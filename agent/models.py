from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

# 4.1 Project Status
ProjectStatus = Literal[
    "collecting",          # 正在理解输入/反问
    "brief_review",        # 等待用户确认创作简报
    "screenplay_ready",    # 剧本拆解完成
    "shots_review",        # 等待用户确认镜头表
    "package_ready",       # Prompt 和工作流参数包完成
    "rendering",           # 可选：正在执行 ComfyUI
    "completed",
    "failed",
]

class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    time_of_day: str
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
    shot_id: str
    scene_id: str
    order: int
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
    image_prompt: Optional[str] = None
    video_prompt: str
    reference_asset_ids: list[str] = Field(default_factory=list)
    seed: int
    steps: Optional[int] = None
    cfg: Optional[float] = None
    width: int
    height: int
    frame_count: int
    fps: int = 24
    workflow_id: Optional[str] = None
    unsupported_requirements: list[str] = Field(default_factory=list)

# 5.7 WorkflowProfile
class WorkflowProfile(StrictBaseModel):
    workflow_id: str
    version: str
    name: str
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"]
    supported_aspect_ratios: list[str]
    min_vram_gb: int
    max_frames: int
    required_models: list[str]
    required_nodes: list[str]
    accepted_references: list[Literal["character", "style", "first_frame", "last_frame"]]
    patch_map_path: str
    workflow_path: str

# 14.2 ContinuityIssue
class ContinuityIssue(StrictBaseModel):
    severity: Literal["warning", "error"]
    shot_ids: list[str]
    field: str
    explanation: str
    suggested_fix: str

# 6. Extraction & Questions
class BriefExtraction(StrictBaseModel):
    known: dict[str, Any] = Field(default_factory=dict)
    unknown: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)

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
