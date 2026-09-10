from __future__ import annotations

import pytest
from app.continuity import continuity_checker
from app.models import CharacterBible, LocationBible, ProjectBible, ShotSpec

def test_continuity_id_verification():
    char = CharacterBible(
        character_id="char_detective",
        name="Detective",
        narrative_role="Hero",
        fixed_appearance="tall, coat",
        fixed_costume="trench coat",
    )
    loc = LocationBible(
        location_id="loc_rooftop",
        name="Rooftop",
        fixed_visual_description="rainy roof",
        time_of_day="night",
        lighting_baseline="moonlight",
    )
    bible = ProjectBible(
        title="Test",
        logline="Test",
        genre=["Noir"],
        visual_style="Dark",
        aspect_ratio="16:9",
        target_duration=45,
        characters=[char],
        locations=[loc],
    )

    shot_valid = ShotSpec(
        shot_id="s01_sh01", scene_id="s01", order=1, duration_seconds=4.0,
        narrative_purpose="intro", subject_ids=["char_detective"], location_id="loc_rooftop",
        start_frame="standing", action="looks", end_frame="stops",
        shot_size="MS", camera_angle="level", camera_movement="pan", composition="rule",
        lighting="night moonlight", mood="dark", generation_mode="image_to_video"
    )

    shot_invalid = ShotSpec(
        shot_id="s01_sh02", scene_id="s01", order=2, duration_seconds=4.0,
        narrative_purpose="action", subject_ids=["char_ghost_unknown"], location_id="loc_nonexistent",
        start_frame="standing", action="runs", end_frame="falls",
        shot_size="CU", camera_angle="level", camera_movement="push", composition="center",
        lighting="night moonlight", mood="dark", generation_mode="image_to_video"
    )

    issues = continuity_checker.check_deterministic([shot_valid, shot_invalid], bible)
    assert len(issues) >= 2
    fields = [i.field for i in issues]
    assert "subject_ids" in fields
    assert "location_id" in fields

def test_continuity_lighting_jump_warning():
    char = CharacterBible(character_id="c1", name="A", narrative_role="H", fixed_appearance="desc", fixed_costume="cos")
    loc = LocationBible(location_id="l1", name="B", fixed_visual_description="desc", time_of_day="night", lighting_baseline="base")
    bible = ProjectBible(title="T", logline="T", genre=["G"], visual_style="V", aspect_ratio="16:9", target_duration=30, characters=[char], locations=[loc])

    shot1 = ShotSpec(
        shot_id="s01_sh01", scene_id="s01", order=1, duration_seconds=5.0,
        narrative_purpose="p", subject_ids=["c1"], location_id="l1",
        start_frame="s", action="a", end_frame="e",
        shot_size="MS", camera_angle="a", camera_movement="m", composition="c",
        lighting="深夜月光低照度", mood="m", generation_mode="image_to_video"
    )
    shot2 = ShotSpec(
        shot_id="s01_sh02", scene_id="s01", order=2, duration_seconds=5.0,
        narrative_purpose="p", subject_ids=["c1"], location_id="l1",
        start_frame="s", action="a", end_frame="e",
        shot_size="MS", camera_angle="a", camera_movement="m", composition="c",
        lighting="白天强日照高光", mood="m", generation_mode="image_to_video"
    )

    issues = continuity_checker.check_deterministic([shot1, shot2], bible)
    light_warnings = [i for i in issues if i.field == "lighting"]
    assert len(light_warnings) > 0
    assert light_warnings[0].severity == "warning"
