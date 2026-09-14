from __future__ import annotations

import asyncio
import json
import time
import hashlib
import re
from pathlib import Path
from typing import Any, Optional
import uuid

from server.config import settings
from agent.execution import exclusive, lease_context, metrics_context, evaluation_context, NeedsClarification, QualityFailed, SubmissionUncertain
from agent.media import MediaProduction, digest, probe, command
from agent.quality import QualityProduction, extract_constraints
from agent.evidence import EvidenceProduction
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

class ProjectService(MediaProduction, QualityProduction, EvidenceProduction):
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

    def ensure_not_generating(self, project_id: str) -> None:
        task = self._pipeline_tasks.get(project_id)
        if task and not task.done() and task is not asyncio.current_task():
            raise ValueError("制作流程正在生成，请等待完成后再修改")

    def get_auteur_context(self, project_id: str) -> Optional[AuteurContext]:
        artifact = self.db.get_latest_artifact(project_id, "auteur_profile")
        return AuteurContext(**artifact["content"]) if artifact else None

    @exclusive
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
        self.ensure_not_generating(project_id)
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
            self.db.update_project_status(project_id, "director_review")
        return context

    @exclusive
    def clear_auteur_profile(self, project_id: str) -> None:
        self.ensure_not_generating(project_id)
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")
        self.db.invalidate_artifacts(project_id, [
            "auteur_profile", "treatments", "selected_treatment", "production_pack", "project_bible",
            "screenplay", "shot_list", "continuity_report", "grammar_report",
            "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        if project["status"] not in ("collecting", "brief_review"):
            self.db.update_project_status(project_id, "director_review")

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
        brief = CreativeBrief(**sanitize_brief_dict(self.enforce_brief(project_id, final_brief)))
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
        merged = self.enforce_brief(project_id, {**current, **sanitize_brief_dict(extraction.known)})
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
    @exclusive
    async def analyze_input(self, project_id: str, new_user_text: Optional[str] = None) -> QuestionsResponse:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        source_text = project["source_text"]
        if new_user_text:
            source_text = self.db.append_project_source(project_id, new_user_text)
            self.db.add_message(project_id, "user", new_user_text)

        existing_constraints = self.db.get_latest_artifact(project_id, "hard_constraints")
        constraints = self.constraints(project_id) if existing_constraints and not new_user_text else extract_constraints(source_text)
        self.db.save_artifact(project_id, "hard_constraints", constraints)
        if constraints["conflicts"]:
            raise NeedsClarification("；".join(constraints["conflicts"]))
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
    @exclusive
    async def answer_questions(self, project_id: str, answers: list[dict[str, str]], use_defaults: bool = False) -> QuestionsResponse:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        if project["status"] != "collecting":
            raise ValueError("当前不在剧情补充阶段，请返回简报修改")
        current = self.get_questions(project_id)
        if not answers:
            return self._finish_brief_collection(project_id, project.get("brief", {}), project.get("round_count", 0))
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
        return self._next_questions(project_id, merged_brief, extraction, round_num, force_review=use_defaults)

    # 10.1 Brief review & confirm
    @exclusive
    def update_brief(self, project_id: str, updates: dict[str, Any]) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        self.ensure_not_generating(project_id)
        current = dict(project.get("brief", {}))
        current.update(updates)
        enforced = self.enforce_brief(project_id, current)
        if any(k in updates and updates[k] != enforced.get(k) for k in self.constraints(project_id)["values"]):
            raise NeedsClarification("修改与原始明确要求冲突，请先更新硬约束")
        brief = CreativeBrief(**sanitize_brief_dict(enforced))
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="draft")
        self.db.invalidate_artifacts(project_id, [
            "treatments", "selected_treatment", "production_pack",
            "project_bible", "screenplay", "shot_list", "continuity_report",
            "grammar_report", "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.update_project_status(project_id, "brief_review")
        return brief

    @exclusive
    async def confirm_brief(self, project_id: str, confirmed_brief: Optional[dict[str, Any]] = None, *, generate: bool = True) -> CreativeBrief:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        data = {**project.get("brief", {}), **(confirmed_brief or {})}
        if confirmed_brief and any(k in data and data[k] != v for k, v in self.constraints(project_id)["values"].items() if k != "character_count"):
            raise NeedsClarification("确认内容与用户明确要求冲突，请先澄清硬约束")
        brief = CreativeBrief(**sanitize_brief_dict(self.enforce_brief(project_id, data)))
        self.db.update_project_brief(project_id, brief.model_dump(), title=brief.title)
        self.db.invalidate_artifacts(project_id, [
            "treatments", "selected_treatment", "production_pack", "project_bible",
            "screenplay", "shot_list", "continuity_report", "grammar_report",
            "auteur_report", "prompt_package", "workflow_plan", "production_report", "rough_cut",
        ])
        self.db.save_artifact(project_id, "creative_brief", brief.model_dump(), status="confirmed")
        self.db.update_project_status(project_id, "director_review")
        if generate:
            await self.generate_screenplay(project_id)
        return brief

    @exclusive
    async def generate_treatments(self, project_id: str) -> TreatmentPackage:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        self.ensure_not_generating(project_id)
        if project["status"] in ("collecting", "brief_review"):
            raise ValueError("请先确认剧情简报")
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

    @exclusive
    async def confirm_treatment(
        self,
        project_id: str,
        treatment_id: str,
        production_pack_id: Optional[str] = None,
        *, generate: bool = True,
    ) -> TreatmentOption:
        self.ensure_not_generating(project_id)
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
        if generate:
            await self.generate_screenplay(project_id)
        return selected

    # 10.2 Screenplay & Shots
    @exclusive
    async def generate_screenplay(self, project_id: str, *, generate: bool = True) -> ScreenplayPackage:
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

        self.db.update_project_status(project_id, "screenplay_ready")
        # Automatically generate shot list
        if generate:
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

    @exclusive
    async def generate_shots(self, project_id: str, *, allow_invalid: bool = False) -> list[ShotSpec]:
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
        if len({shot.shot_id for shot in shots}) != len(shots):
            raise ValueError("镜头编号重复，请重新生成分镜")

        if not shots:
            raise ValueError("LLM returned an empty shot list")

        # Reject invalid plans instead of silently stretching one shot past its limit.
        total_dur = sum(s.duration_seconds for s in shots)
        target_dur = brief.duration_seconds
        tolerance = target_dur * 0.05
        if not allow_invalid and abs(total_dur - target_dur) > tolerance:
            raise ValueError(
                f"分镜总时长 {total_dur:.1f} 秒与目标 {target_dur} 秒不符（允许误差 ±{tolerance:.1f} 秒），请重新生成分镜"
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

    @exclusive
    def update_shot(self, project_id: str, shot_id: str, shot_updates: dict[str, Any]) -> ShotSpec:
        self.ensure_not_generating(project_id)
        if set(shot_updates) & {"shot_id", "scene_id", "order"}:
            raise ValueError("镜头编号、场景归属与顺序不可通过局部编辑修改")
        shots_data = self.get_shots(project_id)
        if not shots_data:
            raise ValueError(f"No shots found for project {project_id}")

        if "shot_id" in shot_updates and shot_updates["shot_id"] != shot_id:
            raise ValueError("镜头 ID 不可修改")
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

    def validate_shots(self, project_id: str) -> None:
        """Recheck current inputs at every production entry point."""
        project = self.db.get_project(project_id)
        screenplay = self.get_screenplay(project_id)
        shots = [ShotSpec(**shot) for shot in self.get_shots(project_id)]
        if not project or not screenplay or not shots:
            raise ValueError("Project, screenplay and shots are required")
        ids = [shot.shot_id for shot in shots]
        if len(ids) != len(set(ids)):
            raise ValueError("Shot IDs must be unique")
        scene_ids = {scene["scene_id"] for scene in screenplay["scenes"]}
        if len(scene_ids) != len(screenplay["scenes"]) or len({s.order for s in shots}) != len(shots):
            raise ValueError("场景 ID 和镜头顺序必须唯一")
        bible_data = screenplay["project_bible"]
        char_ids = {c["character_id"] for c in bible_data["characters"]}
        location_ids = {c["location_id"] for c in bible_data["locations"]}
        if len(char_ids) != len(bible_data["characters"]) or len(location_ids) != len(bible_data["locations"]):
            raise ValueError("人物和地点 ID 必须唯一")
        for scene in screenplay["scenes"]:
            if scene["location_id"] not in location_ids or set(scene["characters"]) - char_ids or any(d["character_id"] not in char_ids for d in scene["dialogue"]):
                raise ValueError("场景引用了未知人物或地点")
        if any(shot.scene_id not in scene_ids for shot in shots):
            raise ValueError("Shot references an unknown scene")
        brief = CreativeBrief(**sanitize_brief_dict(project["brief"]))
        if abs(sum(shot.duration_seconds for shot in shots) - brief.duration_seconds) > brief.duration_seconds * 0.05:
            raise ValueError("Shot duration total exceeds the 5% tolerance")
        pack_art = self.db.get_latest_artifact(project_id, "production_pack")
        pack = FilmProductionPack(**pack_art["content"]) if pack_art else None
        auteur = self.get_auteur_context(project_id)
        if evaluation_context.get() == "baseline":
            pack = None
            auteur = None
        reports = {
            "continuity_report": self.continuity.check_deterministic(shots, ProjectBible(**screenplay["project_bible"])),
            "grammar_report": self.production_packs.validate_shots(shots, pack) if pack else [],
            "auteur_report": self.auteur_profiles.validate_shots(shots, auteur) if auteur else [],
        }
        errors = []
        for kind, issues in reports.items():
            self.db.save_artifact(project_id, kind, [issue.model_dump() for issue in issues])
            errors.extend(issue.model_dump() for issue in issues if issue.severity == "error")
        if errors:
            raise ValueError("Shot quality gate failed: " + json.dumps(errors, ensure_ascii=False))

    def validate_shots_for_export(self, project_id: str) -> None:
        self.validate_shots(project_id)

    @exclusive
    async def confirm_shots(self, project_id: str) -> list[dict[str, Any]]:
        shots_data = self.get_shots(project_id)
        if not shots_data:
            raise ValueError(f"No shots found for project {project_id}")
        self.validate_shots(project_id)

        self.db.save_artifact(project_id, "shot_list", shots_data, status="confirmed")
        self.db.update_project_status(project_id, "package_ready")

        # Automatically compile prompt packages and match workflows
        await self.compile_packages(project_id)
        return shots_data

    # 10.3 Prompt & Workflow packages
    @exclusive
    async def compile_packages(self, project_id: str) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        self.ensure_not_generating(project_id)
        screenplay_data = self.get_screenplay(project_id)
        if not screenplay_data:
            raise ValueError("Screenplay required to compile packages")

        bible = ProjectBible(**screenplay_data["project_bible"])
        shots = [ShotSpec(**s) for s in self.get_shots(project_id)]
        if not shots:
            raise ValueError("Shot list required to compile packages")

        self.validate_shots(project_id)

        prompt_packages: list[dict[str, Any]] = []
        workflow_plans: list[dict[str, Any]] = []

        project_dir = settings.data_dir / project_id
        patched_dir = project_dir / "patched_workflows"
        patched_dir.mkdir(parents=True, exist_ok=True)

        # Portable export does not depend on the server GPU or ComfyUI installation.
        pack_art = self.db.get_latest_artifact(project_id, "production_pack")
        preferred_workflow_id = pack_art["content"]["generation_recipe"]["workflow_id"] if pack_art else None

        for shot in shots:
            if not shot.reference_asset_ids and shot.generation_mode == "image_to_video":
                defaults = [a["id"] for a in self.assets(project_id) if a.get("project_default") and a["purpose"] == "reference"]
                shot = shot.model_copy(update={"reference_asset_ids": defaults})
            # 1. Select workflow
            plan = self.workflows.select_workflow(
                shot,
                aspect_ratio=bible.aspect_ratio,
                check_environment=False,
                preferred_workflow_id=preferred_workflow_id,
            )

            if plan.workflow_id:
                plan.template_sha256 = self.workflow_digest(plan.workflow_id)
            # 2. Compile prompt
            wf_profile = self.workflows.get_profile(plan.workflow_id).model_dump() if plan.workflow_id else None
            rules = self.workflows.get_prompt_rules(plan.workflow_id) if plan.workflow_id else {}

            prompt_pkg = self.compiler.compile(
                shot=shot,
                project_bible=bible,
                workflow_profile=wf_profile,
                prompt_rules=rules,
                quality="standard",
                fixed_seed=int(hashlib.sha256(f"{project_id}:{shot.shot_id}".encode()).hexdigest()[:8], 16),
            )

            # 3. Patch workflow JSON if matched
            if plan.status == "matched" and plan.workflow_id:
                out_path = patched_dir / f"{shot.shot_id}_{uuid.uuid4().hex[:10]}_workflow.json"
                _, err = self.workflows.patch_workflow(
                    workflow_id=plan.workflow_id,
                    prompt_pkg=prompt_pkg,
                    first_frame_asset_path=f"{shot.shot_id}_first_frame.png" if shot.generation_mode == "image_to_video" else None,
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

        self.db.update_project_status(project_id, "package_ready")
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
            f"# 🎬 《{bible.title}》 幕间 制作与执行报告",
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
        lines.append("- 在导出工作流页面下载完整制作包。根据素材需求准备首帧，将界面工作流拖入自己的 ComfyUI。")
        lines.append("- 在线渲染与粗剪是可选功能；工作流编译完成不代表模型、素材或渲染结果已经验证。")

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

    @exclusive
    def reconcile_render(self, project_id: str, run_id: str, task_id: str | None, not_submitted: bool, evidence: str):
        run = self.db.get_render_run(run_id)
        if not run or run["project_id"] != project_id or run["status"] != "running":
            raise ValueError("没有对应的未决任务")
        if not evidence.strip() or bool(task_id) == not_submitted:
            raise ValueError("需要核实依据，并选择远端任务 ID 或确认未提交之一")
        if task_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", task_id):
            raise ValueError("远端任务 ID 格式无效")
        self.db.save_artifact(project_id, "human_intervention", {"operation": "reconcile", "run_id": run_id, "evidence": evidence})
        self.db.update_render_run(run_id, "failed" if not_submitted else "running", prompt_id=task_id,
                                  error_json={"code": "VERIFIED_NOT_SUBMITTED" if not_submitted else "REMOTE_ID_VERIFIED", "message": evidence})
        return self.db.get_render_run(run_id)

    # Render outputs are immutable per run; fingerprints fence cache reuse.
    def workflow_digest(self, workflow_id: str) -> str:
        data = {"template": self.workflows.get_raw_workflow(workflow_id), "patch_map": self.workflows.get_patch_map(workflow_id)}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def render_fingerprint(self, project_id, prompt, plan):
        if plan.get("template_sha256") != self.workflow_digest(plan["workflow_id"]):
            raise ValueError("工作流模板已更新或为旧版本，请重新编译生成包")
        refs = {rid: digest(self.asset_file(project_id, rid)) for rid in prompt.get("reference_asset_ids", [])}
        workflow = json.loads(self._project_file(project_id, plan["patched_workflow_path"]).read_text())
        payload = {"prompt": prompt, "workflow": workflow, "template": self.workflows.get_raw_workflow(plan["workflow_id"]),
                   "patch_map": self.workflows.get_patch_map(plan["workflow_id"]), "backend": settings.render_backend,
                   "endpoint": self.comfyui.base_url if settings.render_backend == "comfyui" else "modelscope:Wan-AI/Wan2.1-T2V-1.3B",
                   "simulation": self.comfyui.mock_mode if settings.render_backend == "comfyui" else False, "references": refs}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @exclusive
    async def render_shot(self, project_id: str, shot_id: str, *, force: bool = False) -> RenderRun:
        self.validate_shots(project_id)
        packages = self.get_packages(project_id)
        plan = next((p for p in packages["workflow_plans"] if p["shot_id"] == shot_id), None)
        prompt = next((p for p in packages["prompt_packages"] if p["shot_id"] == shot_id), None)
        if not plan or plan["status"] != "matched" or not prompt or not plan.get("patched_workflow_path"):
            raise ValueError(f"Shot {shot_id} has no matched workflow: {(plan or {}).get('reason') or '请重新编译生成包'}")
        fingerprint = self.render_fingerprint(project_id, prompt, plan)
        request = {**prompt, "fingerprint": fingerprint}
        previous = [r for r in self.db.list_render_runs(project_id) if r["shot_id"] == shot_id]
        for old in previous:
            # Never submit around unresolved older work, even when inputs changed.
            if old["status"] == "running":
                if old["request_json"].get("fingerprint") != fingerprint:
                    raise SubmissionUncertain("此前远端任务尚未核实，不能用新输入重复提交")
                if not old.get("prompt_id"):
                    raise SubmissionUncertain("提交结果不明确，需要核实远端任务后再继续")
                run = old
                break
        else:
            run = None
        if not force and run is None:
            old = next((r for r in previous if r["status"] == "success" and r["request_json"].get("fingerprint") == fingerprint), None)
            if old:
                try:
                    path = self._project_file(project_id, old["output_json"]["file_path"])
                    if path.is_file() and digest(path) == old["output_json"]["sha256"]:
                        await probe(path)
                        self.db.save_artifact(project_id, "render_reuse", {"shot_id": shot_id, "run_id": old["id"], "fingerprint": fingerprint})
                        return RenderRun(**old)
                except (ValueError, OSError):
                    pass
        workflow = json.loads(self._project_file(project_id, plan["patched_workflow_path"]).read_text())
        refs = prompt.get("reference_asset_ids", [])
        profile = self.workflows.get_profile(plan["workflow_id"])
        if settings.render_backend == "modelscope" and (refs or profile.generation_mode != "text_to_video"):
            raise ValueError("当前云端适配器仅支持文生视频，不支持参考图")
        if settings.render_backend == "comfyui" and profile.generation_mode == "image_to_video":
            if not refs:
                raise ValueError("图生视频缺少真实首帧，请上传并绑定参考图")
            if len(refs) != 1:
                raise ValueError("当前图生视频模板支持一张首帧，请显式选择一张参考图")
            path = self.asset_file(project_id, refs[0])
            asset = next(a for a in self.assets(project_id) if a["id"] == refs[0])
            if asset["purpose"] != "reference":
                raise ValueError("首帧必须是图片素材")
            name = await self.comfyui.upload_image(path)
            patch = self.workflows.get_patch_map(plan["workflow_id"])["first_frame"]
            workflow[str(patch["node"])]["inputs"][patch["input"]] = name
        if settings.render_backend not in ("comfyui", "modelscope"):
            raise ValueError("未知渲染后端")
        if settings.render_backend == "modelscope" and not self.modelscope.available:
            raise ValueError("MODELSCOPE_API_KEY 未配置")
        self.db.invalidate_artifacts(project_id, ["rough_cut", "comparison_frames"])
        for attempt in range(3):
            if run is None:
                rid = "run_" + uuid.uuid4().hex[:12]
                self.db.create_render_run({"id": rid, "project_id": project_id, "shot_id": shot_id,
                                          "workflow_id": plan["workflow_id"], "status": "running", "request_json": request})
                run = self.db.get_render_run(rid)
            rid = run["id"]
            error = None
            try:
                if not run.get("prompt_id"):
                    if settings.render_backend == "comfyui":
                        task_id, err = await self.comfyui.submit_prompt(workflow, max_retries=0)
                    else:
                        task_id, err = await self.modelscope.submit_video(prompt["positive_prompt"], prompt["negative_prompt"])
                    if err or not task_id:
                        error = err.model_dump() if err else {"code": "SUBMISSION_UNCERTAIN", "message": "任务 ID 缺失", "retryable": False}
                    else:
                        self.db.update_render_run(rid, "running", prompt_id=task_id)
                        run["prompt_id"] = task_id
                if not error:
                    out = settings.data_dir / project_id / "outputs"
                    out.mkdir(parents=True, exist_ok=True)
                    dest = out / f"{shot_id}_{rid}.mp4"
                    if settings.render_backend == "comfyui":
                        history, err = await self.comfyui.wait_for_completion(run["prompt_id"])
                        if err:
                            error = err.model_dump()
                        else:
                            asset = self.comfyui.first_video_output(history or {})
                            if not asset:
                                error = {"code": "OUTPUT_MISSING", "message": "任务没有视频输出", "retryable": False}
                            elif self.comfyui.mock_mode:
                                await command("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                              f"color=c=0x223344:size={prompt['width']}x{prompt['height']}:rate={prompt['fps']}:duration={prompt['frame_count']/prompt['fps']}",
                                              "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest))
                            elif not await self.comfyui.download_output_asset(asset["filename"], asset["subfolder"], asset["type"], dest):
                                error = {"code": "DOWNLOAD_FAILED", "message": "视频下载失败", "retryable": True}
                    else:
                        url, err = await self.modelscope.poll_video(run["prompt_id"])
                        if err:
                            error = err.model_dump()
                        elif not url or not await self.modelscope.download_asset(url, dest):
                            error = {"code": "DOWNLOAD_FAILED", "message": "视频下载失败", "retryable": True}
                    if not error:
                        info = await probe(dest)
                        shot = next(s for s in self.get_shots(project_id) if s["shot_id"] == shot_id)
                        if info["duration"] + 2 / prompt["fps"] < shot["duration_seconds"]:
                            raise ValueError("生成视频短于镜头要求，不能重复画面补时长")
                        self.db.update_render_run(rid, "success", output_json={"file_path": str(dest), "sha256": digest(dest), "media": info,
                                                                            "backend": settings.render_backend, "attempt": attempt + 1})
                        return RenderRun(**self.db.get_render_run(rid))
            except (ValueError, OSError) as exc:
                error = {"code": "MEDIA_INVALID", "message": str(exc)[:1000], "retryable": False}
            except Exception as exc:
                from agent.execution import LeaseLost
                if isinstance(exc, LeaseLost):
                    raise
                error = {"code": "SUBMISSION_UNCERTAIN", "message": str(exc)[:1000], "retryable": False}
            pending = error["code"] in ("COMFYUI_TIMEOUT", "MS_TIMEOUT", "DOWNLOAD_FAILED", "SUBMISSION_UNCERTAIN")
            self.db.update_render_run(rid, "running" if pending else "failed", error_json=error)
            self.db.save_artifact(project_id, "render_attempt", {"shot_id": shot_id, "run_id": rid, "attempt": attempt + 1, "error": error})
            if not error.get("retryable") or attempt == 2:
                return RenderRun(**self.db.get_render_run(rid))
            await asyncio.sleep(2 ** (attempt + 1))
            if not pending:
                run = None
        raise RuntimeError("Render attempts exhausted")

    @exclusive
    async def render_all_shots(self, project_id: str) -> list[RenderRun]:
        self.validate_shots(project_id)
        self.db.update_project_status(project_id, "rendering")
        try:
            runs = [await self.render_shot(project_id, shot["shot_id"]) for shot in self.get_shots(project_id)]
            if any(r.status != "success" for r in runs):
                self.db.update_project_status(project_id, "failed")
            return runs
        except Exception:
            self.db.update_project_status(project_id, "failed")
            raise

    @staticmethod
    def _project_file(project_id: str, path: str) -> Path:
        if not re.fullmatch(r"prj_[0-9a-f]{8}", project_id):
            raise ValueError("Invalid project ID")
        project_root = (settings.data_dir / project_id).resolve()
        raw_path = Path(path)
        candidate = (raw_path if raw_path.is_absolute() else project_root / raw_path).resolve()
        if not candidate.is_relative_to(project_root):
            raise ValueError("Workflow path is outside the project directory")
        return candidate

    # Generation Pipeline: run every remaining production step in order,
    # yielding per-step progress for the frontend "generation chain" UI.
    PIPELINE_STEPS = ["treatments", "treatment_choice", "screenplay", "shots", "quality", "packages", "render", "rough_cut"]

    @exclusive
    async def run_auto_pipeline(self, project_id: str, *, evaluation_mode: str = "full", render: bool = True) -> dict[str, Any]:
        if not self.db.get_project(project_id):
            raise ValueError(f"Project {project_id} not found")
        if evaluation_mode not in ("baseline", "rules", "full"):
            raise ValueError("Invalid evaluation mode")
        state = {"steps": [], "status": "running", "error": None, "task_id": lease_context.get()[2], "mode": evaluation_mode, "render": render}
        meter = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "usage_available": False}
        meter_token = metrics_context.set(meter)
        evaluation_token = evaluation_context.set(evaluation_mode)
        self._pipeline_progress[project_id] = state
        started = time.monotonic()
        self.db.save_artifact(project_id, "pipeline_progress", state, status="running")
        try:
            result = await self._run_auto_pipeline_steps(project_id, evaluation_mode=evaluation_mode, render=render)
            state["status"] = "completed"
            self.db.update_project_status(project_id, "completed" if render else "package_ready")
            return result
        except (Exception, asyncio.CancelledError) as exc:
            state["status"] = "needs_clarification" if isinstance(exc, NeedsClarification) else "quality_failed" if isinstance(exc, QualityFailed) else "failed"
            state["error"] = str(exc)[:500] or type(exc).__name__
            self.db.update_project_status(project_id, "failed")
            raise
        finally:
            state["elapsed_seconds"] = round(time.monotonic() - started, 3)
            state["metrics"] = meter
            metrics_context.reset(meter_token)
            evaluation_context.reset(evaluation_token)
            self.db.save_artifact(project_id, "pipeline_progress", state, status=state["status"])

    async def _run_auto_pipeline_steps(self, project_id: str, *, evaluation_mode: str = "full", render: bool = True) -> dict[str, Any]:
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
            self.db.save_artifact(project_id, "pipeline_progress", state, status="running")

        async def run_step(step: str, fn, detail_fn=None):
            role = {"analysis": "producer", "treatments": "producer", "treatment_choice": "producer", "screenplay": "writer", "shots": "director", "quality": "critic"}.get(step, "executor")
            before = self.db.artifact_versions(project_id)
            started = time.monotonic()
            record(step, "running", detail=role)
            try:
                outcome = fn()
                # Lambdas wrapping async methods return coroutines; await them.
                result = await outcome if asyncio.iscoroutine(outcome) else outcome
                record(step, "done", detail_fn(result) if detail_fn else None)
                self.handoff(project_id, role, step, before, started, status="done")
                return result
            except Exception as e:
                self.handoff(project_id, role, step, before, started, status="failed", error=str(e)[:500])
                record(step, "failed", error=str(e)[:500])
                self._pipeline_progress[project_id]["status"] = "failed"
                self._pipeline_progress[project_id]["error"] = str(e)[:500]
                raise

        if not render and not self.db.get_latest_artifact(project_id, "selected_treatment"):
            raise ValueError("请先选择并确认导演方案")
        if not project.get("brief"):
            await run_step("analysis", lambda: self.analyze_input(project_id))
        project = self.db.get_project(project_id)
        if project["status"] == "collecting":
            self._finish_brief_collection(project_id, project["brief"], project["round_count"])

        if self.db.get_project(project_id)["status"] == "brief_review":
            await self.confirm_brief(project_id, generate=False)

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
                lambda: self.confirm_treatment(project_id, package.recommendation, generate=False),
                lambda opt: opt.name,
            )
        else:
            record("treatments", "done", detail="已有导演方案，跳过")
            record("treatment_choice", "done", detail="方案已确认，跳过")

        # 3. Screenplay (confirm_brief / confirm_treatment already trigger it;
        #    run explicitly when the artifact is missing)
        if not self.db.get_latest_artifact(project_id, "screenplay"):
            await run_step("screenplay", lambda: self.generate_screenplay(project_id, generate=False))
        else:
            record("screenplay", "done", detail="已有剧本，跳过")

        # 4. Shots
        shots = self.get_shots(project_id)
        if not shots:
            shots = await run_step("shots", lambda: self.generate_shots(project_id, allow_invalid=True))
        else:
            record("shots", "done", detail=f"已有 {len(shots)} 个镜头，跳过")

        if evaluation_mode != "baseline":
            await run_step("quality", lambda: self.review_and_repair(project_id, repair=evaluation_mode == "full", content_review=evaluation_mode == "full"))
        else:
            record("quality", "done", detail="消融基线：不启用内容质检；安全与输入验证仍执行")

        # 5. Prompt packages & workflow patching
        packages = self.get_packages(project_id)
        if not packages.get("prompt_packages") or any(p.get("template_sha256") != self.workflow_digest(p["workflow_id"]) for p in packages.get("workflow_plans", []) if p.get("workflow_id")):
            await run_step(
                "packages", lambda: self.confirm_shots(project_id),
                lambda p: f"{len(p)} 个镜头包",
            )
        else:
            record("packages", "done", detail="已编译，跳过")

        if not render:
            return {"project_id": project_id, "steps": log, "status": "completed"}

        # 6. Render every shot sequentially
        async def render_checked():
            runs = await self.render_all_shots(project_id)
            failed = [run.shot_id for run in runs if run.status != "success"]
            if failed:
                raise RuntimeError("镜头渲染失败: " + ", ".join(failed))
            return runs

        runs = await run_step(
            "render", render_checked,
            lambda rs: f"{sum(1 for r in rs if r.status == 'success')}/{len(rs)} 成功",
        )
        # 7. Rough cut
        await run_step("rough_cut", lambda: self.create_rough_cut(project_id))

        return {"project_id": project_id, "steps": log, "status": "completed"}

    # Background pipeline execution + orchestration-view state.
    _pipeline_progress: dict[str, dict[str, Any]] = {}
    _pipeline_tasks: dict[str, asyncio.Task] = {}

    def start_auto_pipeline(self, project_id: str, *, render: bool = False) -> dict[str, Any]:
        """Start the auto pipeline as a background task (idempotent)."""
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        if not render and not self.db.get_latest_artifact(project_id, "selected_treatment"):
            raise ValueError("请先选择并确认导演方案")

        existing = self._pipeline_tasks.get(project_id)
        if (existing and not existing.done()) or self.db.lease_active(project_id):
            return {"project_id": project_id, "status": "running", "message": "生成集已在进行中"}

        self._pipeline_progress[project_id] = {"steps": [], "status": "running", "error": None}

        async def runner() -> None:
            try:
                await self.run_auto_pipeline(project_id, render=render)
            except Exception as exc:
                if self._pipeline_progress[project_id]["status"] == "running":
                    self._pipeline_progress[project_id].update(status="failed", error=str(exc)[:500])

        self._pipeline_tasks[project_id] = asyncio.create_task(runner())
        return {"project_id": project_id, "status": "running"}

    def get_pipeline_status(self, project_id: str) -> dict[str, Any]:
        """Orchestration view state: step log + per-shot render status."""
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        saved = self.db.get_latest_artifact(project_id, "pipeline_progress")
        progress = dict(saved["content"] if saved else self._pipeline_progress.get(
            project_id, {"steps": [], "status": "idle", "error": None}
        ))
        if project_id not in self._pipeline_progress and progress["status"] == "running" and not self.db.lease_active(project_id):
            progress.update(status="interrupted", error="进程已中断，可重新启动流水线")

        # Latest run per shot (list_render_runs is newest-first)
        latest_by_shot: dict[str, dict[str, Any]] = {}
        for run in self.db.list_render_runs(project_id):
            latest_by_shot.setdefault(run["shot_id"], run)
        shots = [
            {
                "shot_id": shot_id,
                "run_id": run["id"],
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
            "quality": bool(self.db.get_latest_artifact(project_id, "quality_review")),
        }
        if progress["status"] == "completed" and not artifacts["rough_cut" if progress.get("render", True) else "packages"]:
            progress.update(status="idle", error="输入或时间线已更新，请恢复生成或重新合成")
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
            "handoffs": self.db.list_artifacts(project_id, "handoff"),
            "revisions": self.db.list_artifacts(project_id, "revision"),
            "reused": self.db.list_artifacts(project_id, "render_reuse"),
            "attempts": self.db.list_artifacts(project_id, "render_attempt"),
            "pending_runs": [{"run_id": r["id"], "shot_id": r["shot_id"], "task_id": r.get("prompt_id"), "error": (r.get("error_json") or {}).get("message")} for r in self.db.list_render_runs(project_id) if r["status"] == "running"],
            "legacy_render_notice": any("fingerprint" not in r["request_json"] for r in self.db.list_render_runs(project_id)),
        }

project_service = ProjectService()
