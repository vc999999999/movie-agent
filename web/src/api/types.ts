// Minimal TS interfaces mirroring agent/models.py field names.
// Regenerate full types with: npm run gen:types (requires backend on :8000).

export type ProjectStatus =
  | "collecting"
  | "brief_review"
  | "treatment_review"
  | "screenplay_ready"
  | "shots_review"
  | "package_ready"
  | "rendering"
  | "completed"
  | "failed";

export interface CreativeBrief {
  title: string | null;
  logline: string;
  purpose: "short_film" | "trailer" | "ad" | "music_video" | "social_video";
  audience: string | null;
  platform: "douyin" | "bilibili" | "youtube" | "other";
  duration_seconds: number;
  aspect_ratio: "16:9" | "9:16" | "1:1" | "2.39:1";
  genre: string[];
  tone: string[];
  visual_style: string;
  story_summary: string;
  protagonist: string;
  protagonist_goal: string;
  conflict: string;
  ending: string | null;
  dialogue_mode: "none" | "voiceover" | "dialogue" | "mixed";
  language: string;
  content_constraints: string[];
  user_must_keep: string[];
  agent_assumptions: string[];
}

export interface Project {
  id: string;
  title: string;
  status: ProjectStatus;
  brief: CreativeBrief | null;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface Message {
  role: string;
  content: string;
  created_at?: string;
  [key: string]: unknown;
}

export interface QuestionItem {
  question_id: string;
  field: string;
  text: string;
  choices: string[];
  affects: string[];
  impact: number;
  blocking: boolean;
}

export interface QuestionsResponse {
  project_id: string;
  status: ProjectStatus;
  round: number;
  brief_completion: number;
  questions: QuestionItem[];
  assumptions: string[];
  can_confirm: boolean;
}

export interface AuteurTechnique {
  technique_id: string;
  name: string;
  domain: "narrative" | "camera" | "editing" | "sound";
  instruction: string;
  viewer_effect: string;
  generation_note: string;
}

export interface AuteurVariant {
  variant_id: string;
  name: string;
  reference_works: string[];
  best_for: string[];
  techniques: AuteurTechnique[];
}

export interface AuteurProfile {
  profile_id: string;
  version: string;
  director_name: string;
  label: string;
  description: string;
  disclaimer: string;
  default_variant_id: string;
  variants: AuteurVariant[];
}

export type AuteurIntensity = "subtle" | "balanced" | "strong";

export interface AuteurSelection {
  profile_id: string;
  variant_id: string;
  intensity: AuteurIntensity;
  preserve: string[];
}

export interface AuteurContext {
  profile: AuteurProfile;
  selection: AuteurSelection;
}

export interface TreatmentOption {
  treatment_id: string;
  name: string;
  core_question: string;
  logline: string;
  structure: string;
  visual_strategy: string;
  production_pack_id: string;
  production_risk: "low" | "medium" | "high";
  estimated_shots: number;
  technique_plan: string[];
  viewer_effect: string;
}

export interface TreatmentPackage {
  options: TreatmentOption[];
  recommendation: string;
  recommendation_reason: string;
}

export interface CharacterBible {
  character_id: string;
  name: string;
  narrative_role: string;
  age_range: string | null;
  gender_presentation: string | null;
  fixed_appearance: string;
  fixed_costume: string;
  personality: string[];
  voice: string | null;
  reference_asset_ids: string[];
  forbidden_changes: string[];
}

export interface LocationBible {
  location_id: string;
  name: string;
  fixed_visual_description: string;
  layout_notes: string;
  time_of_day: string;
  weather: string | null;
  lighting_baseline: string;
  reference_asset_ids: string[];
  forbidden_changes: string[];
}

export interface ProjectBible {
  title: string;
  logline: string;
  genre: string[];
  visual_style: string;
  aspect_ratio: string;
  target_duration: number;
  characters: CharacterBible[];
  locations: LocationBible[];
  global_negative_prompt: string;
  color_palette: string[];
  soundtrack_style: string;
}

export interface DialogueLine {
  character_id: string;
  text: string;
  emotion: string | null;
}

export interface SceneSpec {
  scene_id: string;
  order: number;
  heading: string;
  location_id: string;
  time_of_day: string;
  estimated_duration: number;
  purpose: string;
  characters: string[];
  setup: string;
  action_beats: string[];
  dialogue: DialogueLine[];
  transition_in: string;
  transition_out: string;
  continuity_in: string[];
  continuity_out: string[];
}

export interface ScreenplayPackage {
  project_bible: ProjectBible;
  scenes: SceneSpec[];
}

export type ShotSize = "ECU" | "CU" | "MCU" | "MS" | "MLS" | "WS" | "EWS";

export interface ShotSpec {
  shot_id: string;
  scene_id: string;
  order: number;
  beat_id: string | null;
  grammar_pack_id: string | null;
  sequence_pattern: string | null;
  shot_function: string | null;
  information_revealed: string | null;
  information_withheld: string | null;
  screen_direction: "left_to_right" | "right_to_left" | "neutral" | null;
  axis_id: string | null;
  auteur_profile_id: string | null;
  auteur_variant_id: string | null;
  technique_ids: string[];
  technique_rationale: string | null;
  duration_seconds: number;
  narrative_purpose: string;
  subject_ids: string[];
  location_id: string;
  start_frame: string;
  action: string;
  end_frame: string;
  shot_size: ShotSize;
  camera_angle: string;
  camera_movement: string;
  composition: string;
  lens: string | null;
  fps: number;
  lighting: string;
  mood: string;
  dialogue: string | null;
  voiceover: string | null;
  sound_effects: string[];
  music_cue: string | null;
  continuity_requirements: string[];
  reference_asset_ids: string[];
  generation_mode: "text_to_image" | "image_to_video" | "text_to_video";
  first_frame_required: boolean;
  last_frame_required: boolean;
}

export interface GrammarIssue {
  severity: "warning" | "error";
  code: string;
  shot_ids: string[];
  message: string;
  suggested_fix: string;
}

export interface ContinuityIssue {
  severity: "warning" | "error";
  shot_ids: string[];
  field: string;
  explanation: string;
  suggested_fix: string;
}

export interface ShotsResponse {
  shots: ShotSpec[];
  continuity_issues: ContinuityIssue[];
  grammar_issues: GrammarIssue[];
  auteur_issues: GrammarIssue[];
  total_duration: number;
}

export interface ShotPrompt {
  shot_id: string;
  prompt_language: "en" | "zh";
  positive_prompt: string;
  negative_prompt: string;
  reference_asset_ids: string[];
  seed: number;
  steps: number | null;
  cfg: number | null;
  width: number;
  height: number;
  frame_count: number;
  fps: number;
  workflow_id: string | null;
}

export interface WorkflowPlan {
  shot_id: string;
  workflow_id: string | null;
  status: "matched" | "unsupported" | "precheck_failed";
  reason: string | null;
  required_capabilities: string[];
  patched_workflow_path: string | null;
}

export interface PackagesResponse {
  prompt_packages: ShotPrompt[];
  workflow_plans: WorkflowPlan[];
  production_report?: string;
  [key: string]: unknown;
}

export interface RenderRun {
  id: string;
  project_id: string;
  shot_id: string;
  workflow_id: string;
  status: "pending" | "running" | "success" | "failed";
  request_json: Record<string, unknown>;
  prompt_id: string | null;
  output_json: Record<string, unknown> | null;
  error_json: Record<string, unknown> | null;
  created_at: string;
  finished_at: string | null;
}

export interface CreateProjectResponse {
  project: Project;
  questions_response: QuestionsResponse;
}

export interface ProjectDetailResponse {
  project: Project;
  messages: Message[];
}

