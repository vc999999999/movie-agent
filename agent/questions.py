from __future__ import annotations

from typing import Any, Optional
from agent.models import CreativeBrief, QuestionItem

QUESTION_BANK: dict[str, dict[str, Any]] = {
    "duration_seconds": {
        "text": "你希望成片多长？这会决定场景数量和镜头节奏。",
        "choices": ["30 秒", "45 秒", "60 秒", "90 秒"],
        "impact": 5,
        "blocking": True,
        "affects": ["scene_budget", "shot_pace"],
    },
    "ending": {
        "text": "结尾要完整收束，还是停在悬念上？",
        "choices": ["完整结局", "反转", "开放式", "预告片式悬念"],
        "impact": 5,
        "blocking": False,
        "affects": ["story_structure", "last_shot"],
    },
    "dialogue_mode": {
        "text": "声音以哪种方式讲故事？这会影响口型和镜头设计。",
        "choices": ["无对白", "旁白", "角色对白", "混合"],
        "impact": 4,
        "blocking": False,
        "affects": ["audio_pipeline", "shot_specs"],
    },
    "aspect_ratio": {
        "text": "成片画幅比例希望采用哪种？这会影响画面构图和平台适配。",
        "choices": ["16:9 横屏 (电影/B站)", "9:16 竖屏 (抖音/Shorts)", "2.39:1 宽银幕电影感", "1:1 正方形"],
        "impact": 4,
        "blocking": True,
        "affects": ["resolution", "framing"],
    },
    "visual_style": {
        "text": "你期望什么样的视觉风格与光影基调？",
        "choices": ["写实电影感 (胶片质感、真实光影)", "赛博朋克霓虹 (高对比、冷暖反差)", "悬疑暗黑胶片 (低饱和、强阴影)", "科幻史诗未来感"],
        "impact": 4,
        "blocking": False,
        "affects": ["workflow_models", "prompt_styling"],
    },
    "platform": {
        "text": "该短片主要发布在哪个平台？",
        "choices": ["通用网络短片", "抖音 (竖屏优先)", "B 站 (横屏电影感)", "YouTube (横屏16:9)"],
        "impact": 3,
        "blocking": False,
        "affects": ["aspect_ratio", "pacing"],
    },
    "conflict": {
        "text": "故事的核心冲突或危机是什么？",
        "choices": ["雨夜追捕高危目标", "潜入封锁区域寻找机密", "生死倒计时撤离", "面临背叛与绝境对抗"],
        "impact": 5,
        "blocking": True,
        "affects": ["narrative_core", "scene_actions"],
    },
    "protagonist_goal": {
        "text": "主角在短片中最迫切达成的目标是什么？",
        "choices": ["找出真凶 / 侦破悬案", "成功撤离并保护关键证物", "揭开巨大阴谋的冰山一角", "解救受困同伴"],
        "impact": 4,
        "blocking": False,
        "affects": ["protagonist_beats", "shot_intentions"],
    },
}

# Safe defaults to fill when rounds finish or user defaults
SAFE_DEFAULTS: dict[str, Any] = {
    "duration_seconds": 45,
    "purpose": "trailer",
    "platform": "other",
    "aspect_ratio": "16:9",
    "visual_style": "写实电影感，雨夜冷色调，35mm胶片质感",
    "genre": ["悬疑", "犯罪", "赛博朋克"],
    "tone": ["紧张", "冷峻", "神秘"],
    "dialogue_mode": "voiceover",
    "language": "zh-CN",
    "ending": "预告片式悬念",
    "protagonist": "侦探",
    "protagonist_goal": "在暴风雨之夜追踪神秘凶手",
    "conflict": "目标在阴暗街巷中不断设伏与潜逃",
}

def calculate_priority(field: str, confidence: float, is_missing: bool, is_conflict: bool) -> float:
    meta = QUESTION_BANK.get(field, {"impact": 3, "blocking": False})
    impact = meta["impact"]
    uncertainty = 1.0 if is_missing else (1.0 - confidence)
    blocking = 2.0 if meta["blocking"] else 1.0
    score = impact * uncertainty * blocking
    if is_conflict:
        score += 100.0  # Conflicts always take top priority
    return score

def select_questions(
    known: dict[str, Any],
    conflicts: list[str],
    confidence: dict[str, float],
    asked_fields: set[str],
    max_questions: int = 3
) -> list[QuestionItem]:
    candidates: list[tuple[float, str, bool]] = []

    # Check conflicts first
    for field in conflicts:
        if field in QUESTION_BANK:
            score = calculate_priority(field, confidence.get(field, 0.5), is_missing=False, is_conflict=True)
            candidates.append((score, field, True))

    # Check missing fields
    for field, meta in QUESTION_BANK.items():
        if field in asked_fields:
            continue
        val = known.get(field)
        is_missing = val is None or val == "" or val == []
        conf = confidence.get(field, 0.0) if not is_missing else 0.0

        if is_missing or conf < 0.7:
            score = calculate_priority(field, conf, is_missing, is_conflict=False)
            candidates.append((score, field, False))

    # Sort descending by priority score
    candidates.sort(key=lambda x: x[0], reverse=True)

    selected: list[QuestionItem] = []
    selected_fields: set[str] = set()

    for _, field, _ in candidates:
        if field in selected_fields:
            continue
        meta = QUESTION_BANK[field]
        selected.append(QuestionItem(
            question_id=f"q_{field}",
            field=field,
            text=meta["text"],
            choices=meta["choices"],
            affects=meta["affects"],
            impact=meta["impact"],
            blocking=meta["blocking"],
        ))
        selected_fields.add(field)
        if len(selected) >= max_questions:
            break

    return selected

def apply_safe_defaults(known: dict[str, Any], assumptions: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Fill safe defaults for missing fields when rounds conclude, appending to assumptions."""
    updated = dict(known)
    assumptions_out = list(assumptions)

    if not updated.get("duration_seconds"):
        updated["duration_seconds"] = 45
        assumptions_out.append("未明确成片时长，默认按标准短片 45 秒规划")
    if not updated.get("aspect_ratio"):
        # If platform is douyin, default 9:16 else 16:9
        if updated.get("platform") == "douyin":
            updated["aspect_ratio"] = "9:16"
            assumptions_out.append("根据抖音平台，画幅自动设为 9:16 竖屏")
        else:
            updated["aspect_ratio"] = "16:9"
            assumptions_out.append("未明确画幅比例，默认采用 16:9 横屏")
    if not updated.get("dialogue_mode"):
        updated["dialogue_mode"] = "voiceover"
        assumptions_out.append("未指定声音形式，默认采用旁白主导 (voiceover)，保障生成画面的口型稳定性")
    if not updated.get("visual_style"):
        updated["visual_style"] = SAFE_DEFAULTS["visual_style"]
        assumptions_out.append("视觉风格默认采用写实电影感 (胶片质感、电影光影)")
    if not updated.get("ending"):
        updated["ending"] = "预告片式悬念"
        assumptions_out.append("故事结尾默认采用预告片式悬念收尾")
    if not updated.get("protagonist"):
        updated["protagonist"] = "核心主角"
        assumptions_out.append("主角设定自动从故事核心角色提炼")
    if not updated.get("protagonist_goal"):
        updated["protagonist_goal"] = "查明真相并直面危机"
        assumptions_out.append("主角目标自动补全为查明真相并直面危机")
    if not updated.get("conflict"):
        updated["conflict"] = "主角与危险阻碍的正面交锋"
        assumptions_out.append("核心冲突自动补全为主客双方的激烈对抗")

    return updated, assumptions_out

def calculate_brief_completion(brief_dict: dict[str, Any]) -> float:
    """Calculate brief completion percentage (0.0 to 1.0)."""
    core_fields = [
        "logline", "duration_seconds", "aspect_ratio", "visual_style",
        "protagonist", "protagonist_goal", "conflict", "ending", "dialogue_mode"
    ]
    present = sum(1 for f in core_fields if brief_dict.get(f))
    return round(present / len(core_fields), 2)
