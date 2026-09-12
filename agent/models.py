from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

# 4.1 Project Status
ProjectStatus = Literal[
    "collecting",          # 正在理解输入/反问
    "brief_review",        # 等待用户确认创作简报
    "director_review",     # 简报已确认，等待导演模板
    "treatment_review",    # 等待用户选择导演方案
    "screenplay_ready",    # 剧本拆解完成
    "shots_review",        # 等待用户确认镜头表
    "package_ready",       # Prompt 和工作流参数包完成
    "rendering",           # 可选：正在执行 ComfyUI
    "completed",
    "failed",
]

class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# LLM 输出字段的白名单清洗：枚举字段不合法值回退默认，多余字段丢弃。
# 让 brief 合并对真实 LLM 的脏输出（幻觉字段、错误枚举值）保持健壮。
_BRIEF_ENUM_FALLBACKS: dict[str, tuple[tuple[str, ...], Any]] = {
    "purpose": (("short_film", "trailer", "ad", "music_video", "social_video"), "trailer"),
    "platform": (("douyin", "bilibili", "youtube", "other"), "other"),
    "aspect_ratio": (("16:9", "9:16", "1:1", "2.39:1"), "16:9"),
    "dialogue_mode": (("none", "voiceover", "dialogue", "mixed"), "voiceover"),
}

_BRIEF_ALLOWED_FIELDS: frozenset[str] = frozenset([
    "title", "logline", "purpose", "audience", "platform", "duration_seconds",
    "aspect_ratio", "genre", "tone", "visual_style", "story_summary",
    "protagonist", "protagonist_goal", "conflict", "ending", "dialogue_mode",
    "language", "content_constraints", "user_must_keep", "agent_assumptions",
])


def _map_free_text_to_enum(text: str, allowed: tuple[str, ...], key: str) -> Optional[str]:
    hints: dict[str, dict[str, tuple[str, ...]]] = {
        "dialogue_mode": {
            "none": ("无对白", "纯视觉", "不要对白", "no dialogue"),
            "voiceover": ("旁白", "视觉叙事", "环境音", "画外音", "voiceover"),
            "dialogue": ("对白", "角色对白", "对话", "dialogue"),
            "mixed": ("混合", "both", "mixed"),
        },
        "aspect_ratio": {
            "9:16": ("竖屏", "9:16"),
            "16:9": ("横屏", "16:9"),
            "1:1": ("方形", "1:1"),
            "2.39:1": ("宽银幕", "2.39"),
        },
        "platform": {
            "douyin": ("抖音", "douyin"),
            "bilibili": ("b站", "bilibili"),
            "youtube": ("youtube",),
            "other": ("其他", "other"),
        },
        "purpose": {
            "trailer": ("预告", "trailer"),
            "short_film": ("短片", "short"),
            "ad": ("广告", "ad"),
            "music_video": ("mv", "music"),
            "social_video": ("社交", "social"),
        },
    }
    table = hints.get(key, {})
    for candidate in allowed:
        for hint in table.get(candidate, ()):
            if hint in text:
                return candidate
    return None


def sanitize_brief_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize an LLM-written brief dict to fields CreativeBrief accepts."""
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key not in _BRIEF_ALLOWED_FIELDS or value is None:
            continue
        if key in _BRIEF_ENUM_FALLBACKS:
            allowed, fallback = _BRIEF_ENUM_FALLBACKS[key]
            if value not in allowed:
                mapped = _map_free_text_to_enum(str(value), allowed, key)
                value = mapped if mapped else fallback
        if key == "duration_seconds":
            try:
                value = max(10, min(90, int(value)))
            except (TypeError, ValueError):
                continue
        cleaned[key] = value
    return cleaned


# 5.1 CreativeBrief
class CreativeBrief(StrictBaseModel):
    title: Optional[str] = None
    logline: str
    purpose: Literal["short_film", "trailer", "ad", "music_video", "social_video"] = "trailer"
    audience: Optional[str] = None
    platform: Literal["douyin", "bilibili", "youtube", "other"] = "other"
    duration_seconds: int = Field(default=45, ge=10, le=90)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "2.39:1"] = "16:9"
    genre: list[str] = Field(default_factory=list)
    tone: list[str] = Field(default_factory=list)
    visual_style: str = "写实电影感"
    story_summary: str = ""
    protagonist: str = ""
    protagonist_goal: str = ""
    conflict: str = ""
    ending: Optional[str] = None
    dialogue_mode: Literal["none", "voiceover", "dialogue", "mixed"] = "voiceover"
    language: str = "zh-CN"
    content_constraints: list[str] = Field(default_factory=list)
    user_must_keep: list[str] = Field(default_factory=list)
    agent_assumptions: list[str] = Field(default_factory=list)

# 5.2 CharacterBible
class CharacterBible(StrictBaseModel):
    character_id: str
    name: str
    narrative_role: str
    age_range: Optional[str] = None
    gender_presentation: Optional[str] = None
    fixed_appearance: str
    fixed_costume: str
    personality: list[str] = Field(default_factory=list)
    voice: Optional[str] = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)

# 5.3 LocationBible
class LocationBible(StrictBaseModel):
    location_id: str
    name: str
    fixed_visual_description: str
    layout_notes: str = ""
    time_of_day: str = "夜晚"
    weather: Optional[str] = None
    lighting_baseline: str = "低照度冷光"
    reference_asset_ids: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)

# Dialogue line
class DialogueLine(StrictBaseModel):
    character_id: str
    text: str
    emotion: Optional[str] = None

# Project Bible
class ProjectBible(StrictBaseModel):
    title: str
    logline: str
    genre: list[str]
    visual_style: str
    aspect_ratio: str
    target_duration: int
    characters: list[CharacterBible]
    locations: list[LocationBible]
    global_negative_prompt: str = ""
    color_palette: list[str] = Field(default_factory=list)
    soundtrack_style: str = ""

# 5.4 SceneSpec
class SceneSpec(StrictBaseModel):
    scene_id: str
    order: int
    heading: str
    location_id: str
    time_of_day: str = "未指定"
    estimated_duration: float
    purpose: str
    characters: list[str]
    setup: str
    action_beats: list[str]
    dialogue: list[DialogueLine] = Field(default_factory=list)
    transition_in: str = "CUT"
    transition_out: str = "CUT"
    continuity_in: list[str] = Field(default_factory=list)
    continuity_out: list[str] = Field(default_factory=list)

# 5.5 ShotSpec
class ShotSpec(StrictBaseModel):
    shot_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    scene_id: str
    order: int
    beat_id: Optional[str] = None
    grammar_pack_id: Optional[str] = None
    sequence_pattern: Optional[str] = None
    shot_function: Optional[str] = None
    information_revealed: Optional[str] = None
    information_withheld: Optional[str] = None
    screen_direction: Optional[Literal["left_to_right", "right_to_left", "neutral"]] = None
    axis_id: Optional[str] = None
    auteur_profile_id: Optional[str] = None
    auteur_variant_id: Optional[str] = None
    technique_ids: list[str] = Field(default_factory=list)
    technique_rationale: Optional[str] = None
    duration_seconds: float = Field(ge=1.0, le=12.0)
    narrative_purpose: str
    subject_ids: list[str]
    location_id: str
    start_frame: str
    action: str
    end_frame: str
    shot_size: Literal["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]
    camera_angle: str
    camera_movement: str
    composition: str
    lens: Optional[str] = None
    fps: int = 24
    lighting: str
    mood: str
    dialogue: Optional[str] = None
    voiceover: Optional[str] = None
    sound_effects: list[str] = Field(default_factory=list)
    music_cue: Optional[str] = None
    continuity_requirements: list[str] = Field(default_factory=list)
    reference_asset_ids: list[str] = Field(default_factory=list)
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"] = "image_to_video"
    first_frame_required: bool = False
    last_frame_required: bool = False

# 5.6 PromptPackage / ShotPrompt
class ShotPrompt(StrictBaseModel):
    shot_id: str
    prompt_language: Literal["en", "zh"] = "en"
    positive_prompt: str
    negative_prompt: str
    reference_asset_ids: list[str] = Field(default_factory=list)
    seed: int
    steps: Optional[int] = None
    cfg: Optional[float] = None
    width: int
    height: int
    frame_count: int
    fps: int = 24
    workflow_id: Optional[str] = None

# 5.7 WorkflowProfile
class WorkflowProfile(StrictBaseModel):
    workflow_id: str
    version: str
    name: str
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"]
    supported_aspect_ratios: list[str]
    min_vram_gb: int
    max_frames: int
    frame_step: int = 1
    frame_offset: int = 0
    required_models: list[str]
    required_nodes: list[str]
    accepted_references: list[Literal["character", "style", "first_frame", "last_frame"]]

class NarrativeBeat(StrictBaseModel):
    role: str
    ratio: float = Field(gt=0, le=1)
    purpose: str

class NarrativePattern(StrictBaseModel):
    pattern_id: str
    duration_range: tuple[int, int]
    beats: list[NarrativeBeat]

class DirectingGrammar(StrictBaseModel):
    grammar_id: str
    intent: str
    preferred_sizes: list[Literal["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]]
    preferred_movements: list[str]
    max_same_size_run: int = Field(default=2, ge=1, le=5)
    sequence_patterns: dict[str, list[str]]
    forbidden_patterns: list[str] = Field(default_factory=list)

class GenerationRecipe(StrictBaseModel):
    workflow_id: str
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"]
    max_duration_seconds: float = Field(gt=0, le=12)
    unsupported: list[str] = Field(default_factory=list)

class FilmProductionPack(StrictBaseModel):
    pack_id: str
    version: str
    name: str
    genres: list[str]
    keywords: list[str]
    narrative_pattern: NarrativePattern
    directing_grammar: DirectingGrammar
    generation_recipe: GenerationRecipe

class AuteurTechnique(StrictBaseModel):
    technique_id: str
    name: str
    domain: Literal["narrative", "camera", "editing", "sound"]
    instruction: str
    viewer_effect: str
    generation_note: str

class AuteurVariant(StrictBaseModel):
    variant_id: str
    name: str
    reference_works: list[str]
    best_for: list[str]
    techniques: list[AuteurTechnique]

class AuteurProfile(StrictBaseModel):
    profile_id: str
    version: str
    director_name: str
    label: str
    description: str
    disclaimer: str
    default_variant_id: str
    variants: list[AuteurVariant]

class AuteurSelection(StrictBaseModel):
    profile_id: str
    variant_id: str
    intensity: Literal["subtle", "balanced", "strong"] = "balanced"
    preserve: list[str] = Field(default_factory=list)

class AuteurContext(StrictBaseModel):
    profile: AuteurProfile
    selection: AuteurSelection

class TreatmentOption(StrictBaseModel):
    treatment_id: str
    name: str
    core_question: str
    logline: str
    structure: str
    visual_strategy: str
    production_pack_id: str
    production_risk: Literal["low", "medium", "high"]
    estimated_shots: int = Field(ge=3, le=30)
    technique_plan: list[str] = Field(default_factory=list)
    viewer_effect: str = ""

class TreatmentPackage(StrictBaseModel):
    options: list[TreatmentOption] = Field(min_length=2, max_length=3)
    recommendation: str
    recommendation_reason: str

class GrammarIssue(StrictBaseModel):
    severity: Literal["warning", "error"]
    code: str
    shot_ids: list[str]
    message: str
    suggested_fix: str

# 14.2 ContinuityIssue
class ContinuityIssue(StrictBaseModel):
    severity: Literal["warning", "error"]
    shot_ids: list[str]
    field: str
    explanation: str
    suggested_fix: str

# 6. Extraction & Questions
def _coerce_conflicts(value: Any) -> list[str]:
    """LLM 常把 conflicts 写成 [{field, message, severity}, ...]，压平为字符串列表。"""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            text = "；".join(
                str(v) for k, v in item.items() if k != "severity" and v
            )
            if text:
                out.append(text)
    return out


class BriefExtraction(StrictBaseModel):
    known: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)

    @field_validator("conflicts", mode="before")
    @classmethod
    def _flatten_conflicts(cls, v: Any) -> Any:
        if isinstance(v, list) and any(isinstance(i, dict) for i in v):
            return _coerce_conflicts(v)
        return v

class QuestionItem(StrictBaseModel):
    question_id: str
    field: str
    text: str
    choices: list[str]
    affects: list[str]
    impact: int
    blocking: bool

class QuestionsResponse(StrictBaseModel):
    project_id: str
    status: ProjectStatus
    round: int
    brief_completion: float
    questions: list[QuestionItem]
    assumptions: list[str]
    can_confirm: bool

# Screenplay Package
class ScreenplayPackage(StrictBaseModel):
    project_bible: ProjectBible
    scenes: list[SceneSpec]

# Workflow Plan
class WorkflowPlan(StrictBaseModel):
    shot_id: str
    workflow_id: Optional[str]
    status: Literal["matched", "unsupported", "precheck_failed"]
    reason: Optional[str] = None
    required_capabilities: list[str] = Field(default_factory=list)
    patched_workflow_path: Optional[str] = None

# Render Run
class RenderRun(StrictBaseModel):
    id: str
    project_id: str
    shot_id: str
    workflow_id: str
    status: Literal["pending", "running", "success", "failed"]
    request_json: dict[str, Any]
    prompt_id: Optional[str] = None
    output_json: Optional[dict[str, Any]] = None
    error_json: Optional[dict[str, Any]] = None
    created_at: str
    finished_at: Optional[str] = None

# 16 Error Model
class ErrorDetail(StrictBaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    suggested_action: str = ""
