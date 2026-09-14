from __future__ import annotations

import random
from typing import Any, Optional
from agent.models import CharacterBible, LocationBible, ProjectBible, ShotPrompt, ShotSpec

# Aspect ratio resolution mapping
ASPECT_RATIO_RESOLUTIONS: dict[str, dict[str, tuple[int, int]]] = {
    "16:9": {
        "standard": (1280, 720),
        "high": (1920, 1080),
        "preview": (854, 480),
    },
    "9:16": {
        "standard": (720, 1280),
        "high": (1080, 1920),
        "preview": (480, 854),
    },
    "1:1": {
        "standard": (1024, 1024),
        "high": (1024, 1024),
        "preview": (512, 512),
    },
    "2.39:1": {
        "standard": (1280, 536),
        "high": (1920, 804),
        "preview": (854, 356),
    }
}

DEFAULT_NEGATIVE_PROMPTS = [
    "blurry", "low quality", "worst quality", "distorted limbs", "extra fingers",
    "flickering", "jpeg artifacts", "watermark", "signature", "bad anatomy", "overexposed", "underexposed"
]

def map_resolution(aspect_ratio: str, quality: str = "standard") -> tuple[int, int]:
    ratios = ASPECT_RATIO_RESOLUTIONS.get(aspect_ratio, ASPECT_RATIO_RESOLUTIONS["16:9"])
    return ratios.get(quality, ratios["standard"])

def merge_negative_prompts(workflow_negatives: list[str], project_negatives: list[str], shot_negatives: list[str]) -> str:
    """Merge and deduplicate negative prompts preserving order."""
    combined: list[str] = []
    seen: set[str] = set()

    for item in workflow_negatives + project_negatives + shot_negatives:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        for p in parts:
            p_lower = p.lower()
            if p_lower not in seen:
                seen.add(p_lower)
                combined.append(p)

    return ", ".join(combined)

class PromptCompiler:
    """8. Prompt Compiler - Deterministic layering and prompt assembly."""

    def compile(
        self,
        shot: ShotSpec,
        project_bible: ProjectBible,
        workflow_profile: Optional[dict[str, Any]] = None,
        prompt_rules: Optional[dict[str, Any]] = None,
        quality: str = "standard",
        fixed_seed: Optional[int] = None,
    ) -> ShotPrompt:
        rules = prompt_rules or {}
        lang = rules.get("prompt_language", "en")
        quality_triggers = rules.get("quality_triggers", "masterpiece, cinematic film grain, 8k uhd, photorealistic, 35mm photograph")

        # 1. Look up characters and locations
        char_map: dict[str, CharacterBible] = {c.character_id: c for c in project_bible.characters}
        loc_map: dict[str, LocationBible] = {l.location_id: l for l in project_bible.locations}

        # 2. Layer assembling strictly in order
        # [项目风格锁]
        style_layer = project_bible.visual_style.strip()

        # [角色固定描述]
        char_descs: list[str] = []
        for cid in shot.subject_ids:
            if cid in char_map:
                c = char_map[cid]
                char_str = f"{c.name} ({c.fixed_appearance}, wearing {c.fixed_costume})"
                char_descs.append(char_str)
        char_layer = "; ".join(char_descs)

        # [场景固定描述]
        loc = loc_map.get(shot.location_id)
        if loc:
            loc_layer = f"Location: {loc.name}, {loc.fixed_visual_description}, time: {loc.time_of_day}, lighting: {loc.lighting_baseline}"
            if loc.weather:
                loc_layer += f", weather: {loc.weather}"
        else:
            loc_layer = f"Location ID: {shot.location_id}"

        # [镜头起始状态]
        start_state_layer = f"Start frame: {shot.start_frame.strip()}"

        # [主体动作]
        action_layer = f"Action: {shot.action.strip()}"

        # [镜头景别、角度、运动与构图]
        cam_lens = f", lens: {shot.lens}" if shot.lens else ""
        camera_layer = f"Cinematography: shot size {shot.shot_size}, angle {shot.camera_angle}, movement {shot.camera_movement}, composition {shot.composition}{cam_lens}"

        # [灯光、色彩与情绪]
        lighting_mood_layer = f"Lighting: {shot.lighting}, mood: {shot.mood}"

        # Assemble positive prompt
        layers = [
            f"[Style]: {style_layer}",
            f"[Characters]: {char_layer}" if char_layer else "",
            f"[Environment]: {loc_layer}",
            f"[Setup]: {start_state_layer}",
            f"[Subject Action]: {action_layer}",
            f"[Camera]: {camera_layer}",
            f"[Lighting & Mood]: {lighting_mood_layer}",
            f"[Rendering]: {quality_triggers}",
        ]
        positive_prompt = ". ".join([layer for layer in layers if layer])

        # 3. Negative prompt merging
        wf_negatives = rules.get("default_negative_prompts", DEFAULT_NEGATIVE_PROMPTS)
        proj_negatives = [project_bible.global_negative_prompt] if project_bible.global_negative_prompt else []
        shot_negatives = ["motion blur artifact", "jump cuts", "deformed face"]
        negative_prompt = merge_negative_prompts(wf_negatives, proj_negatives, shot_negatives)

        # 4. Deterministic parameters
        w, h = map_resolution(project_bible.aspect_ratio, quality=quality)
        fps = shot.fps
        frame_count = max(16, int(round(shot.duration_seconds * fps)))

        if workflow_profile and workflow_profile.get("frame_step", 1) > 1:
            step = workflow_profile["frame_step"]
            offset = workflow_profile.get("frame_offset", 0)
            frame_count = max(offset + step, round((frame_count - offset) / step) * step + offset)

        # Workflow clamping
        if workflow_profile and "max_frames" in workflow_profile:
            max_f = workflow_profile["max_frames"]
            if frame_count > max_f:
                frame_count = max_f

        seed = fixed_seed if fixed_seed is not None else random.randint(10000000, 99999999)
        steps = rules.get("defaults", {}).get("steps", 28)
        cfg = rules.get("defaults", {}).get("cfg", 6.0)

        return ShotPrompt(
            shot_id=shot.shot_id,
            prompt_language=lang,
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            reference_asset_ids=shot.reference_asset_ids,
            seed=seed,
            steps=steps,
            cfg=cfg,
            width=w,
            height=h,
            frame_count=frame_count,
            fps=fps,
            workflow_id=workflow_profile.get("workflow_id") if workflow_profile else None,
        )

prompt_compiler = PromptCompiler()
