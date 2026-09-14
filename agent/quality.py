"""Evidence-based constraints and bounded writer/director/critic handoffs."""
from __future__ import annotations

import json
import re
import time
from typing import Literal
from pydantic import Field

from agent.execution import exclusive, NeedsClarification, QualityFailed, metrics_context
from agent.models import StrictBaseModel, ShotSpec, SceneSpec, ProjectBible, CreativeBrief, sanitize_brief_dict
from server.config import settings


class ReviewIssue(StrictBaseModel):
    severity: Literal["error", "warning"]
    role: Literal["writer", "director"]
    scene_ids: list[str] = Field(default_factory=list)
    shot_ids: list[str] = Field(default_factory=list)
    evidence: str = Field(min_length=1)
    instruction: str = Field(min_length=1)


class Review(StrictBaseModel):
    issues: list[ReviewIssue] = Field(default_factory=list)


class Revision(StrictBaseModel):
    shots: list[ShotSpec] = Field(default_factory=list)
    scenes: list[SceneSpec] = Field(default_factory=list)
    project_bible: ProjectBible | None = None


def extract_constraints(text: str) -> dict:
    evidence = []
    def add(field, value, quote):
        evidence.append({"field": field, "value": value, "quote": quote})
    def number_value(token):
        digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if "百" in token:
            left, right = token.split("百", 1)
            return number_value(left or "一") * 100 + (number_value(right) if right else 0)
        if "十" in token:
            left, right = token.split("十", 1)
            return number_value(left or "一") * 10 + (number_value(right) if right else 0)
        if all(c in digits for c in token):
            return int("".join(str(digits[c]) for c in token))
        return float(token)
    for match in re.finditer(r"(\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+)\s*(秒|分钟|seconds?|minutes?)", text, re.I):
        number = number_value(match[1]) * (60 if match[2].lower() in ("分钟", "minute", "minutes") else 1)
        add("duration_seconds", number, match[0])
    for value, pattern in (("9:16", r"竖屏|9[:：]16"), ("16:9", r"横屏|16[:：]9"), ("1:1", r"方形|1[:：]1"), ("2.39:1", r"2\.39[:：]1|宽银幕")):
        for match in re.finditer(pattern, text):
            add("aspect_ratio", value, match[0])
    numbers = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for match in re.finditer(r"([一两二三四五六七八九十]|\d+)\s*(?:名|个|位)?\s*(?:角色|人物|主角|宇航员|演员|人)", text):
        add("character_count", numbers[match[1]] if match[1] in numbers else int(match[1]), match[0])
    no_dialogue = list(re.finditer(r"无对白|不要对白|没有对白|纯视觉|no dialogue", text, re.I))
    for match in no_dialogue:
        add("dialogue_mode", "none", match[0])
    clean = re.sub(r"无对白|不要对白|没有对白|纯视觉|no dialogue", "", text, flags=re.I)
    for value, pattern in (("dialogue", r"有对白|角色对白|有对话"), ("voiceover", r"仅旁白|只有旁白"), ("mixed", r"对白和旁白|旁白和对白")):
        for match in re.finditer(pattern, clean):
            add("dialogue_mode", value, match[0])
    values, conflicts = {}, []
    for item in evidence:
        field, value = item["field"], item["value"]
        if field in values and values[field] != value:
            conflicts.append(f"{field} 存在相互矛盾的明确要求")
        values[field] = value
    duration = values.get("duration_seconds", 45)
    if not 10 <= duration <= 90 or int(duration) != duration:
        conflicts.append("当前支持 10–90 秒的整数时长，请明确调整目标")
    return {"values": values, "evidence": evidence, "conflicts": list(dict.fromkeys(conflicts))}


class QualityProduction:
    def constraints(self, project_id: str) -> dict:
        art = self.db.get_latest_artifact(project_id, "hard_constraints")
        return art["content"] if art else extract_constraints(self.db.get_project(project_id)["source_text"])

    def enforce_brief(self, project_id: str, brief: dict) -> dict:
        constraints = self.constraints(project_id)
        if constraints["conflicts"]:
            raise NeedsClarification("；".join(constraints["conflicts"]))
        result = {**brief, **{k: v for k, v in constraints["values"].items() if k != "character_count"}}
        count = constraints["values"].get("character_count")
        if count is not None:
            result["user_must_keep"] = list(dict.fromkeys([*brief.get("user_must_keep", []), f"角色数量必须为 {count}"]))
        return result

    @exclusive
    def update_constraints(self, project_id: str, text: str) -> dict:
        constraints = extract_constraints(text)
        if constraints["conflicts"] or not constraints["values"]:
            raise NeedsClarification("；".join(constraints["conflicts"]) or "请提供明确时长、画幅、角色数量或对白要求")
        old = self.constraints(project_id)
        fields = set(constraints["values"])
        merged = {"values": {**old["values"], **constraints["values"]},
                  "evidence": [e for e in old["evidence"] if e["field"] not in fields] + constraints["evidence"], "conflicts": []}
        # Unresolved conflicts on other fields must survive a partial clarification.
        original = extract_constraints(self.db.get_project(project_id)["source_text"])
        for conflict in original["conflicts"]:
            key = "duration_seconds" if "10–90" in conflict else conflict.split(" ")[0]
            if key not in fields and key not in old.get("resolved_fields", []):
                merged["conflicts"].append(conflict)
        merged["resolved_fields"] = sorted(set(old.get("resolved_fields", [])) | fields)
        self.db.save_artifact(project_id, "hard_constraints", merged)
        self.db.add_message(project_id, "user", "明确要求澄清：" + text)
        brief = self.db.get_project(project_id)["brief"]
        self.db.update_project_brief(project_id, {**brief, **{k: v for k, v in merged["values"].items() if k != "character_count"}})
        self.db.invalidate_artifacts(project_id, ["selected_treatment", "treatments", "screenplay", "project_bible", "shot_list", "prompt_package", "workflow_plan", "rough_cut", "quality_review", "comparison_frames", "timeline"])
        self.db.update_project_status(project_id, "collecting")
        return merged

    def hard_constraint_errors(self, project_id: str) -> list[str]:
        constraints = self.constraints(project_id)
        errors = list(constraints["conflicts"])
        brief = self.db.get_project(project_id)["brief"]
        screenplay = self.get_screenplay(project_id)
        for field, value in constraints["values"].items():
            if field != "character_count" and brief.get(field) != value:
                errors.append(f"明确要求 {field}={value} 未满足")
        if screenplay:
            bible = screenplay["project_bible"]
            count = constraints["values"].get("character_count")
            if count is not None and len(bible["characters"]) != count:
                errors.append(f"要求 {count} 名角色，当前 {len(bible['characters'])} 名")
            if bible["aspect_ratio"] != brief["aspect_ratio"] or bible["target_duration"] != brief["duration_seconds"]:
                errors.append("ProjectBible 与简报时长或画幅不一致")
            mode = brief.get("dialogue_mode")
            shots = self.get_shots(project_id)
            target_duration = constraints["values"].get("duration_seconds")
            if shots and target_duration is not None and abs(sum(s["duration_seconds"] for s in shots) - target_duration) > 2/24:
                errors.append(f"镜头总时长不满足明确的 {target_duration} 秒要求")
            if mode == "none" and (any(s["dialogue"] for s in screenplay["scenes"]) or any(s.get("dialogue") or s.get("voiceover") for s in shots)):
                errors.append("无对白要求下仍有对白或旁白")
            if mode == "dialogue" and shots and not any(s.get("dialogue") for s in shots):
                errors.append("要求角色对白但镜头没有对白")
            if mode in ("voiceover", "mixed") and shots and not any(s.get("voiceover") for s in shots):
                errors.append("要求旁白但镜头没有旁白")
        return errors

    def handoff(self, project_id, role, task, before, started, **extra):
        self.db.save_artifact(project_id, "handoff", {"role": role, "task": task, "input_versions": before,
                              "output_versions": self.db.artifact_versions(project_id),
                              "elapsed_seconds": round(time.monotonic() - started, 3), **extra})

    @exclusive
    async def review_and_repair(self, project_id: str, *, repair: bool = True, content_review: bool = True) -> dict:
        if self.constraints(project_id)["conflicts"]:
            raise NeedsClarification("；".join(self.constraints(project_id)["conflicts"]))
        for round_number in range(3 if repair else 1):
            before = self.db.artifact_versions(project_id)
            started = time.monotonic()
            screenplay = self.get_screenplay(project_id)
            shots = self.get_shots(project_id)
            if not screenplay or not shots:
                raise ValueError("质检需要剧本与分镜")
            scene_ids = {s["scene_id"] for s in screenplay["scenes"]}
            shot_ids = {s["shot_id"] for s in shots}
            rules = []
            try:
                self.validate_shots(project_id)
            except ValueError as exc:
                # Prefer concrete issue locations from fresh deterministic reports.
                for kind in ("continuity_report", "grammar_report", "auteur_report"):
                    art = self.db.get_latest_artifact(project_id, kind)
                    for issue in art["content"] if art and art["version"] > before.get(kind, 0) else []:
                        if issue["severity"] == "error":
                            rules.append(ReviewIssue(severity="error", role="director", shot_ids=issue.get("shot_ids") or sorted(shot_ids),
                                                     evidence=issue.get("explanation") or str(issue), instruction=issue.get("suggested_fix") or "修正此规则错误"))
                if not rules:
                    rules.append(ReviewIssue(severity="error", role="director", shot_ids=sorted(shot_ids), evidence=str(exc), instruction="修正验证错误，保持所有明确要求"))
            hard_errors = self.hard_constraint_errors(project_id)
            if hard_errors:
                rules.append(ReviewIssue(severity="error", role="writer", scene_ids=sorted(scene_ids), evidence="；".join(hard_errors), instruction="恢复用户硬约束，修正相关人物设定与场景"))
            review = Review()
            if content_review:
                prompt = (settings.prompts_dir / "review_film.md").read_text()
                payload = {"brief": self.db.get_project(project_id)["brief"], "constraints": self.constraints(project_id), "screenplay": screenplay, "shots": shots}
                review = await self.llm.structured_call(prompt, json.dumps(payload, ensure_ascii=False), Review, fallback_fn=Review)
                for issue in review.issues:
                    if not (issue.shot_ids or issue.scene_ids) or set(issue.shot_ids) - shot_ids or set(issue.scene_ids) - scene_ids:
                        raise QualityFailed("质检反馈引用了不存在的场景或镜头")
            issues = [*rules, *review.issues]
            report = {"round": round_number, "issues": [i.model_dump() for i in issues], "passed": not any(i.severity == "error" for i in issues),
                      "simulation": settings.llm_mock_mode, "content_review": content_review}
            self.db.save_artifact(project_id, "quality_review", report)
            self.handoff(project_id, "critic", "review", before, started, feedback=report)
            if report["passed"]:
                return report
            if not repair or round_number == 2:
                raise QualityFailed("质检未通过，已停止生成；请查看具体问题与修订记录")
            for role in ("writer", "director"):
                targeted = [i for i in issues if i.severity == "error" and i.role == role]
                if not targeted:
                    continue
                screenplay = self.get_screenplay(project_id)
                shots = self.get_shots(project_id)
                allowed_scenes = {sid for i in targeted for sid in i.scene_ids}
                allowed_shots = {sid for i in targeted for sid in i.shot_ids}
                if role == "writer":
                    allowed_scenes |= {s["scene_id"] for s in shots if s["shot_id"] in allowed_shots}
                    allowed_shots |= {s["shot_id"] for s in shots if s["scene_id"] in allowed_scenes}
                elif not allowed_shots:
                    allowed_shots |= {s["shot_id"] for s in shots if s["scene_id"] in allowed_scenes}
                before = self.db.artifact_versions(project_id)
                started = time.monotonic()
                payload = {"role": role, "brief": self.db.get_project(project_id)["brief"], "constraints": self.constraints(project_id),
                           "project_bible": screenplay["project_bible"], "issues": [i.model_dump() for i in targeted],
                           "scenes": [s for s in screenplay["scenes"] if s["scene_id"] in allowed_scenes or s["scene_id"] in {x["scene_id"] for x in shots if x["shot_id"] in allowed_shots}],
                           "shots": [s for s in shots if s["shot_id"] in allowed_shots],
                           "allowed_shot_ids": sorted(allowed_shots), "allowed_scene_ids": sorted(allowed_scenes),
                           "schema": Revision.model_json_schema()}
                revision = await self.llm.structured_call((settings.prompts_dir / "repair_film.md").read_text(), json.dumps(payload, ensure_ascii=False), Revision)
                new_shots = {s.shot_id: s.model_dump() for s in revision.shots}
                new_scenes = {s.scene_id: s.model_dump() for s in revision.scenes}
                if len(new_shots) != len(revision.shots) or len(new_scenes) != len(revision.scenes):
                    raise QualityFailed("修订包含重复 ID")
                if set(new_shots) - allowed_shots or set(new_scenes) - allowed_scenes or (role == "director" and (new_scenes or revision.project_bible)):
                    raise QualityFailed("修订越过了授权的镜头或场景范围")
                for old in shots:
                    new = new_shots.get(old["shot_id"])
                    if new and (new["scene_id"] != old["scene_id"] or new["order"] != old["order"]):
                        raise QualityFailed("局部修订不能改变镜头所属场景或顺序")
                if revision.project_bible and allowed_scenes != scene_ids:
                    if revision.project_bible.model_dump() != screenplay["project_bible"]:
                        raise QualityFailed("局部场景修订不能修改共享人物场景设定")
                if not new_shots and not new_scenes and not revision.project_bible:
                    raise QualityFailed("修订没有返回任何修改")
                changes = {"role": role, "round": round_number + 1,
                           "before": {"shots": [s for s in shots if s["shot_id"] in new_shots], "scenes": [s for s in screenplay["scenes"] if s["scene_id"] in new_scenes],
                                      "project_bible": screenplay["project_bible"] if revision.project_bible else None}, "after": revision.model_dump()}
                if revision.project_bible:
                    self.db.save_artifact(project_id, "project_bible", revision.project_bible.model_dump())
                if new_scenes:
                    self.db.save_artifact(project_id, "screenplay", [new_scenes.get(s["scene_id"], s) for s in screenplay["scenes"]])
                if new_shots:
                    self.db.save_artifact(project_id, "shot_list", [new_shots.get(s["shot_id"], s) for s in shots])
                self.db.invalidate_artifacts(project_id, ["prompt_package", "workflow_plan", "production_report", "rough_cut", "comparison_frames"])
                self.db.save_artifact(project_id, "revision", changes)
                self.handoff(project_id, role, "repair", before, started, feedback=changes)
        raise QualityFailed("质检未通过")
