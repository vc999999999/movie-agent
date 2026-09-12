from agent.models import ShotSpec
from agent.production_packs import auteur_profile_registry, production_pack_registry
from agent.service import project_service


def _shot(shot_id: str, duration: float = 3) -> ShotSpec:
    return ShotSpec(
        shot_id=shot_id,
        scene_id="scene_01",
        order=int(shot_id[-1]),
        grammar_pack_id="action_chase_v1",
        sequence_pattern="pursuit",
        shot_function="launch_action",
        information_revealed="人物开始逃跑",
        duration_seconds=duration,
        narrative_purpose="推进追逐",
        subject_ids=["hero"],
        location_id="alley",
        start_frame="人物站在巷口",
        action="人物向右跑",
        end_frame="人物到达转角",
        shot_size="WS",
        camera_angle="平视",
        camera_movement="平移跟拍",
        composition="方向明确",
        lighting="夜景",
        mood="紧张",
    )


def test_pack_registry_and_grammar_validation():
    packs = production_pack_registry.list()
    assert len(packs) == 3
    assert len({pack.directing_grammar.grammar_id for pack in packs}) == 3

    pack = production_pack_registry.get("action_chase_v1")
    issues = production_pack_registry.validate_shots(
        [_shot("shot1"), _shot("shot2"), _shot("shot3", duration=5)],
        pack,
    )
    assert {issue.code for issue in issues} >= {"REPEATED_SHOT_SIZE", "SHOT_TOO_LONG"}


async def test_treatment_path_generates_grammar_bound_shots():
    project = project_service.create_project("做一个30秒雨夜侦探追凶悬疑预告片")
    await project_service.analyze_input(project["id"])
    await project_service.confirm_brief(project["id"])
    auteur = project_service.apply_auteur_profile(
        project["id"],
        "christopher_nolan_technique_study",
        "parallel_time_pressure",
        "strong",
        ["侦探主角", "雨夜场景"],
    )
    assert auteur_profile_registry.variant(auteur.profile, auteur.selection.variant_id).reference_works
    treatments = await project_service.generate_treatments(project["id"])
    assert 2 <= len(treatments.options) <= 3
    assert all(option.technique_plan for option in treatments.options)

    await project_service.confirm_treatment(project["id"], treatments.recommendation)
    await project_service.run_auto_pipeline(project["id"])
    shots = project_service.get_shots(project["id"])
    selected = next(item for item in treatments.options if item.treatment_id == treatments.recommendation)
    assert shots and all(shot["grammar_pack_id"] == selected.production_pack_id for shot in shots)
    assert all(shot["auteur_profile_id"] == auteur.profile.profile_id for shot in shots)
    assert all(len(shot["technique_ids"]) == 2 for shot in shots)
    assert project_service.db.get_latest_artifact(project["id"], "grammar_report") is not None
    assert project_service.db.get_latest_artifact(project["id"], "auteur_report")["content"] == []

    await project_service.confirm_shots(project["id"])
    pack = production_pack_registry.get(selected.production_pack_id)
    plans = project_service.get_packages(project["id"])["workflow_plans"]
    assert plans and all(plan["workflow_id"] == pack.generation_recipe.workflow_id for plan in plans)
