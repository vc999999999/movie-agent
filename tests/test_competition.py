import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agent.service import ProjectService
from agent.execution import ProjectBusy, LeaseLost, NeedsClarification, QualityFailed, SubmissionUncertain
from agent.media import AssetMetadata, Timeline, command, digest, probe
from agent.models import ErrorDetail
from agent.quality import Review, ReviewIssue, Revision, extract_constraints
from server.db import Database, get_db_connection
from conftest import bind_reference


async def ready(reference_bytes):
    service = ProjectService()
    pid = service.create_project("10秒雨夜侦探预告片，无对白")["id"]
    await service.analyze_input(pid)
    await service.confirm_brief(pid)
    await bind_reference(service, pid, reference_bytes)
    return service, pid


def test_leases_expire_and_fence_writes(tmp_path):
    from agent.execution import lease_context, current_task
    db = Database(tmp_path / "test.db")
    db.create_project("p", None, "idea")
    db.acquire_lease("p", "first")
    with pytest.raises(ProjectBusy):
        db.acquire_lease("p", "second")
    conn = get_db_connection(db.db_path)
    with conn:
        conn.execute("UPDATE execution_leases SET expires_at=0")
    conn.close()
    db.acquire_lease("p", "second")
    token = lease_context.set((str(db.db_path), "p", "first", current_task()))
    try:
        with pytest.raises(LeaseLost):
            db.save_artifact("p", "should_not_exist", {})
    finally:
        lease_context.reset(token)
    assert db.get_latest_artifact("p", "should_not_exist") is None
    db.release_lease("p", "first")
    db.assert_lease("p", "second")


@pytest.mark.asyncio
async def test_parallel_request_and_input_edit_conflict(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    started, finish = asyncio.Event(), asyncio.Event()
    original = service.comfyui.wait_for_completion
    async def wait(*args, **kwargs):
        started.set()
        await finish.wait()
        return await original(*args, **kwargs)
    monkeypatch.setattr(service.comfyui, "wait_for_completion", wait)
    sid = service.get_shots(pid)[0]["shot_id"]
    task = asyncio.create_task(service.render_shot(pid, sid))
    await started.wait()
    try:
        with pytest.raises(ProjectBusy):
            await service.render_shot(pid, sid)
        with pytest.raises(ProjectBusy):
            service.update_shot(pid, sid, {"action": "changed"})
    finally:
        finish.set()
        await task


@pytest.mark.asyncio
async def test_resume_reuses_success_and_corruption_invalidates(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    original = service.comfyui.submit_prompt
    calls = []
    async def submit(workflow, **kwargs):
        calls.append(workflow)
        if len(calls) == 3:
            return None, ErrorDetail(code="INVALID_INPUT", message="injected failure")
        return await original(workflow, **kwargs)
    monkeypatch.setattr(service.comfyui, "submit_prompt", submit)
    first = await service.render_all_shots(pid)
    assert first[2].status == "failed"
    second = await service.render_all_shots(pid)
    assert second[0].id == first[0].id and second[1].id == first[1].id
    assert all(r.status == "success" for r in second)
    assert len(calls) == len(first) + 1
    saved_prompt = service.get_packages(pid)["prompt_packages"][0]
    await service.compile_packages(pid)
    assert service.get_packages(pid)["prompt_packages"][0] == saved_prompt
    sid = second[0].shot_id
    Path(second[0].output_json["file_path"]).write_bytes(b"corrupt")
    replacement = await service.render_shot(pid, sid)
    assert replacement.id != second[0].id
    service.update_shot(pid, sid, {"action": "侦探转头观察新证据"})
    await service.compile_packages(pid)
    changed = await service.render_shot(pid, sid)
    assert changed.request_json["fingerprint"] != replacement.request_json["fingerprint"]


@pytest.mark.asyncio
async def test_unknown_submit_never_resubmitted(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    submit = AsyncMock(return_value=(None, ErrorDetail(code="SUBMISSION_UNCERTAIN", message="lost response")))
    monkeypatch.setattr(service.comfyui, "submit_prompt", submit)
    sid = service.get_shots(pid)[0]["shot_id"]
    run = await service.render_shot(pid, sid)
    assert run.status == "running"
    with pytest.raises(SubmissionUncertain):
        await service.render_shot(pid, sid)
    assert submit.await_count == 1


@pytest.mark.asyncio
async def test_remote_id_is_polled_after_restart(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    sid = service.get_shots(pid)[0]["shot_id"]
    packages = service.get_packages(pid)
    prompt, plan = packages["prompt_packages"][0], packages["workflow_plans"][0]
    request = {**prompt, "fingerprint": service.render_fingerprint(pid, prompt, plan)}
    service.db.create_render_run({"id": "remote_pending", "project_id": pid, "shot_id": sid, "workflow_id": plan["workflow_id"], "status": "running", "request_json": request, "prompt_id": "known_remote"})
    submit = AsyncMock(side_effect=AssertionError("Must not resubmit"))
    monkeypatch.setattr(service.comfyui, "submit_prompt", submit)
    resumed = await ProjectService().render_shot(pid, sid)
    assert resumed.id == "remote_pending" and resumed.status == "success"
    submit.assert_not_awaited()


def test_constraints_preserve_evidence_and_conflicts():
    extracted = extract_constraints("30秒，竖屏，两名角色，无对白")
    assert extracted["values"] == {"duration_seconds": 30, "aspect_ratio": "9:16", "character_count": 2, "dialogue_mode": "none"}
    assert all(e["quote"] for e in extracted["evidence"])
    assert extract_constraints("30秒或60秒，横屏和竖屏")["conflicts"]
    assert extract_constraints("两分钟的电影")["conflicts"]
    assert extract_constraints("120秒")["conflicts"]


@pytest.mark.asyncio
async def test_hard_constraints_need_clarification():
    service = ProjectService()
    pid = service.create_project("120秒，横屏和竖屏")["id"]
    with pytest.raises(NeedsClarification):
        await service.analyze_input(pid)
    service.update_constraints(pid, "30秒，竖屏")
    await service.analyze_input(pid)
    assert service.get_project(pid)["brief"]["duration_seconds"] == 30
    with pytest.raises(NeedsClarification):
        service.update_brief(pid, {"duration_seconds": 60})


@pytest.mark.asyncio
async def test_local_repair_preserves_other_shots(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    before = service.get_shots(pid)
    bad = json.loads(json.dumps(before))
    bad[0]["subject_ids"] = ["missing"]
    service.db.save_artifact(pid, "shot_list", bad)
    async def structured(system, user, schema, fallback_fn=None):
        if schema is Review:
            return Review()
        assert schema is Revision
        payload = json.loads(user)
        assert payload["allowed_shot_ids"] == [before[0]["shot_id"]]
        return Revision(shots=[before[0]])
    monkeypatch.setattr(service.llm, "structured_call", structured)
    result = await service.review_and_repair(pid)
    assert result["passed"]
    assert service.get_shots(pid) == before
    assert len(service.db.list_artifacts(pid, "revision")) == 1


@pytest.mark.asyncio
async def test_content_repair_limit_and_scope(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    shots = service.get_shots(pid)
    issue = ReviewIssue(severity="error", role="director", shot_ids=[shots[0]["shot_id"]], evidence="首镜没有说明行动动机", instruction="补充可见动机")
    attempts = []
    async def structured(system, user, schema, fallback_fn=None):
        if schema is Review:
            return Review(issues=[issue])
        attempts.append(1)
        return Revision(shots=[shots[0]])
    monkeypatch.setattr(service.llm, "structured_call", structured)
    with pytest.raises(QualityFailed):
        await service.review_and_repair(pid)
    assert len(attempts) == 2
    assert service.get_shots(pid)[1:] == shots[1:]
    async def out_of_scope(system, user, schema, fallback_fn=None):
        return Review(issues=[issue]) if schema is Review else Revision(shots=[shots[1]])
    monkeypatch.setattr(service.llm, "structured_call", out_of_scope)
    with pytest.raises(QualityFailed, match="范围"):
        await service.review_and_repair(pid)


@pytest.mark.asyncio
async def test_missing_reference_and_real_workflow_binding(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    sid = service.get_shots(pid)[0]["shot_id"]
    upload = AsyncMock(return_value="uploaded/real.png")
    original = service.comfyui.submit_prompt
    submitted = []
    async def submit(workflow, **kwargs):
        submitted.append(workflow)
        return await original(workflow, **kwargs)
    monkeypatch.setattr(service.comfyui, "upload_image", upload)
    monkeypatch.setattr(service.comfyui, "submit_prompt", submit)
    assert (await service.render_shot(pid, sid)).status == "success"
    assert submitted[0]["52"]["inputs"]["image"] == "uploaded/real.png"
    service.update_shot(pid, sid, {"reference_asset_ids": []})
    await service.compile_packages(pid)
    with pytest.raises(ValueError, match="首帧"):
        await service.render_shot(pid, sid)


@pytest.mark.asyncio
async def test_audio_subtitles_and_atomic_cut(reference_bytes, tmp_path, monkeypatch):
    service, pid = await ready(reference_bytes)
    await service.render_all_shots(pid)
    sound = tmp_path / "voice.wav"
    await command("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=duration=10", str(sound))
    voice = await service.register_asset(pid, sound.read_bytes(), AssetMetadata(purpose="voice", source="test"))
    music = await service.register_asset(pid, sound.read_bytes(), AssetMetadata(purpose="music", source="test"))
    service.save_timeline(pid, Timeline(audio=[{"asset_id": voice["id"], "role": "voice", "start": 1, "end": 3}, {"asset_id": music["id"], "role": "music", "start": 0, "end": 10}], subtitles=[{"start": 1, "end": 3, "text": "你好，电影"}]))
    first = Path(await service.create_rough_cut(pid))
    info = await probe(first)
    assert abs(info["duration"] - 10) < .1
    assert {s["codec_type"] for s in info["streams"]} >= {"audio", "video", "subtitle"}
    original_hash = digest(first)
    async def fail(*args):
        raise ValueError("injected edit failure")
    monkeypatch.setattr("agent.media.command", fail)
    with pytest.raises(ValueError):
        await service.create_rough_cut(pid)
    assert digest(first) == original_hash
    assert service.db.get_latest_artifact(pid, "rough_cut")["content"]["file_path"] == str(first)


@pytest.mark.asyncio
async def test_invalid_upload_and_export_rights(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    with pytest.raises(ValueError):
        await service.register_asset(pid, b"not an image", AssetMetadata(purpose="reference", source="test"))
    await service.render_all_shots(pid)
    await service.create_rough_cut(pid)
    assert (await service.export_evidence(pid)).is_file()
    # Rights guard must also operate independently of the simulation guard.
    report = service.evidence_report(pid)
    report["simulation"] = False
    monkeypatch.setattr(service, "evidence_report", lambda _: report)
    asset = service.assets(pid)[0]
    service.update_asset_rights(pid, asset["id"], "pending", "")
    with pytest.raises(ValueError, match="授权"):
        await service.export_evidence(pid, competition=True)


@pytest.mark.asyncio
async def test_explicit_default_reference_and_stale_review(reference_bytes):
    service = ProjectService()
    pid = service.create_project("10秒横屏，无对白")["id"]
    await service.register_asset(pid, reference_bytes, AssetMetadata(purpose="reference", project_default=True, source="explicit default"))
    await service.run_auto_pipeline(pid)
    prompts = service.get_packages(pid)["prompt_packages"]
    assert all(p["reference_asset_ids"] for p in prompts)
    assert service.db.get_latest_artifact(pid, "quality_review") is not None
    service.update_shot(pid, service.get_shots(pid)[0]["shot_id"], {"action": "更改叙事动机"})
    assert service.db.get_latest_artifact(pid, "quality_review") is None
    assert service.get_pipeline_status(pid)["pipeline"]["status"] == "idle"


@pytest.mark.asyncio
async def test_short_video_is_rejected(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    from agent.media import command as real_command
    async def too_short(*args):
        if args[0] == "ffmpeg" and any("color=" in a for a in args):
            return await real_command("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=duration=0.5:size=32x32", args[-1])
        return await real_command(*args)
    monkeypatch.setattr("agent.service.command", too_short)
    run = await service.render_shot(pid, service.get_shots(pid)[0]["shot_id"])
    assert run.status == "failed" and run.error_json["code"] == "MEDIA_INVALID"


@pytest.mark.asyncio
async def test_retry_backoff_and_reconcile(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    original = service.comfyui.submit_prompt
    submit_count, delays = [], []
    async def submit(*args, **kwargs):
        submit_count.append(1)
        if len(submit_count) < 3:
            return None, ErrorDetail(code="RATE_LIMITED", message="429", retryable=True)
        return await original(*args, **kwargs)
    original_sleep = asyncio.sleep
    async def sleep(delay):
        if delay in (2, 4):
            delays.append(delay)
            await original_sleep(0)
        else:
            await original_sleep(delay)
    monkeypatch.setattr(service.comfyui, "submit_prompt", submit)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    sid = service.get_shots(pid)[0]["shot_id"]
    run = await service.render_shot(pid, sid)
    assert run.status == "success" and delays == [2, 4]
    service.db.create_render_run({"id": "unknown", "project_id": pid, "shot_id": sid, "workflow_id": run.workflow_id, "status": "running", "request_json": run.request_json})
    verified = service.reconcile_render(pid, "unknown", None, True, "Remote queue and history checked")
    assert verified["status"] == "failed"
    assert (await service.render_shot(pid, sid)).id == run.id


@pytest.mark.asyncio
async def test_fractional_shots_produce_exact_sixty_seconds(reference_bytes):
    service = ProjectService()
    pid = service.create_project("60秒横屏，无对白")["id"]
    await service.register_asset(pid, reference_bytes, AssetMetadata(purpose="reference", project_default=True, source="test"))
    await service.run_auto_pipeline(pid)
    artifact = service.db.get_latest_artifact(pid, "rough_cut")
    assert abs(artifact["content"]["media"]["duration"] - 60) < .1


@pytest.mark.asyncio
async def test_workflow_change_requires_recompilation(reference_bytes, monkeypatch):
    service, pid = await ready(reference_bytes)
    sid = service.get_shots(pid)[0]["shot_id"]
    old = await service.render_shot(pid, sid)
    raw = json.loads(json.dumps(service.workflows.raw_workflows[old.workflow_id]))
    raw["50"]["inputs"]["filename_prefix"] = "changed_workflow"
    monkeypatch.setitem(service.workflows.raw_workflows, old.workflow_id, raw)
    with pytest.raises(ValueError, match="重新编译"):
        await service.render_shot(pid, sid)
    await service.compile_packages(pid)
    new = await service.render_shot(pid, sid)
    assert new.id != old.id and new.request_json["fingerprint"] != old.request_json["fingerprint"]
