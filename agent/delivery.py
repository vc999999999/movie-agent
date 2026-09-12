"""Portable, snapshot-based production handoff. Never submits a render job."""
from __future__ import annotations

import io
import json
import zipfile
from typing import Any


def ui_workflow(registry, workflow_id: str, patched: dict) -> dict | None:
    root = registry.workflows_dir / workflow_id
    if not (root / "workflow_ui.json").is_file():
        return None
    graph = json.loads((root / "workflow_ui.json").read_text())
    widget_map = json.loads((root / "widget_map.json").read_text())
    if {str(n["id"]) for n in graph["nodes"]} != set(patched):
        raise ValueError("工作流模板已升级，请重新编译后导出")
    for node in graph["nodes"]:
        inputs = patched[str(node["id"])]["inputs"]
        for name, index in widget_map.get(str(node["id"]), {}).items():
            node["widgets_values"][index] = inputs[name]
    return graph


def delivery_snapshot(service, project_id: str) -> tuple[dict, dict[str, Any]]:
    project = service.get_project(project_id)
    if not project:
        raise ValueError("项目不存在")
    service.ensure_not_generating(project_id)
    service.validate_shots_for_export(project_id)
    packages = service.get_packages(project_id)
    if not packages["prompt_packages"]:
        raise ValueError("请先生成制作流程；上游修改后需要重新编译")
    screenplay = service.get_screenplay(project_id)
    shots = service.get_shots(project_id)
    files: dict[str, Any] = {
        "brief.json": project["brief"],
        "screenplay.json": screenplay,
        "shots.json": shots,
        "prompts.json": packages["prompt_packages"],
        "production_report.md": packages.get("production_report", ""),
    }
    for name in ("auteur_profile", "selected_treatment", "production_pack", "continuity_report", "grammar_report", "auteur_report"):
        artifact = service.db.get_latest_artifact(project_id, name)
        if artifact:
            files[f"{name}.json"] = artifact["content"]
    by_shot = {s["shot_id"]: s for s in shots}
    prompts = {p["shot_id"]: p for p in packages["prompt_packages"]}
    requirements, items, assets = {}, [], []
    for plan in packages["workflow_plans"]:
        shot_id = plan["shot_id"]
        # Shot ids are validated in ShotSpec; still do not trust stored paths for archive names.
        if not shot_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in shot_id):
            raise ValueError("镜头编号不适合导出")
        item = {"shot_id": shot_id, "workflow_id": plan["workflow_id"], "status": plan["status"], "reason": plan.get("reason"), "api_file": None, "ui_file": None}
        if plan["status"] == "matched" and plan.get("patched_workflow_path"):
            path = service._project_file(project_id, plan["patched_workflow_path"])
            if not path.is_file():
                raise ValueError(f"{shot_id} 工作流文件缺失，请重新编译")
            patched = json.loads(path.read_text())
            item["api_file"] = f"workflows/api/{shot_id}.json"
            files[item["api_file"]] = patched
            ui = ui_workflow(service.workflows, plan["workflow_id"], patched)
            if ui:
                item["ui_file"] = f"workflows/ui/{shot_id}.json"
                files[item["ui_file"]] = ui
            profile = service.workflows.get_profile(plan["workflow_id"])
            requirements[profile.workflow_id] = profile.model_dump()
            source = service.workflows.workflows_dir / profile.workflow_id / "SOURCE.md"
            if source.is_file():
                files[f"dependencies/{profile.workflow_id}_source.md"] = source.read_text()
        shot = by_shot[shot_id]
        if shot["generation_mode"] == "image_to_video":
            bible = screenplay["project_bible"]
            characters = [c for c in bible["characters"] if c["character_id"] in shot["subject_ids"]]
            location = next((l for l in bible["locations"] if l["location_id"] == shot["location_id"]), {})
            first_prompt = "; ".join(filter(None, [bible["visual_style"], *[f'{c["name"]}: {c["fixed_appearance"]}, {c["fixed_costume"]}' for c in characters], location.get("fixed_visual_description"), shot["start_frame"], shot["composition"], shot["lighting"]]))
            assets.append({"shot_id": shot_id, "filename": f"{shot_id}_first_frame.png", "status": "user_required", "destination": "ComfyUI/input/", "positive_prompt": first_prompt, "negative_prompt": prompts[shot_id]["negative_prompt"], "width": prompts[shot_id]["width"], "height": prompts[shot_id]["height"], "reference_asset_ids": shot.get("reference_asset_ids", [])})
        items.append(item)
    files["assets/requirements.json"] = assets
    files["dependencies/models_and_nodes.json"] = list(requirements.values())
    matched = sum(bool(i["api_file"]) for i in items)
    manifest = {"schema_version": 1, "project_id": project_id, "title": project["title"], "status": "complete" if matched == len(shots) and matched > 0 else "partial", "shot_count": len(shots), "workflow_count": matched, "ui_workflow_count": sum(bool(i["ui_file"]) for i in items), "required_asset_count": len(assets), "execution_verified": False, "environment_check": "Run on recipient ComfyUI; server GPU not required for export", "workflows": items, "assets": assets, "dependencies": list(requirements.values())}
    files["manifest.json"] = manifest
    files["README.md"] = f'''# {project["title"] or "电影制作包"}

本包包含 {len(shots)} 个镜头，已导出 {matched} 个工作流。交付状态：{manifest["status"]}。
工作流参数已注入；未在接收者的 GPU / ComfyUI 环境实际渲染验证。

## 使用顺序

1. 查看 `dependencies/models_and_nodes.json`，准备对应模型与节点。模型路径相对于 ComfyUI/models。
2. 阅读 `assets/requirements.json`，按每个镜头的首帧提示词生成或自行准备图片，保持人物外观一致。按 filename 命名，放进 ComfyUI/input/。本包不包含实际图片或模型权重。
3. 将 `workflows/ui/` 内的镜头 JSON 拖入 ComfyUI。检查模型下拉框和 LoadImage，点击运行。
4. `workflows/api/` 是 API 格式，供脚本调用 /prompt；不要将它误认为包含布局信息的界面工作流。没有 UI 文件的旧模板需按依赖在本地校验。
5. 按 `shots.json` 的 order 顺序收集视频，参考剧本和声音设计剪辑。配音、音乐、音效是制作说明，不会由视频工作流自动合成。

## 制作资料

- brief.json：确认后的剧情需求。
- screenplay.json：角色、场景设定与剧本。
- selected_treatment.json / auteur_profile.json：用户选择的方案和导演技法（如已选择）。
- shots.json / prompts.json：镜头、时长、运镜与正负提示词。
- manifest.json：完整性、各镜头文件、缺失项和依赖。
- production_report.md：制作报告。

## 未完成项

{chr(10).join('- ' + i['shot_id'] + ': ' + str(i['reason'] or '未匹配模板') for i in items if not i['api_file']) or '- 所有镜头均已导出参数工作流。'}

首帧素材仍需准备；模板匹配不代表素材就绪或渲染成功。部分交付包中未匹配镜头不会伪造工作流。
Wan 原生模板来源及改动见 dependencies 下的 source 文件。帧数对齐模型要求，实际片段时长可与分镜时长有小幅差异，剪辑时按镜头表裁切。
'''
    return manifest, files


def build_archive(service, project_id: str) -> bytes:
    _, files = delivery_snapshot(service, project_id)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
            archive.writestr(name, content)
    return buffer.getvalue()
