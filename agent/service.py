from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional
import uuid

from server.config import settings
from agent.continuity import continuity_checker
from agent.comfyui import comfyui_client
from server.db import db
from agent.llm import llm_service
from agent.models import (
    CreativeBrief,
    ErrorDetail,
    ProjectBible,
    ProjectStatus,
    QuestionsResponse,
    RenderRun,
    SceneSpec,
    ScreenplayPackage,
    ShotPrompt,
    ShotSpec,
    WorkflowPlan,
)
from agent.prompt_compiler import prompt_compiler
from agent.questions import (
    apply_safe_defaults,
    calculate_brief_completion,
    select_questions,
)
from agent.workflow import workflow_registry

logger = logging.getLogger(__name__)

class ProjectService:
    def __init__(self):
        self.db = db
        self.llm = llm_service
        self.comfyui = comfyui_client
        self.compiler = prompt_compiler
        self.workflows = workflow_registry
        self.continuity = continuity_checker

    # 10.1 Projects
    def create_project(self, source_text: str, title: Optional[str] = None) -> dict[str, Any]:
        project_id = f"prj_{uuid.uuid4().hex[:8]}"
        project = self.db.create_project(project_id, title, source_text)
        self.db.add_message(project_id, "user", source_text)
        return project

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        return self.db.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        return self.db.list_projects()

    # Analyze input and pick first questions
    async def analyze_input(self, project_id: str, new_user_text: Optional[str] = None) -> QuestionsResponse:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        source_text = project["source_text"]
        if new_user_text:
            source_text += f"\n{new_user_text}"
            self.db.add_message(project_id, "user", new_user_text)

        current_brief = project.get("brief", {})
        extraction = await self.llm.extract_brief(source_text, previous_brief=current_brief)

        # Merge extracted known fields into brief
        merged_brief = dict(current_brief)
        merged_brief.update(extraction.known)
        for assump in extraction.assumptions:
            if "agent_assumptions" not in merged_brief:
                merged_brief["agent_assumptions"] = []
            if assump not in merged_brief["agent_assumptions"]:
                merged_brief["agent_assumptions"].append(assump)

        self.db.update_project_brief(project_id, merged_brief, title=merged_brief.get("title"))

        # Check round and completion
        completion = calculate_brief_completion(merged_brief)
        round_count = project.get("round_count", 0)

        # Determine if we should proceed to brief_review
        ready_to_review = False
        if round_count >= settings.max_question_rounds:
            ready_to_review = True
        elif completion >= 0.85 and not extraction.conflicts:
            ready_to_review = True
        elif any(k in source_text for k in ["直接生成", "跳过反问", "不需要修改", "确认并生成"]):
            ready_to_review = True

        if ready_to_review:
            # Apply safe defaults
            final_brief, updated_assump = apply_safe_defaults(merged_brief, merged_brief.get("agent_assumptions", []))
            final_brief["agent_assumptions"] = updated_assump
            self.db.update_project_brief(project_id, final_brief)
            self.db.update_project_status(project_id, "brief_review")
            self.db.save_artifact(project_id, "creative_brief", final_brief, status="ready_for_review")

            return QuestionsResponse(
                project_id=project_id,
                status="brief_review",
                round=round_count,
                brief_completion=1.0,
                questions=[],
                assumptions=updated_assump,
                can_confirm=True,
            )

        # Select questions
        questions = select_questions(
            known=merged_brief,
            conflicts=extraction.conflicts,
            confidence=extraction.confidence,
            asked_fields=set(),
            max_questions=settings.max_questions_per_round,
        )

        if not questions:
            # No more questions to ask
            final_brief, updated_assump = apply_safe_defaults(merged_brief, merged_brief.get("agent_assumptions", []))
            final_brief["agent_assumptions"] = updated_assump
            self.db.update_project_brief(project_id, final_brief)
            self.db.update_project_status(project_id, "brief_review")
            self.db.save_artifact(project_id, "creative_brief", final_brief, status="ready_for_review")

            return QuestionsResponse(
                project_id=project_id,
                status="brief_review",
                round=round_count,
                brief_completion=1.0,
                questions=[],
                assumptions=updated_assump,
                can_confirm=True,
            )

        return QuestionsResponse(
            project_id=project_id,
            status="collecting",
            round=round_count + 1,
            brief_completion=completion,
            questions=questions,
            assumptions=merged_brief.get("agent_assumptions", []),
            can_confirm=completion >= 0.6,
        )

    # Submit answers
    async def answer_questions(self, project_id: str, answers: list[dict[str, str]]) -> QuestionsResponse:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        round_num = self.db.increment_project_round(project_id)
        self.db.add_message(project_id, "user", f"Answers: {json.dumps(answers, ensure_ascii=False)}")

        # Extraction with answers
        extraction = await self.llm.extract_brief(
            project["source_text"],
            previous_brief=project.get("brief", {}),
            answers=answers,
        )

        merged_brief = dict(project.get("brief", {}))
        merged_brief.update(extraction.known)
        for assump in extraction.assumptions:
            if "agent_assumptions" not in merged_brief:
                merged_brief["agent_assumptions"] = []
            if assump not in merged_brief["agent_assumptions"]:
                merged_brief["agent_assumptions"].append(assump)

        self.db.update_project_brief(project_id, merged_brief)

        completion = calculate_brief_completion(merged_brief)
        ready_to_review = round_num >= settings.max_question_rounds or (completion >= 0.85 and not extraction.conflicts)

        if ready_to_review:
            final_brief, updated_assump = apply_safe_defaults(merged_brief, merged_brief.get("agent_assumptions", []))
            final_brief["agent_assumptions"] = updated_assump
            self.db.update_project_brief(project_id, final_brief)
            self.db.update_project_status(project_id, "brief_review")
            self.db.save_artifact(project_id, "creative_brief", final_brief, status="ready_for_review")

            return QuestionsResponse(
                project_id=project_id,
                status="brief_review",
                round=round_num,
                brief_completion=1.0,
                questions=[],
                assumptions=updated_assump,
                can_confirm=True,
            )

        # Select next questions
        questions = select_questions(
            known=merged_brief,
            conflicts=extraction.conflicts,
            confidence=extraction.confidence,
            asked_fields=set(),
            max_questions=settings.max_questions_per_round,
        )

        if not questions:
            final_brief, updated_assump = apply_safe_defaults(merged_brief, merged_brief.get("agent_assumptions", []))
            final_brief["agent_assumptions"] = updated_assump
            self.db.update_project_brief(project_id, final_brief)
            self.db.update_project_status(project_id, "brief_review")
            self.db.save_artifact(project_id, "creative_brief", final_brief, status="ready_for_review")

            return QuestionsResponse(
                project_id=project_id,
                status="brief_review",
                round=round_num,
                brief_completion=1.0,
                questions=[],
                assumptions=updated_assump,
                can_confirm=True,
            )

        return QuestionsResponse(
            project_id=project_id,
            status="collecting",
            round=round_num,
            brief_completion=completion,
            questions=questions,
            assumptions=merged_brief.get("agent_assumptions", []),
            can_confirm=completion >= 0.6,
        )

    # 10.1 Brief review & confirm
    def update_brief(self, project_id: str, updates: dict[str, Any]) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        current = dict(project.get("brief", {}))
        current.update(updates)
        brief = CreativeBrief(**current)
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="draft")
        return brief

    async def confirm_brief(self, project_id: str, confirmed_brief: Optional[dict[str, Any]] = None) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        data = confirmed_brief or project.get("brief", {})
        brief = CreativeBrief(**data)
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="confirmed")
        self.db.update_project_status(project_id, "screenplay_ready")

        # Auto trigger screenplay generation
        await self.generate_screenplay(project_id)
        return brief

    # 10.2 Screenplay & Shots
    async def generate_screenplay(self, project_id: str) -> ScreenplayPackage:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        brief = CreativeBrief(**project["brief"])
        screenplay_pkg = await self.llm.build_screenplay(brief)

        # Save artifacts
        self.db.save_artifact(project_id, "project_bible", screenplay_pkg.project_bible.model_dump(), status="confirmed")
        self.db.save_artifact(project_id, "screenplay", [s.model_dump() for s in screenplay_pkg.scenes], status="confirmed")

        # Automatically generate shot list
        await self.generate_shots(project_id)
        return screenplay_pkg

    def get_screenplay(self, project_id: str) -> Optional[dict[str, Any]]:
        bible_art = self.db.get_latest_artifact(project_id, "project_bible")
        scenes_art = self.db.get_latest_artifact(project_id, "screenplay")
        if not bible_art or not scenes_art:
            return None
        return {
            "project_bible": bible_art["content"],
            "scenes": scenes_art["content"]
        }

    async def generate_shots(self, project_id: str) -> list[ShotSpec]:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        brief = CreativeBrief(**project["brief"])
        screenplay_data = self.get_screenplay(project_id)
        if not screenplay_data:
            raise ValueError("Screenplay not found. Please generate screenplay first.")

        screenplay_pkg = ScreenplayPackage(
            project_bible=ProjectBible(**screenplay_data["project_bible"]),
            scenes=[SceneSpec(**s) for s in screenplay_data["scenes"]],
        )

        shots = await self.llm.build_shot_list(screenplay_pkg, brief)

        # Validate total duration (5% tolerance)
        total_dur = sum(s.duration_seconds for s in shots)
        target_dur = brief.duration_seconds
        tolerance = target_dur * 0.05
        if abs(total_dur - target_dur) > tolerance:
            # Adjust last shot duration to strictly satisfy conservation
            diff = round(target_dur - total_dur, 1)
            new_dur = round(shots[-1].duration_seconds + diff, 1)
            if new_dur > 0:
                shots[-1].duration_seconds = new_dur

        # Continuity check
        issues = self.continuity.check_deterministic(shots, screenplay_pkg.project_bible)

        # Save artifacts
        self.db.save_artifact(project_id, "shot_list", [s.model_dump() for s in shots], status="draft")
        self.db.save_artifact(project_id, "continuity_report", [i.model_dump() for i in issues], status="draft")
        self.db.update_project_status(project_id, "shots_review")

        return shots

    def get_shots(self, project_id: str) -> list[dict[str, Any]]:
        shots_art = self.db.get_latest_artifact(project_id, "shot_list")
        return shots_art["content"] if shots_art else []

    def update_shot(self, project_id: str, shot_id: str, shot_updates: dict[str, Any]) -> ShotSpec:
        shots_data = self.get_shots(project_id)
        if not shots_data:
            raise ValueError(f"No shots found for project {project_id}")

        updated_shots = []
        target_shot = None
        for s in shots_data:
            if s["shot_id"] == shot_id:
                s.update(shot_updates)
                target_shot = ShotSpec(**s)
                updated_shots.append(target_shot.model_dump())
            else:
                updated_shots.append(s)

        if not target_shot:
            raise ValueError(f"Shot {shot_id} not found in project {project_id}")

        self.db.save_artifact(project_id, "shot_list", updated_shots, status="draft")

        # Run continuity recheck
        screenplay_data = self.get_screenplay(project_id)
        if screenplay_data:
            bible = ProjectBible(**screenplay_data["project_bible"])
            all_specs = [ShotSpec(**s) for s in updated_shots]
            issues = self.continuity.check_deterministic(all_specs, bible)
            self.db.save_artifact(project_id, "continuity_report", [i.model_dump() for i in issues], status="draft")

        return target_shot

    async def confirm_shots(self, project_id: str) -> list[dict[str, Any]]:
        shots_data = self.get_shots(project_id)
        if not shots_data:
            raise ValueError(f"No shots found for project {project_id}")

        self.db.save_artifact(project_id, "shot_list", shots_data, status="confirmed")
        self.db.update_project_status(project_id, "package_ready")

        # Automatically compile prompt packages and match workflows
        await self.compile_packages(project_id)
        return shots_data

    # 10.3 Prompt & Workflow packages
    async def compile_packages(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        screenplay_data = self.get_screenplay(project_id)
        if not screenplay_data:
            raise ValueError("Screenplay required to compile packages")

        bible = ProjectBible(**screenplay_data["project_bible"])
        shots = [ShotSpec(**s) for s in self.get_shots(project_id)]

        prompt_packages: list[dict[str, Any]] = []
        workflow_plans: list[dict[str, Any]] = []

        project_dir = settings.data_dir / project_id
        patched_dir = project_dir / "patched_workflows"
        patched_dir.mkdir(parents=True, exist_ok=True)

        for shot in shots:
            # 1. Select workflow
            plan = self.workflows.select_workflow(shot, aspect_ratio=bible.aspect_ratio)

            # 2. Compile prompt
            wf_profile = self.workflows.get_profile(plan.workflow_id).model_dump() if plan.workflow_id else None
            rules = self.workflows.get_prompt_rules(plan.workflow_id) if plan.workflow_id else {}

            prompt_pkg = self.compiler.compile(
                shot=shot,
                project_bible=bible,
                workflow_profile=wf_profile,
                prompt_rules=rules,
                quality="standard",
            )

            # 3. Patch workflow JSON if matched
            if plan.status == "matched" and plan.workflow_id:
                out_path = patched_dir / f"{shot.shot_id}_workflow.json"
                patched_dict, err = self.workflows.patch_workflow(
                    workflow_id=plan.workflow_id,
                    prompt_pkg=prompt_pkg,
                    output_file_path=out_path,
                )
                if not err:
                    plan.patched_workflow_path = str(out_path)
                else:
                    plan.status = "precheck_failed"
                    plan.reason = err.message

            prompt_packages.append(prompt_pkg.model_dump())
            workflow_plans.append(plan.model_dump())

        # Save artifacts
        self.db.save_artifact(project_id, "prompt_package", prompt_packages, status="confirmed")
        self.db.save_artifact(project_id, "workflow_plan", workflow_plans, status="confirmed")

        # Generate production report markdown
        report_md = self._generate_production_report(project, bible, shots, prompt_packages, workflow_plans)
        self.db.save_artifact(project_id, "production_report", {"markdown": report_md}, status="confirmed")

        return {
            "prompt_packages": prompt_packages,
            "workflow_plans": workflow_plans,
            "production_report": report_md,
        }

    def _generate_production_report(
        self,
        project: dict[str, Any],
        bible: ProjectBible,
        shots: list[ShotSpec],
        packages: list[dict[str, Any]],
        plans: list[dict[str, Any]],
    ) -> str:
        total_dur = sum(s.duration_seconds for s in shots)
        matched_count = sum(1 for p in plans if p.get("status") == "matched")

        lines = [
            f"# 🎬 《{bible.title}》 电影 Agent 制作与执行报告",
            f"\n- **项目 ID**: `{project['id']}`",
            f"- **成片时长**: 目标 {bible.target_duration} 秒 | 镜头总计 {total_dur:.1f} 秒 (误差: {abs(total_dur - bible.target_duration):.2f}s)",
            f"- **画面比例**: {bible.aspect_ratio}",
            f"- **视觉风格**: {bible.visual_style}",
            f"- **镜头总数**: {len(shots)} 个镜头 | 兼容工作流: {matched_count}/{len(shots)}",
            "\n## 1. 人物与场景设定 (ProjectBible)",
            "\n### 角色列表",
        ]
        for c in bible.characters:
            lines.append(f"- **{c.name}** ({c.narrative_role}): {c.fixed_appearance}, 统一着装: {c.fixed_costume}")

        lines.append("\n### 场景列表")
        for l in bible.locations:
            lines.append(f"- **{l.name}** ({l.time_of_day}): {l.fixed_visual_description}")

        lines.append("\n## 2. 镜头清单与工作流匹配")
        for idx, shot in enumerate(shots):
            plan = plans[idx] if idx < len(plans) else {}
            pkg = packages[idx] if idx < len(packages) else {}
            wf_str = plan.get("workflow_id") or "无适配模板"
            status_badge = "✅ MATCHED" if plan.get("status") == "matched" else f"❌ {plan.get('status')}"

            lines.extend([
                f"\n### 镜头 {shot.shot_id} ({shot.duration_seconds}s) - {status_badge}",
                f"- **景别机位**: {shot.shot_size} | 角度: {shot.camera_angle} | 运镜: {shot.camera_movement}",
                f"- **动作描述**: {shot.action}",
                f"- **匹配工作流**: `{wf_str}`",
                f"- **正向提示词**: `{pkg.get('positive_prompt', '')[:120]}...`",
                f"- **负向提示词**: `{pkg.get('negative_prompt', '')[:80]}...`",
                f"- **生成参数**: 尺寸 {pkg.get('width')}x{pkg.get('height')} | 帧数 {pkg.get('frame_count')} | Seed: {pkg.get('seed')}",
            ])

        lines.append("\n## 3. 下一步指引")
        lines.append("- 点击前端或调用 `/api/shots/{shot_id}/render` 即可直接调度 ComfyUI 执行渲染。")
        lines.append("- 全部镜头生成完成后，调用 `/api/projects/{project_id}/rough_cut` 即可调用 FFmpeg 自动合成为完整预告片短片。")

        return "\n".join(lines)

    def get_packages(self, project_id: str) -> dict[str, Any]:
        pkg_art = self.db.get_latest_artifact(project_id, "prompt_package")
        wf_art = self.db.get_latest_artifact(project_id, "workflow_plan")
        rep_art = self.db.get_latest_artifact(project_id, "production_report")
        return {
            "prompt_packages": pkg_art["content"] if pkg_art else [],
            "workflow_plans": wf_art["content"] if wf_art else [],
            "production_report": rep_art["content"]["markdown"] if rep_art else "",
        }

    # 10.3 Render Execution
    async def render_shot(self, project_id: str, shot_id: str) -> RenderRun:
        packages_data = self.get_packages(project_id)
        wf_plans = packages_data.get("workflow_plans", [])
        prompts = packages_data.get("prompt_packages", [])

        target_plan = next((p for p in wf_plans if p["shot_id"] == shot_id), None)
        target_prompt = next((p for p in prompts if p["shot_id"] == shot_id), None)

        if not target_plan or not target_plan.get("workflow_id"):
            raise ValueError(f"Shot {shot_id} has no matched workflow")

        workflow_path = target_plan.get("patched_workflow_path")
        if not workflow_path or not os.path.exists(workflow_path):
            raise ValueError(f"Patched workflow JSON for {shot_id} does not exist at {workflow_path}")

        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_json = json.load(f)

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run_data = {
            "id": run_id,
            "project_id": project_id,
            "shot_id": shot_id,
            "workflow_id": target_plan["workflow_id"],
            "status": "running",
            "request_json": target_prompt,
            "created_at": "",
        }
        self.db.create_render_run(run_data)

        # Submit to ComfyUI
        prompt_id, err = await self.comfyui.submit_prompt(workflow_json)
        if err or not prompt_id:
            self.db.update_render_run(run_id, status="failed", error_json=err.model_dump() if err else None)
            return RenderRun(**self.db.get_render_run(run_id))  # type: ignore

        self.db.update_render_run(run_id, status="running", prompt_id=prompt_id)

        # Wait for completion
        history_res, exec_err = await self.comfyui.wait_for_completion(prompt_id)
        if exec_err:
            self.db.update_render_run(run_id, status="failed", error_json=exec_err.model_dump())
            return RenderRun(**self.db.get_render_run(run_id))  # type: ignore

        # Download asset
        out_dir = settings.data_dir / project_id / "outputs"
        dest_video = out_dir / f"{shot_id}.mp4"
        sha = await self.comfyui.download_output_asset(f"{prompt_id}.mp4", "output", "video", dest_video)

        output_info = {
            "prompt_id": prompt_id,
            "file_path": str(dest_video),
            "sha256": sha,
            "history": history_res
        }
        self.db.update_render_run(run_id, status="success", output_json=output_info)
        return RenderRun(**self.db.get_render_run(run_id))  # type: ignore

    async def render_all_shots(self, project_id: str) -> list[RenderRun]:
        self.db.update_project_status(project_id, "rendering")
        shots = self.get_shots(project_id)
        runs = []
        all_success = True

        for s in shots:
            try:
                run = await self.render_shot(project_id, s["shot_id"])
                runs.append(run)
                if run.status != "success":
                    all_success = False
            except Exception as e:
                logger.error(f"Render shot {s['shot_id']} failed: {e}")
                all_success = False

        if all_success:
            self.db.update_project_status(project_id, "completed")
        else:
            self.db.update_project_status(project_id, "failed")

        return runs

    # Phase 4 / Rough Cut: Stitch shots into unified MP4 with FFmpeg
    async def create_rough_cut(self, project_id: str) -> str:
        shots = self.get_shots(project_id)
        if not shots:
            raise ValueError("No shots in project")

        out_dir = settings.data_dir / project_id / "outputs"
        out_dir.mkdir(parents=True, exist_ok=True)
        rough_cut_path = out_dir / "rough_cut.mp4"

        # Prepare concat list
        concat_list_file = out_dir / "concat_list.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for s in shots:
                shot_file = out_dir / f"{s['shot_id']}.mp4"
                if not shot_file.exists():
                    # Generate a placeholder 2s shot if not yet rendered
                    cmd = f'ffmpeg -y -f lavfi -i testsrc=duration={s["duration_seconds"]}:size=1280x720:rate=24 -f lavfi -i sine=frequency=440:duration={s["duration_seconds"]} -pix_fmt yuv420p "{str(shot_file)}" -loglevel error'
                    proc = await asyncio.create_subprocess_shell(cmd)
                    await proc.communicate()
                f.write(f"file '{shot_file.resolve()}'\n")

        # Stitch videos with ffmpeg concat demuxer
        cmd = f'ffmpeg -y -f concat -safe 0 -i "{str(concat_list_file)}" -c copy "{str(rough_cut_path)}" -loglevel error'
        proc = await asyncio.create_subprocess_shell(cmd)
        await proc.communicate()

        if not rough_cut_path.exists():
            # Fallback if concat copy had codec mismatch
            cmd = f'ffmpeg -y -f concat -safe 0 -i "{str(concat_list_file)}" -c:v libx264 -pix_fmt yuv420p "{str(rough_cut_path)}" -loglevel error'
            proc = await asyncio.create_subprocess_shell(cmd)
            await proc.communicate()

        return str(rough_cut_path)

project_service = ProjectService()
