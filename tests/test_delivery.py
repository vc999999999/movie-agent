import asyncio
import io
import json
import zipfile

import pytest
from starlette.testclient import TestClient
from agent.delivery import build_archive, delivery_snapshot
from agent.service import project_service as service
from server.config import settings
from server.main import app


async def chosen_project():
    pid = service.create_project("30秒雨夜侦探追凶悬疑短片，必须保留红色围巾")["id"]
    await service.analyze_input(pid)
    await service.confirm_brief(pid, {"user_must_keep": ["红色围巾"], "genre": ["悬疑"]})
    package = await service.generate_treatments(pid)
    await service.confirm_treatment(pid, package.options[-1].treatment_id)
    return pid, package.options[-1].treatment_id


async def test_explicit_selection_before_production():
    pid = service.create_project("30秒雨夜追凶")["id"]
    await service.analyze_input(pid)
    await service.confirm_brief(pid)
    assert service.get_project(pid)["status"] == "director_review"
    assert service.get_screenplay(pid) is None
    with pytest.raises(ValueError, match="导演方案"):
        await service.run_auto_pipeline(pid)
    with pytest.raises(ValueError, match="导演方案"):
        service.start_auto_pipeline(pid)
    assert service.db.get_latest_artifact(pid, "selected_treatment") is None


async def test_offline_export_preserves_selection_and_contains_patched_ui(monkeypatch):
    pid, chosen = await chosen_project()
    assert service.get_screenplay(pid) is None
    async def forbidden(*args, **kwargs):
        raise AssertionError("Portable production must not contact a renderer")
    monkeypatch.setattr(service.comfyui, "get_object_info", forbidden)
    monkeypatch.setattr(service, "render_all_shots", forbidden)
    monkeypatch.setattr(service, "create_rough_cut", forbidden)
    monkeypatch.setattr(settings, "comfyui_vram_gb", 0)
    await service.run_auto_pipeline(pid)
    assert service.get_project(pid)["status"] == "package_ready"
    assert service.db.get_latest_artifact(pid, "selected_treatment")["content"]["treatment_id"] == chosen
    manifest, _ = delivery_snapshot(service, pid)
    assert manifest["status"] == "complete"
    assert manifest["workflow_count"] == manifest["shot_count"] == manifest["ui_workflow_count"]
    assert manifest["execution_verified"] is False
    assert not service.db.list_render_runs(pid)
    blob = build_archive(service, pid)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert all(not n.startswith("/") and ".." not in n for n in archive.namelist())
        for item in manifest["workflows"]:
            api = json.loads(archive.read(item["api_file"]))
            ui = json.loads(archive.read(item["ui_file"]))
            nodes = {str(n["id"]): n for n in ui["nodes"]}
            assert api["52"]["inputs"]["image"] == f'{item["shot_id"]}_first_frame.png'
            assert nodes["52"]["widgets_values"][0] == api["52"]["inputs"]["image"]
            assert nodes["6"]["widgets_values"][0] == api["6"]["inputs"]["text"]
            assert (api["50"]["inputs"]["length"] - 1) % 4 == 0
            assert api["6"]["inputs"]["clip"] == ["38", 0]
            assert nodes["47"]["mode"] == 0
        assert "红色围巾" in archive.read("brief.json").decode()
        assert "ComfyUI/input/" in archive.read("README.md").decode()
    with TestClient(app) as client:
        response = client.get(f"/api/projects/{pid}/export")
        assert response.status_code == 200 and response.content[:2] == b"PK"
        first = manifest["workflows"][0]["shot_id"]
        assert "nodes" in client.get(f"/api/projects/{pid}/workflow/{first}?format=ui").json()
    # Edits must revoke all previous delivery files, even if they remain on disk.
    service.update_shot(pid, first, {"action": "侦探停下来查看红围巾"})
    with pytest.raises(ValueError, match="重新编译"):
        build_archive(service, pid)


async def test_brief_patch_preserves_unedited_fields_and_invalidates_downstream():
    pid, _ = await chosen_project()
    await service.run_auto_pipeline(pid)
    await service.confirm_brief(pid, {"title": "新的片名"})
    brief = service.get_project(pid)["brief"]
    assert brief["user_must_keep"] == ["红色围巾"] and brief["genre"] == ["悬疑"]
    assert service.get_screenplay(pid) is None
    assert service.get_packages(pid)["prompt_packages"] == []


def test_all_default_answers_can_advance():
    with TestClient(app) as client:
        pid = client.post("/api/projects", json={"source_text": "一个人等待"}).json()["project"]["id"]
        result = client.post(f"/api/projects/{pid}/answers", json={"answers": []})
        assert result.status_code == 200
        assert result.json()["can_confirm"] is True
        assert result.json()["status"] == "brief_review"


async def test_running_pipeline_blocks_edits_and_can_retry(monkeypatch):
    pid, _ = await chosen_project()
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.generate_screenplay
    async def paused(project_id):
        entered.set()
        await release.wait()
        return await original(project_id)
    monkeypatch.setattr(service, "generate_screenplay", paused)
    service.start_auto_pipeline(pid)
    await entered.wait()
    with pytest.raises(ValueError, match="正在生成"):
        service.update_brief(pid, {"title": "race"})
    assert service.start_auto_pipeline(pid)["status"] == "running"
    release.set()
    await service._pipeline_tasks[pid]
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "completed"


async def test_partial_export_names_missing_workflows():
    pid, _ = await chosen_project()
    await service.run_auto_pipeline(pid)
    shot_id = service.get_shots(pid)[0]["shot_id"]
    service.update_shot(pid, shot_id, {"last_frame_required": True})
    await service.compile_packages(pid)
    manifest, files = delivery_snapshot(service, pid)
    assert manifest["status"] == "partial"
    missing = next(item for item in manifest["workflows"] if item["shot_id"] == shot_id)
    assert missing["api_file"] is None and missing["reason"]
    assert f"workflows/api/{shot_id}.json" not in files
    assert shot_id in files["README.md"]


async def test_compile_cannot_bypass_invalid_duration():
    pid, _ = await chosen_project()
    await service.run_auto_pipeline(pid)
    first = service.get_shots(pid)[0]
    service.update_shot(pid, first["shot_id"], {"duration_seconds": 12})
    with pytest.raises(ValueError, match="5%"):
        await service.compile_packages(pid)
    with pytest.raises(ValueError):
        build_archive(service, pid)


async def test_retry_reuses_screenplay_and_never_reselects(monkeypatch):
    pid, chosen = await chosen_project()
    original = service.generate_shots
    async def fail(*args):
        raise RuntimeError("temporary generation failure")
    monkeypatch.setattr(service, "generate_shots", fail)
    with pytest.raises(RuntimeError):
        await service.run_auto_pipeline(pid)
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "failed"
    assert service.get_screenplay(pid) is not None
    monkeypatch.setattr(service, "generate_shots", original)
    async def forbid(*args):
        raise AssertionError("Do not regenerate existing screenplay")
    monkeypatch.setattr(service, "generate_screenplay", forbid)
    await service.run_auto_pipeline(pid)
    assert service.db.get_latest_artifact(pid, "selected_treatment")["content"]["treatment_id"] == chosen
    service._pipeline_progress.pop(pid)
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "completed"


async def test_legacy_workflow_requests_recompile():
    pid, _ = await chosen_project()
    await service.run_auto_pipeline(pid)
    first = service.get_packages(pid)["workflow_plans"][0]
    path = service._project_file(pid, first["patched_workflow_path"])
    path.write_text(json.dumps({"10": {"class_type": "WanVideoModelLoader", "inputs": {}}}))
    with pytest.raises(ValueError, match="模板已升级"):
        delivery_snapshot(service, pid)
    await service.compile_packages(pid)
    assert delivery_snapshot(service, pid)[0]["status"] == "complete"
