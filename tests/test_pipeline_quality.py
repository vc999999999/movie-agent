import pytest

from agent.service import ProjectService


@pytest.mark.asyncio
async def test_current_shots_are_checked_before_compiling_and_rendering():
    service = ProjectService()
    pid = service.create_project("30秒雨夜侦探追凶预告片")["id"]
    await service.analyze_input(pid)
    await service.confirm_brief(pid)
    await service.compile_packages(pid)
    shots = service.get_shots(pid)
    shots[0]["subject_ids"] = ["missing_character"]
    # Even a stale clean report must not authorize invalid current inputs.
    service.db.save_artifact(pid, "shot_list", shots)
    service.db.save_artifact(pid, "continuity_report", [])
    for action in (service.compile_packages(pid), service.render_shot(pid, shots[0]["shot_id"])):
        with pytest.raises(ValueError, match="quality gate"):
            await action
    assert service.db.list_render_runs(pid) == []


@pytest.mark.asyncio
async def test_pipeline_failure_is_persisted_and_visible_after_memory_reset(monkeypatch):
    service = ProjectService()
    pid = service.create_project("30秒雨夜侦探追凶预告片")["id"]

    async def failed_render(project_id):
        raise RuntimeError("render unavailable")

    monkeypatch.setattr(service, "render_all_shots", failed_render)
    with pytest.raises(RuntimeError, match="render unavailable"):
        await service.run_auto_pipeline(pid)
    service._pipeline_progress.pop(pid)
    progress = service.get_pipeline_status(pid)["pipeline"]
    assert progress["status"] == "failed"
    assert progress["steps"][-1]["step"] == "render"
    assert progress["steps"][-1]["status"] == "failed"
    assert progress["elapsed_seconds"] >= 0
    assert service.get_project(pid)["status"] == "failed"

    service.db.save_artifact(pid, "pipeline_progress", {"steps": [], "status": "running", "error": None})
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_one_sentence_pipeline_reaches_playable_cut(reference_bytes, monkeypatch):
    from pathlib import Path

    service = ProjectService()
    pid = service.create_project("30秒雨夜侦探追凶预告片")["id"]
    from agent.media import AssetMetadata
    asset = await service.register_asset(pid, reference_bytes, AssetMetadata(purpose="reference", source="explicit test input"))
    original = service.llm.build_shot_list
    async def with_reference(*args, **kwargs):
        shots = await original(*args, **kwargs)
        return [shot.model_copy(update={"reference_asset_ids": [asset["id"]]}) for shot in shots]
    monkeypatch.setattr(service.llm, "build_shot_list", with_reference)
    result = await service.run_auto_pipeline(pid)
    assert result["status"] == "completed"
    artifact = service.db.get_latest_artifact(pid, "rough_cut")
    assert Path(artifact["content"]["file_path"]).stat().st_size > 1000
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "completed"
