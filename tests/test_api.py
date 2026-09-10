from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_workflows_list():
    res = client.get("/api/workflows")
    assert res.status_code == 200
    workflows = res.json()
    assert len(workflows) >= 3
    ids = [w["workflow_id"] for w in workflows]
    assert "flux_character_sheet_v1" in ids
    assert "wan_i2v_v1" in ids
    assert "cogvideox_t2v_v1" in ids

def test_api_project_lifecycle():
    # 1. Create project
    create_res = client.post("/api/projects", json={
        "source_text": "做一个45秒赛博朋克雨夜追凶预告片，竖屏，冷色调",
        "title": "测试预告片"
    })
    assert create_res.status_code == 200
    data = create_res.json()
    project_id = data["project"]["id"]
    assert project_id.startswith("prj_")

    # 2. Get project
    get_res = client.get(f"/api/projects/{project_id}")
    assert get_res.status_code == 200
    assert get_res.json()["project"]["id"] == project_id

    # 3. Submit an answer
    ans_res = client.post(f"/api/projects/{project_id}/answers", json={
        "answers": [{"field": "ending", "answer": "预告片式悬念"}]
    })
    assert ans_res.status_code == 200

    # 4. Confirm brief
    confirm_res = client.post(f"/api/projects/{project_id}/brief/confirm", json={
        "title": "测试预告片",
        "duration_seconds": 45,
        "aspect_ratio": "9:16",
        "dialogue_mode": "voiceover",
        "logline": "侦探在雨夜追凶",
        "visual_style": "赛博朋克写实冷光",
        "protagonist": "侦探",
        "protagonist_goal": "查清真相",
        "conflict": "凶手伏击",
        "ending": "悬念收尾"
    })
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "success"

    # 5. Check screenplay
    sp_res = client.get(f"/api/projects/{project_id}/screenplay")
    assert sp_res.status_code == 200
    sp_data = sp_res.json()
    assert len(sp_data["project_bible"]["characters"]) >= 1
    assert len(sp_data["scenes"]) >= 1

    # 6. Check shots
    shots_res = client.get(f"/api/projects/{project_id}/shots")
    assert shots_res.status_code == 200
    shots_data = shots_res.json()
    assert len(shots_data["shots"]) >= 3
    # 5% duration tolerance
    assert abs(shots_data["total_duration"] - 45) <= 2.25

    # 7. Confirm shots and compile packages
    conf_shots_res = client.post(f"/api/projects/{project_id}/shots/confirm")
    assert conf_shots_res.status_code == 200

    # 8. Check packages & patched workflows
    pkg_res = client.get(f"/api/projects/{project_id}/packages")
    assert pkg_res.status_code == 200
    pkg_data = pkg_res.json()
    assert len(pkg_data["prompt_packages"]) >= 3
    assert len(pkg_data["workflow_plans"]) >= 3

    # 9. Test single shot render (mock/real mode)
    first_shot_id = pkg_data["prompt_packages"][0]["shot_id"]
    render_res = client.post(f"/api/shots/{first_shot_id}/render", json={"project_id": project_id})
    assert render_res.status_code == 200
    render_run = render_res.json()
    assert render_run["status"] in ["success", "running"]
