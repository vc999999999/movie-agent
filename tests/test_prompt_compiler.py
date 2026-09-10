from __future__ import annotations

import pytest
from app.models import CharacterBible, LocationBible, ProjectBible, ShotSpec
from app.prompt_compiler import (
    map_resolution,
    merge_negative_prompts,
    prompt_compiler,
)

def test_resolution_mapping():
    assert map_resolution("16:9", "standard") == (1280, 720)
    assert map_resolution("16:9", "high") == (1920, 1080)
    assert map_resolution("9:16", "standard") == (720, 1280)
    assert map_resolution("1:1", "standard") == (1024, 1024)
    assert map_resolution("2.39:1", "high") == (1920, 804)

def test_merge_negative_prompts_deduplication():
    wf_neg = ["blurry", "low quality", "deformed"]
    proj_neg = ["blurry", "anime", "cartoon"]
    shot_neg = ["low quality", "jump cut"]

    result = merge_negative_prompts(wf_neg, proj_neg, shot_neg)
    parts = [p.strip() for p in result.split(",")]
    assert len(parts) == len(set(parts))
    assert "blurry" in parts
    assert "low quality" in parts
    assert "anime" in parts
    assert "jump cut" in parts

def test_prompt_layering_and_verbatim_character_lock():
    char = CharacterBible(
        character_id="char_01",
        name="Anna",
        narrative_role="Protagonist",
        fixed_appearance="silver ponytail hair, cybernetic glowing eye",
        fixed_costume="black leather trench coat, combat boots",
        personality=["determined"],
    )
    loc = LocationBible(
        location_id="loc_01",
        name="Rainy Alley",
        fixed_visual_description="neon reflection on wet asphalt",
        time_of_day="midnight",
        lighting_baseline="low key blue lighting",
    )
    bible = ProjectBible(
        title="Cyber Chase",
        logline="A chase in rain",
        genre=["Cyberpunk"],
        visual_style="Cinematic noir, high contrast",
        aspect_ratio="16:9",
        target_duration=45,
        characters=[char],
        locations=[loc],
    )
    shot = ShotSpec(
        shot_id="s01_sh01",
        scene_id="s01",
        order=1,
        duration_seconds=4.0,
        narrative_purpose="intro",
        subject_ids=["char_01"],
        location_id="loc_01",
        start_frame="Standing in rain",
        action="Walks forward cautiously",
        end_frame="Stops under neon sign",
        shot_size="MS",
        camera_angle="eye level",
        camera_movement="slow tracking push",
        composition="rule of thirds",
        lighting="neon blue and pink",
        mood="tense",
        generation_mode="image_to_video",
    )

    prompt_pkg = prompt_compiler.compile(shot, bible, fixed_seed=42)

    # 18.3: Character fixed appearance appears verbatim in positive prompt
    assert "silver ponytail hair, cybernetic glowing eye" in prompt_pkg.positive_prompt
    assert "black leather trench coat, combat boots" in prompt_pkg.positive_prompt
    assert "neon reflection on wet asphalt" in prompt_pkg.positive_prompt

    # Verify frame count and resolution
    assert prompt_pkg.frame_count == int(round(4.0 * 24))
    assert (prompt_pkg.width, prompt_pkg.height) == (1280, 720)
    assert prompt_pkg.seed == 42
