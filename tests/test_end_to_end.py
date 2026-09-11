from __future__ import annotations

import os
from pathlib import Path
import pytest
from agent.service import project_service

@pytest.mark.asyncio
async def test_case_1_30s_vertical_trailer():
    """Case 1: 一句话 30 秒竖屏预告片."""
    source_text = "做一个赛博朋克雨夜追逐的 30 秒竖屏预告片"
    project = project_service.create_project(source_text, title="30秒竖屏追逐")
    pid = project["id"]

    q_resp = await project_service.analyze_input(pid)
    assert q_resp.status in ["collecting", "brief_review"]

    # Confirm brief
    brief = await project_service.confirm_brief(pid)
    assert brief.duration_seconds == 30
    assert brief.aspect_ratio == "9:16"

    # Screenplay & shots
    screenplay_data = project_service.get_screenplay(pid)
    assert screenplay_data is not None
    shots = project_service.get_shots(pid)
    assert len(shots) >= 3

    total_dur = sum(s["duration_seconds"] for s in shots)
    # 5% tolerance for 30s: <= 1.5s
    assert abs(total_dur - 30) <= 1.5

    # Compile packages
    packages = await project_service.compile_packages(pid)
    assert len(packages["prompt_packages"]) == len(shots)
    for pkg in packages["prompt_packages"]:
        assert pkg["width"] == 720
        assert pkg["height"] == 1280

@pytest.mark.asyncio
async def test_case_2_60s_two_characters_with_dialogue():
    """Case 2: 60 秒剧情短片，两名角色与对白."""
    source_text = "60秒飞船太空危机短片，两名宇航员争夺最后的氧气面罩，有对白"
    project = project_service.create_project(source_text, title="60秒太空危机")
    pid = project["id"]

    q_resp = await project_service.analyze_input(pid)
    brief = await project_service.confirm_brief(pid, {
        "title": "太空危机",
        "duration_seconds": 60,
        "aspect_ratio": "16:9",
        "dialogue_mode": "dialogue",
        "logline": "两名宇航员在氧气耗尽的飞船中争夺生存希望",
        "visual_style": "硬科幻写实，冷光仪表盘阴影",
        "protagonist": "资深宇航员",
        "protagonist_goal": "活到救援到来",
        "conflict": "维生系统崩溃导致氧气不足",
        "ending": "反转结局"
    })

    shots = project_service.get_shots(pid)
    total_dur = sum(s["duration_seconds"] for s in shots)
    # 5% tolerance for 60s: <= 3.0s
    assert abs(total_dur - 60) <= 3.0

    packages = await project_service.compile_packages(pid)
    assert len(packages["prompt_packages"]) == len(shots)

@pytest.mark.asyncio
async def test_case_3_complete_pipeline_with_render_and_rough_cut():
    """Case 3: 完整管线测试：创意 -> 简报 -> 分镜 -> Prompt编译 -> PatchMap注入 -> 渲染 -> FFmpeg粗剪短片合成."""
    source_text = "做一个45秒雨夜侦探追凶预告片"
    project = project_service.create_project(source_text, title="全流程测试预告片")
    pid = project["id"]

    # 1. Step 1 -> Step 2
    await project_service.analyze_input(pid)
    await project_service.confirm_brief(pid)

    # 2. Step 3 Shots confirmation
    shots = await project_service.confirm_shots(pid)
    assert len(shots) >= 3

    # 3. Step 4 Packages compiled
    pkgs = project_service.get_packages(pid)
    assert len(pkgs["prompt_packages"]) >= 3
    assert len(pkgs["workflow_plans"]) >= 3

    # Verify patched workflow files were created on disk
    for plan in pkgs["workflow_plans"]:
        if plan["status"] == "matched":
            wf_path = plan["patched_workflow_path"]
            assert wf_path is not None
            assert os.path.exists(wf_path)

    # 4. Render all shots
    render_runs = await project_service.render_all_shots(pid)
    assert len(render_runs) == len(shots)
    for run in render_runs:
        assert run.status == "success"

    # 5. Rough cut synthesis with FFmpeg
    rough_cut_mp4 = await project_service.create_rough_cut(pid)
    assert os.path.exists(rough_cut_mp4)
    assert os.path.getsize(rough_cut_mp4) > 1000
