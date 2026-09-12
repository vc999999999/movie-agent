from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional
import uuid

from server.config import settings
from agent.continuity import continuity_checker
from agent.comfyui import comfyui_client
from agent.modelscope_gen import modelscope_gen_client
from server.db import db
from agent.llm import llm_service
from agent.models import (
    AuteurContext,
    AuteurSelection,
    BriefExtraction,
    CreativeBrief,
    sanitize_brief_dict,
    FilmProductionPack,
    ProjectBible,
    QuestionsResponse,
    RenderRun,
    SceneSpec,
    ScreenplayPackage,
    ShotSpec,
    TreatmentOption,
    TreatmentPackage,
)
from agent.production_packs import auteur_profile_registry, production_pack_registry
from agent.prompt_compiler import prompt_compiler
from agent.questions import (
    apply_safe_defaults,
    calculate_brief_completion,
    select_questions,
)
from agent.workflow import workflow_registry

class ProjectService:
    def __init__(self):
        self.db = db
        self.llm = llm_service
        self.comfyui = comfyui_client
        self.modelscope = modelscope_gen_client
        self.compiler = prompt_compiler
        self.workflows = workflow_registry
        self.continuity = continuity_checker
        self.production_packs = production_pack_registry
        self.auteur_profiles = auteur_profile_registry

    def get_auteur_context(self, project_id: str) -> Optional[AuteurContext]:
        artifact = self.db.get_latest_artifact(project_id, "auteur_profile")
        return AuteurContext(**artifact["content"]) if artifact else None

    def apply_auteur_profile(
        self,
        project_id: str,
        profile_id: str,
        variant_id: Optional[str] = None,
        intensity: str = "balanced",
        preserve: Optional[list[str]] = None,
    ) -> AuteurContext:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        profile = self.auteur_profiles.get(profile_id)
        variant = self.auteur_profiles.variant(profile, variant_id)
        selection = AuteurSelection(
            profile_id=profile.profile_id,
            variant_id=variant.variant_id,
            intensity=intensity,
            preserve=preserve or [],
        )
        context = AuteurContext(profile=profile, selection=selection)
        self.db.invalidate_artifacts(project_id, [
            "auteur_profile", "treatments", "selected_treatment", "production_pack", "project_bible",
            "screenplay", "shot_list", "continuity_report", "grammar_report",
            "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.save_artifact(project_id, "auteur_profile", context.model_dump(), status="confirmed")
        if project["status"] not in ("collecting", "brief_review"):
            self.db.update_project_status(project_id, "brief_review")
        return context

    def clear_auteur_profile(self, project_id: str) -> None:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        self.db.invalidate_artifacts(project_id, [
            "auteur_profile", "treatments", "selected_treatment", "production_pack", "project_bible",
            "screenplay", "shot_list", "continuity_report", "grammar_report",
            "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        if project["status"] not in ("collecting", "brief_review"):
            self.db.update_project_status(project_id, "brief_review")

    def _record_questions(self, response: QuestionsResponse) -> QuestionsResponse:
        self.db.save_artifact(
            response.project_id,
            "questions",
            response.model_dump(),
            status="current",
        )
        return response

    def _finish_brief_collection(
        self,
        project_id: str,
        brief_data: dict[str, Any],
        round_count: int,
    ) -> QuestionsResponse:
        final_brief, assumptions = apply_safe_defaults(
            brief_data,
            brief_data.get("agent_assumptions", []),
        )
        final_brief["agent_assumptions"] = list(dict.fromkeys(assumptions))
        brief = CreativeBrief(**sanitize_brief_dict(final_brief))
        canonical = brief.model_dump()
        self.db.update_project_brief(project_id, canonical, title=brief.title)
        self.db.update_project_status(project_id, "brief_review")
        self.db.save_artifact(project_id, "creative_brief", canonical, status="ready_for_review")
        return self._record_questions(QuestionsResponse(
            project_id=project_id,
            status="brief_review",
            round=round_count,
            brief_completion=1.0,
            questions=[],
            assumptions=brief.agent_assumptions,
            can_confirm=True,
        ))

    def _merge_brief(
        self,
        project_id: str,
        current: dict[str, Any],
        extraction: BriefExtraction,
    ) -> dict[str, Any]:
        # LLM 的 known 可能带幻觉字段或非法枚举值（如 dialogue_mode="以视觉叙事…"），
        # 统一过白名单清洗，保证后续 CreativeBrief 校验永不因脏数据崩溃。
        merged = {**current, **sanitize_brief_dict(extraction.known)}
        assumptions = [*merged.get("agent_assumptions", []), *extraction.assumptions]
        merged["agent_assumptions"] = list(dict.fromkeys(assumptions))
        self.db.update_project_brief(project_id, merged, title=merged.get("title"))
        return merged

    def _next_questions(
        self,
        project_id: str,
        brief: dict[str, Any],
        extraction: BriefExtraction,
        completed_rounds: int,
        force_review: bool = False,
    ) -> QuestionsResponse:
        completion = calculate_brief_completion(brief)
        if (
            force_review
            or completed_rounds >= settings.max_question_rounds
            or (completion >= 0.85 and not extraction.conflicts)
        ):
            return self._finish_brief_collection(project_id, brief, completed_rounds)

        questions = select_questions(
            known=brief,
            conflicts=extraction.conflicts,
            confidence=extraction.confidence,
            asked_fields=set(),
            max_questions=settings.max_questions_per_round,
        )
        if not questions:
            return self._finish_brief_collection(project_id, brief, completed_rounds)

        return self._record_questions(QuestionsResponse(
            project_id=project_id,
            status="collecting",
            round=completed_rounds + 1,
            brief_completion=completion,
            questions=questions,
            assumptions=brief.get("agent_assumptions", []),
            can_confirm=completion >= 0.6,
        ))

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
            source_text = self.db.append_project_source(project_id, new_user_text)
            self.db.add_message(project_id, "user", new_user_text)

        current_brief = project.get("brief", {})
        extraction = await self.llm.extract_brief(source_text, previous_brief=current_brief)
        merged_brief = self._merge_brief(project_id, current_brief, extraction)
        round_count = project.get("round_count", 0)
        return self._next_questions(
            project_id,
            merged_brief,
            extraction,
            round_count,
            force_review=any(
                phrase in source_text
                for phrase in ["直接生成", "跳过反问", "不需要修改", "确认并生成"]
            ),
        )

    def get_questions(self, project_id: str) -> QuestionsResponse:
        if not self.db.get_project(project_id):
            raise ValueError(f"Project {project_id} not found")
        artifact = self.db.get_latest_artifact(project_id, "questions")
        if not artifact:
            raise ValueError("Questions have not been generated")
        return QuestionsResponse(**artifact["content"])

    # Submit answers
    async def answer_questions(self, project_id: str, answers: list[dict[str, str]]) -> QuestionsResponse:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        current = self.get_questions(project_id)
        allowed_fields = {question.field for question in current.questions}
        answer_fields = [answer.get("field", "") for answer in answers]
        invalid_fields = sorted(set(answer_fields) - allowed_fields)
        if invalid_fields:
            raise ValueError(f"Answers contain fields that were not asked: {', '.join(invalid_fields)}")
        if len(answer_fields) != len(set(answer_fields)):
            raise ValueError("Each question may be answered only once per round")

        round_num = self.db.increment_project_round(project_id)
        self.db.add_message(project_id, "user", f"Answers: {json.dumps(answers, ensure_ascii=False)}")

        # Extraction with answers
        extraction = await self.llm.extract_brief(
            project["source_text"],
            previous_brief=project.get("brief", {}),
            answers=answers,
        )

        merged_brief = self._merge_brief(project_id, project.get("brief", {}), extraction)
        return self._next_questions(project_id, merged_brief, extraction, round_num)

    # 10.1 Brief review & confirm
    def update_brief(self, project_id: str, updates: dict[str, Any]) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        current = dict(project.get("brief", {}))
        current.update(updates)
        brief = CreativeBrief(**sanitize_brief_dict(current))
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="draft")
        self.db.invalidate_artifacts(project_id, [
            "treatments", "selected_treatment", "production_pack",
            "project_bible", "screenplay", "shot_list", "continuity_report",
            "grammar_report", "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.update_project_status(project_id, "brief_review")
        return brief

    async def confirm_brief(self, project_id: str, confirmed_brief: Optional[dict[str, Any]] = None) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        data = confirmed_brief or project.get("brief", {})
        brief = CreativeBrief(**sanitize_brief_dict(data))
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.invalidate_artifacts(project_id, [
            "treatments", "selected_treatment", "production_pack", "project_bible",
            "screenplay", "shot_list", "continuity_report", "grammar_report",
            "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="confirmed")
        self.db.update_project_status(project_id, "screenplay_ready")

        # Auto trigger screenplay generation
        await self.generate_screenplay(project_id)
        return brief

    async def generate_treatments(self, project_id: str) -> TreatmentPackage:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        brief = CreativeBrief(**sanitize_brief_dict(project["brief"]))
        package = await self.llm.generate_treatments(
            brief,
            self.production_packs.relevant(brief),
            self.get_auteur_context(project_id),
        )
        option_ids = [option.treatment_id for option in package.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("Treatment IDs must be unique")
        if package.recommendation not in option_ids:
            raise ValueError("Treatment recommendation does not reference an option")
        for option in package.options:
            self.production_packs.get(option.production_pack_id)

        self.db.invalidate_artifacts(project_id, [
            "selected_treatment", "production_pack", "project_bible", "screenplay",
            "shot_list", "continuity_report", "grammar_report", "prompt_package",
            "auteur_report", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="confirmed")
        self.db.save_artifact(project_id, "treatments", package.model_dump(), status="draft")
        self.db.update_project_status(project_id, "treatment_review")
        return package

    def get_treatments(self, project_id: str) -> Optional[TreatmentPackage]:
        artifact = self.db.get_latest_artifact(project_id, "treatments")
        return TreatmentPackage(**artifact["content"]) if artifact else None

    async def confirm_treatment(
        self,
        project_id: str,
        treatment_id: str,
        production_pack_id: Optional[str] = None,
    ) -> TreatmentOption:
        package = self.get_treatments(project_id)
        if not package:
            raise ValueError("Treatments have not been generated")
        selected = next((option for option in package.options if option.treatment_id == treatment_id), None)
        if not selected:
            raise ValueError(f"Treatment {treatment_id} not found")

        pack = self.production_packs.get(production_pack_id or selected.production_pack_id)
        selected = selected.model_copy(update={"production_pack_id": pack.pack_id})
        self.db.invalidate_artifacts(project_id, [
            "selected_treatment", "production_pack", "project_bible", "screenplay",
            "shot_list", "continuity_report", "grammar_report", "prompt_package",
            "auteur_report", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.save_artifact(project_id, "selected_treatment", selected.model_dump(), status="confirmed")
        self.db.save_artifact(project_id, "production_pack", pack.model_dump(), status="confirmed")
        self.db.update_project_status(project_id, "screenplay_ready")
        await self.generate_screenplay(project_id)
        return selected

    # 10.2 Screenplay & Shots
    async def generate_screenplay(self, project_id: str) -> ScreenplayPackage:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        brief = CreativeBrief(**sanitize_brief_dict(project["brief"]))
        treatment_art = self.db.get_latest_artifact(project_id, "selected_treatment")
        treatment = TreatmentOption(**treatment_art["content"]) if treatment_art else None
        screenplay_pkg = await self.llm.build_screenplay(
            brief,
            treatment,
            self.get_auteur_context(project_id),
        )

        # Save artifacts
        self.db.invalidate_artifacts(project_id, [
            "shot_list", "continuity_report", "grammar_report", "prompt_package",
            "auteur_report", "workflow_plan", "production_report", "rough_cut",
        ])
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

        brief = CreativeBrief(**sanitize_brief_dict(project["brief"]))
        screenplay_data = self.get_screenplay(project_id)
        if not screenplay_data:
            raise ValueError("Screenplay not found. Please generate screenplay first.")

        screenplay_pkg = ScreenplayPackage(
            project_bible=ProjectBible(**screenplay_data["project_bible"]),
            scenes=[SceneSpec(**s) for s in screenplay_data["scenes"]],
        )

        pack_art = self.db.get_latest_artifact(project_id, "production_pack")
        pack = FilmProductionPack(**pack_art["content"]) if pack_art else None
        auteur = self.get_auteur_context(project_id)
        shots = await self.llm.build_shot_list(screenplay_pkg, brief, pack, auteur)

        if not shots:
            raise ValueError("LLM returned an empty shot list")

        # Reject invalid plans instead of silently stretching one shot past its limit.
        total_dur = sum(s.duration_seconds for s in shots)
        target_dur = brief.duration_seconds
        tolerance = target_dur * 0.05
        if abs(total_dur - target_dur) > tolerance:
            raise ValueError(
                f"Shot duration total {total_dur:.1f}s exceeds the 5% tolerance for {target_dur}s"
            )

        # Continuity check
        issues = self.continuity.check_deterministic(shots, screenplay_pkg.project_bible)
        grammar_issues = self.production_packs.validate_shots(shots, pack) if pack else []
        auteur_issues = self.auteur_profiles.validate_shots(shots, auteur) if auteur else []

        # Save artifacts
        self.db.invalidate_artifacts(
            project_id,
            ["prompt_package", "workflow_plan", "production_report", "rough_cut"],
        )
        self.db.save_artifact(project_id, "shot_list", [s.model_dump() for s in shots], status="draft")
        self.db.save_artifact(project_id, "continuity_report", [i.model_dump() for i in issues], status="draft")
        self.db.save_artifact(project_id, "grammar_report", [i.model_dump() for i in grammar_issues], status="draft")
        self.db.save_artifact(project_id, "auteur_report", [i.model_dump() for i in auteur_issues], status="draft")
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
        self.db.invalidate_artifacts(
            project_id,
            ["prompt_package", "workflow_plan", "production_report", "rough_cut"],
        )
        self.db.update_project_status(project_id, "shots_review")

        # Run continuity recheck
        screenplay_data = self.get_screenplay(project_id)
        if screenplay_data:
            bible = ProjectBible(**screenplay_data["project_bible"])
            all_specs = [ShotSpec(**s) for s in updated_shots]
            issues = self.continuity.check_deterministic(all_specs, bible)
            self.db.save_artifact(project_id, "continuity_report", [i.model_dump() for i in issues], status="draft")

            pack_art = self.db.get_latest_artifact(project_id, "production_pack")
            if pack_art:
                pack = FilmProductionPack(**pack_art["content"])
                grammar_issues = self.production_packs.validate_shots(all_specs, pack)
                self.db.save_artifact(project_id, "grammar_report", [i.model_dump() for i in grammar_issues], status="draft")

            auteur = self.get_auteur_context(project_id)
            if auteur:
                auteur_issues = self.auteur_profiles.validate_shots(all_specs, auteur)
                self.db.save_artifact(project_id, "auteur_report", [i.model_dump() for i in auteur_issues], status="draft")

        return target_shot

    async def confirm_shots(self, project_id: str) -> list[dict[str, Any]]:
        shots_data = self.get_shots(project_id)
        if not shots_data:
            raise ValueError(f"No shots found for project {project_id}")
        grammar_art = self.db.get_latest_artifact(project_id, "grammar_report")
        auteur_art = self.db.get_latest_artifact(project_id, "auteur_report")
        reports = [artifact for artifact in (grammar_art, auteur_art) if artifact]
        grammar_errors = [
            issue for artifact in reports for issue in artifact["content"] if issue["severity"] == "error"
        ]
        if grammar_errors:
            raise ValueError(f"Shot list has {len(grammar_errors)} directing grammar error(s)")

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
        if not shots:
            raise ValueError("Shot list required to compile packages")

        prompt_packages: list[dict[str, Any]] = []
        workflow_plans: list[dict[str, Any]] = []

        project_dir = settings.data_dir / project_id
        patched_dir = project_dir / "patched_workflows"
        patched_dir.mkdir(parents=True, exist_ok=True)

        installed_nodes = set((await self.comfyui.get_object_info()).keys())
        pack_art = self.db.get_latest_artifact(project_id, "production_pack")
        preferred_workflow_id = pack_art["content"]["generation_recipe"]["workflow_id"] if pack_art else None

        for shot in shots:
            # 1. Select workflow
            plan = self.workflows.select_workflow(
                shot,
                aspect_ratio=bible.aspect_ratio,
                comfyui_installed_nodes=installed_nodes,
                preferred_workflow_id=preferred_workflow_id,
            )

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
                _, err = self.workflows.patch_workflow(
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

        if (
            not target_plan
            or target_plan.get("status") != "matched"
            or not target_plan.get("workflow_id")
            or not target_prompt
        ):
            raise ValueError(f"Shot {shot_id} has no matched workflow")

        workflow_path = target_plan.get("patched_workflow_path")
        if not workflow_path:
            raise ValueError(f"Patched workflow JSON for {shot_id} is missing")
        workflow_file = self._project_file(project_id, workflow_path)
        if not workflow_file.is_file():
            raise ValueError(f"Patched workflow JSON for {shot_id} does not exist at {workflow_path}")

        with workflow_file.open("r", encoding="utf-8") as f:
            workflow_json = json.load(f)

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run_data = {
            "id": run_id,
            "project_id": project_id,
            "shot_id": shot_id,
            "workflow_id": target_plan["workflow_id"],
            "status": "running",
            "request_json": target_prompt,
        }
        self.db.create_render_run(run_data)

        # Cloud backend: ModelScope API-Inference (text_to_video, GPU-less hosts)
        if settings.render_backend == "modelscope":
            if not self.modelscope.available:
                error = {"code": "MS_KEY_MISSING", "message": "MODELSCOPE_API_KEY 未配置，无法使用云端生成后端"}
                self.db.update_render_run(run_id, status="failed", error_json=error)
                return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

            positive = target_prompt.get("positive_prompt", "")
            negative = target_prompt.get("negative_prompt", "")
            asset_url, gen_err = await self.modelscope.generate_video(positive, negative)
            if gen_err or not asset_url:
                self.db.update_render_run(
                    run_id, status="failed",
                    error_json=gen_err.model_dump() if gen_err else {"code": "MS_OUTPUT_MISSING", "message": "云端任务未返回视频"},
                )
                return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

            out_dir = settings.data_dir / project_id / "outputs"
            dest_video = out_dir / f"{shot_id}.mp4"
            sha = await self.modelscope.download_asset(asset_url, dest_video)
            if not sha:
                error = {"code": "MS_DOWNLOAD_FAILED", "message": "云端视频下载失败"}
                self.db.update_render_run(run_id, status="failed", error_json=error)
                return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

            output_info = {"backend": "modelscope", "task_url": asset_url, "file_path": str(dest_video), "sha256": sha}
            self.db.update_render_run(run_id, status="success", output_json=output_info)
            return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

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

        asset = self.comfyui.first_video_output(history_res or {})
        if not asset:
            error = {"code": "COMFYUI_OUTPUT_MISSING", "message": "ComfyUI 任务未输出视频文件"}
            self.db.update_render_run(run_id, status="failed", error_json=error)
            return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

        out_dir = settings.data_dir / project_id / "outputs"
        dest_video = out_dir / f"{shot_id}.mp4"
        sha = await self.comfyui.download_output_asset(
            asset["filename"],
            asset["subfolder"],
            asset["type"],
            dest_video,
        )
        if not sha:
            error = {"code": "COMFYUI_DOWNLOAD_FAILED", "message": "ComfyUI 输出文件下载失败"}
            self.db.update_render_run(run_id, status="failed", error_json=error)
            return RenderRun(**self.db.get_render_run(run_id))  # type: ignore[arg-type]

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
        if not shots:
            raise ValueError(f"No shots found for project {project_id}")
        runs = []
        all_success = True

        try:
            for s in shots:
                run = await self.render_shot(project_id, s["shot_id"])
                runs.append(run)
                if run.status != "success":
                    all_success = False
        except Exception:
            self.db.update_project_status(project_id, "failed")
            raise

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

        current_prompts = {
            prompt["shot_id"]: prompt
            for prompt in self.get_packages(project_id).get("prompt_packages", [])
        }
        missing = []
        for shot in shots:
            shot_id = shot["shot_id"]
            run = self.db.get_latest_successful_render(project_id, shot_id)
            if (
                not (out_dir / f"{shot_id}.mp4").is_file()
                or not run
                or run["request_json"] != current_prompts.get(shot_id)
            ):
                missing.append(shot_id)
        if missing:
            raise ValueError(f"Cannot create rough cut; missing current renders: {', '.join(missing)}")

        concat_list_file = out_dir / "concat_list.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for s in shots:
                shot_file = out_dir / f"{s['shot_id']}.mp4"
                escaped_path = str(shot_file.resolve()).replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")

        args = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file),
            "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(rough_cut_path), "-loglevel", "error",
        ]
        proc = await asyncio.create_subprocess_exec(*args, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not rough_cut_path.is_file() or rough_cut_path.stat().st_size == 0:
            rough_cut_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg rough cut failed: {stderr.decode(errors='replace')[-2000:]}")

        self.db.save_artifact(
            project_id,
            "rough_cut",
            {"file_path": str(rough_cut_path)},
            status="confirmed",
        )
        return str(rough_cut_path)

    @staticmethod
    def _project_file(project_id: str, path: str) -> Path:
        project_root = (settings.data_dir / project_id).resolve()
        raw_path = Path(path)
        candidate = (raw_path if raw_path.is_absolute() else project_root / raw_path).resolve()
        if not candidate.is_relative_to(project_root):
            raise ValueError("Workflow path is outside the project directory")
        return candidate

    # Generation Pipeline: run every remaining production step in order,
    # yielding per-step progress for the frontend "generation chain" UI.
    PIPELINE_STEPS = ["treatments", "treatment_choice", "screenplay", "shots", "packages", "render", "rough_cut"]

    async def run_auto_pipeline(self, project_id: str) -> dict[str, Any]:
        """Execute the full generation chain from the current project state.

        Starts at whichever step is next for the project's status; reuses
        existing artifacts when they are already present. Returns a step log.
        """
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        log: list[dict[str, Any]] = []

        def record(step: str, status: str, detail: Any = None, error: Optional[str] = None) -> None:
            entry: dict[str, Any] = {"step": step, "status": status}
            if detail is not None:
                entry["detail"] = detail
            if error:
                entry["error"] = error
            log.append(entry)
            # Mirror into the shared progress state for polling UIs;
            # create the slot lazily so direct run_auto_pipeline callers work too
            state = self._pipeline_progress.setdefault(
                project_id, {"steps": [], "status": "running", "error": None}
            )
            state["steps"] = list(log)

        async def run_step(step: str, fn, detail_fn=None):
            record(step, "running")
            try:
                outcome = fn()
                # Lambdas wrapping async methods return coroutines; await them.
                result = await outcome if asyncio.iscoroutine(outcome) else outcome
                record(step, "done", detail_fn(result) if detail_fn else None)
                return result
            except Exception as e:
                record(step, "failed", error=str(e)[:500])
                raise

        status = project["status"]

        # 1-2. Treatments (only needed before one has been confirmed).
        # confirm_brief jumps straight to screenplay_ready, so rely on the
        # selected_treatment artifact rather than the status alone.
        selected_pack = self.db.get_latest_artifact(project_id, "selected_treatment")
        if not selected_pack:
            package = await run_step(
                "treatments", lambda: self.generate_treatments(project_id),
                lambda p: f"{len(p.options)} 个方案",
            )
            # Auto-pick the recommended treatment
            await run_step(
                "treatment_choice",
                lambda: self.confirm_treatment(project_id, package.recommendation),
                lambda opt: opt.name,
            )
        else:
            record("treatments", "done", detail="已有导演方案，跳过")
            record("treatment_choice", "done", detail="方案已确认，跳过")

        # 3. Screenplay (confirm_brief / confirm_treatment already trigger it;
        #    run explicitly when the artifact is missing)
        if not self.db.get_latest_artifact(project_id, "screenplay"):
            await run_step("screenplay", lambda: self.generate_screenplay(project_id))
        else:
            record("screenplay", "done", detail="已有剧本，跳过")

        # 4. Shots
        shots = self.get_shots(project_id)
        if not shots:
            shots = await run_step("shots", lambda: self.generate_shots(project_id))
        else:
            record("shots", "done", detail=f"已有 {len(shots)} 个镜头，跳过")

        # 5. Prompt packages & workflow patching
        packages = self.get_packages(project_id)
        if not packages.get("prompt_packages"):
            await run_step(
                "packages", lambda: self.compile_packages(project_id),
                lambda p: f"{len(p.get('prompt_packages', []))} 个镜头包",
            )
        else:
            record("packages", "done", detail="已编译，跳过")

        # 6. Render every shot sequentially
        runs = await run_step(
            "render", lambda: self.render_all_shots(project_id),
            lambda rs: f"{sum(1 for r in rs if r.status == 'success')}/{len(rs)} 成功",
        )
        failed = [r for r in runs if r.status != "success"]
        if failed:
            raise RuntimeError(
                "镜头渲染失败: "
                + ", ".join(
                    f"{r.shot_id}({(r.error_json or {}).get('message', '未知错误')})"
                    for r in failed
                )
            )

        # 7. Rough cut
        await run_step("rough_cut", lambda: self.create_rough_cut(project_id))

        return {"project_id": project_id, "steps": log, "status": "completed"}

    # Background pipeline execution + orchestration-view state.
    _pipeline_progress: dict[str, dict[str, Any]] = {}
    _pipeline_tasks: dict[str, asyncio.Task] = {}

    def start_auto_pipeline(self, project_id: str) -> dict[str, Any]:
        """Start the auto pipeline as a background task (idempotent)."""
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        existing = self._pipeline_tasks.get(project_id)
        if existing and not existing.done():
            return {"project_id": project_id, "status": "running", "message": "生成集已在进行中"}

        self._pipeline_progress[project_id] = {"steps": [], "status": "running", "error": None}

        async def runner() -> None:
            state = self._pipeline_progress[project_id]
            try:
                await self.run_auto_pipeline(project_id)
                state["status"] = "completed"
            except Exception as e:
                state["status"] = "failed"
                state["error"] = str(e)[:500]

        self._pipeline_tasks[project_id] = asyncio.create_task(runner())
        return {"project_id": project_id, "status": "running"}

    def get_pipeline_status(self, project_id: str) -> dict[str, Any]:
        """Orchestration view state: step log + per-shot render status."""
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        progress = self._pipeline_progress.get(project_id, {"steps": [], "status": "idle", "error": None})

        # Latest run per shot (list_render_runs is newest-first)
        latest_by_shot: dict[str, dict[str, Any]] = {}
        for run in self.db.list_render_runs(project_id):
            latest_by_shot.setdefault(run["shot_id"], run)
        shots = [
            {
                "shot_id": shot_id,
                "status": run["status"],
                "error": (run.get("error_json") or {}).get("message"),
            }
            for shot_id, run in latest_by_shot.items()
        ]

        # Artifact presence so idle states still show completed waves
        artifacts = {
            "brief": bool(project.get("brief")),
            "treatments": bool(self.db.get_latest_artifact(project_id, "treatments")),
            "screenplay": bool(self.db.get_latest_artifact(project_id, "screenplay")),
            "shots": len(self.get_shots(project_id)) > 0,
            "packages": bool(self.get_packages(project_id).get("prompt_packages")),
            "rough_cut": bool(self.db.get_latest_artifact(project_id, "rough_cut")),
        }
        # Render status from artifacts/runs even when not running via pipeline
        shot_list = self.get_shots(project_id)
        if progress["status"] == "idle" and artifacts["rough_cut"]:
            render_done = all(latest_by_shot.get(s["shot_id"], {}).get("status") == "success" for s in shot_list)
            if render_done and shot_list:
                progress["status"] = "completed"

        return {
            "project_id": project_id,
            "project_status": project["status"],
            "pipeline": progress,
            "shots": shots,
            "artifacts": artifacts,
        }

project_service = ProjectService()
