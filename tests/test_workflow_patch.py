from __future__ import annotations

from agent.models import ShotPrompt, ShotSpec
from agent.workflow import workflow_registry

def test_workflow_loading():
    assert "flux_character_sheet_v1" in workflow_registry.profiles
    assert "wan_i2v_v1" in workflow_registry.profiles
    assert "cogvideox_t2v_v1" in workflow_registry.profiles

def test_workflow_selection_matched():
    shot = ShotSpec(
        shot_id="s01_sh01",
        scene_id="s01",
        order=1,
        duration_seconds=3.5,
        narrative_purpose="action",
        subject_ids=["char_01"],
        location_id="loc_01",
        start_frame="start",
        action="action",
        end_frame="end",
        shot_size="MS",
        camera_angle="eye",
        camera_movement="pan",
        composition="center",
        lighting="dim",
        mood="tense",
        generation_mode="image_to_video",
        first_frame_required=True,
    )

    plan = workflow_registry.select_workflow(shot, aspect_ratio="16:9")
    assert plan.status == "matched"
    assert plan.workflow_id == "wan_i2v_v1"

def test_workflow_selection_unsupported():
    shot = ShotSpec(
        shot_id="s01_sh02",
        scene_id="s01",
        order=2,
        duration_seconds=3.0,
        narrative_purpose="action",
        subject_ids=[],
        location_id="loc_01",
        start_frame="start",
        action="action",
        end_frame="end",
        shot_size="MS",
        camera_angle="eye",
        camera_movement="pan",
        composition="center",
        lighting="dim",
        mood="tense",
        generation_mode="image_to_video",
        last_frame_required=True,  # wan_i2v_v1 does not accept last_frame
    )

    plan = workflow_registry.select_workflow(shot, aspect_ratio="16:9")
    assert plan.status == "unsupported"
    assert "last_frame" in plan.reason or "last_frame" in plan.required_capabilities

def test_workflow_deterministic_patching_and_immutability(tmp_path):
    # Snapshot original template
    original_raw = workflow_registry.get_raw_workflow("wan_i2v_v1")

    prompt_pkg = ShotPrompt(
        shot_id="s01_sh01",
        prompt_language="en",
        positive_prompt="Cinematic rain action, photorealistic",
        negative_prompt="blurry, bad quality",
        seed=12345678,
        steps=30,
        cfg=6.5,
        width=1280,
        height=720,
        frame_count=84,
        fps=24,
    )

    out_file = tmp_path / "patched_wan.json"
    patched, err = workflow_registry.patch_workflow(
        workflow_id="wan_i2v_v1",
        prompt_pkg=prompt_pkg,
        output_file_path=out_file,
    )

    assert err is None
    assert out_file.exists()

    # 18.4: Verify PatchMap values were correctly injected into target nodes
    # positive_prompt node 40
    assert patched["40"]["inputs"]["text"] == "Cinematic rain action, photorealistic"
    # negative_prompt node 41
    assert patched["41"]["inputs"]["text"] == "blurry, bad quality"
    # sampler node 30
    assert patched["30"]["inputs"]["seed"] == 12345678
    assert patched["30"]["inputs"]["width"] == 1280
    assert patched["30"]["inputs"]["height"] == 720
    assert patched["30"]["inputs"]["length"] == 84

    # 18.4: Verify other nodes remain untouched
    assert patched["10"]["inputs"]["model_name"] == "Wan2.1-I2V-14B-720P.safetensors"

    # 18.4: Raw template remains untouched in registry
    assert workflow_registry.get_raw_workflow("wan_i2v_v1") == original_raw
