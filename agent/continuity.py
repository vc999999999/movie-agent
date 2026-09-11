from __future__ import annotations

from typing import Any, Optional
from agent.models import ContinuityIssue, ProjectBible, ShotSpec

class ContinuityChecker:
    """14. Continuity engine: deterministic checks + LLM continuity review."""

    def check_deterministic(
        self,
        shots: list[ShotSpec],
        project_bible: ProjectBible
    ) -> list[ContinuityIssue]:
        issues: list[ContinuityIssue] = []

        char_ids = {c.character_id for c in project_bible.characters}
        loc_ids = {l.location_id for l in project_bible.locations}

        for idx, shot in enumerate(shots):
            # 1. Verify IDs exist in ProjectBible
            for cid in shot.subject_ids:
                if cid not in char_ids:
                    issues.append(ContinuityIssue(
                        severity="error",
                        shot_ids=[shot.shot_id],
                        field="subject_ids",
                        explanation=f"镜头引用的角色 ID '{cid}' 在 ProjectBible 中不存在",
                        suggested_fix=f"请修正为已定义的角色 ID: {list(char_ids)}",
                    ))

            if shot.location_id not in loc_ids:
                issues.append(ContinuityIssue(
                    severity="error",
                    shot_ids=[shot.shot_id],
                    field="location_id",
                    explanation=f"镜头引用的场景 ID '{shot.location_id}' 在 ProjectBible 中不存在",
                    suggested_fix=f"请修正为已定义的场景 ID: {list(loc_ids)}",
                ))

            # 2. Check adjacent shot continuity
            if idx > 0:
                prev_shot = shots[idx - 1]

                # Check transition between consecutive shots in the same scene
                if prev_shot.scene_id == shot.scene_id:
                    # Check lighting continuity
                    if prev_shot.lighting and shot.lighting:
                        # If radically different lighting in same scene without explanation
                        prev_l = prev_shot.lighting.lower()
                        curr_l = shot.lighting.lower()
                        if ("夜" in prev_l and "日" in curr_l) or ("白天" in prev_l and "黑夜" in curr_l):
                            issues.append(ContinuityIssue(
                                severity="warning",
                                shot_ids=[prev_shot.shot_id, shot.shot_id],
                                field="lighting",
                                explanation=f"相邻镜头光照发生跳跃: 前镜头为 '{prev_shot.lighting}'，后镜头为 '{shot.lighting}'",
                                suggested_fix="确认是否处于同一时间段，或在转场中增加时间流逝说明",
                            ))

                    # Check frame continuity warning if start_frame doesn't match narrative of end_frame
                    if not shot.start_frame:
                        issues.append(ContinuityIssue(
                            severity="warning",
                            shot_ids=[shot.shot_id],
                            field="start_frame",
                            explanation="镜头缺少起始画面状态描述，不利于镜头衔接",
                            suggested_fix="填写清晰的 start_frame 状态，描述主体与环境起始构图",
                        ))

        return issues

continuity_checker = ContinuityChecker()
