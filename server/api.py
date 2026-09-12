from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import FileResponse, Response
from agent.delivery import build_archive, delivery_snapshot, ui_workflow
from pydantic import BaseModel, ConfigDict, Field

from server.config import settings
from server.db import db
from agent.service import project_service
from agent.production_packs import auteur_profile_registry, production_pack_registry
from agent.workflow import workflow_registry

async def protect_production(request: Request):
    if request.method not in ("GET", "HEAD"):
        project_id = request.path_params.get("project_id")
        if project_id and not request.url.path.endswith("/auto_pipeline"):
            try:
                project_service.ensure_not_generating(project_id)
            except ValueError as e:
                raise HTTPException(status_code=409, detail=str(e))

router = APIRouter(prefix="/api", dependencies=[Depends(protect_production)])

@router.get("/capabilities")
async def capabilities():
    return {"demo_mode": settings.llm_mock_mode, "render_backend": settings.render_backend, "version": "0.3.0", "revision": settings.deployment_revision}


@router.get("/health", summary="部署完整性检查")
async def health():
    required_prompts = ["extract_brief.md", "generate_treatments.md", "build_screenplay.md", "build_shots.md"]
    prompts_ready = all((settings.prompts_dir / name).is_file() for name in required_prompts)
    return {"status": "ok" if prompts_ready else "incomplete", "version": "0.3.0", "revision": settings.deployment_revision,
            "prompt_templates_ready": prompts_ready, "workflow_templates": len(workflow_registry.profiles),
            "persistent_storage": settings.data_dir.is_relative_to("/mnt/workspace"), "demo_mode": settings.llm_mock_mode}

class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class CreateProjectRequest(RequestModel):
    source_text: str = Field(min_length=1, max_length=50_000, description="创意想法、梗概或剧本片段")
    title: Optional[str] = Field(default=None, max_length=200)

class SendMessageRequest(RequestModel):
    content: str = Field(min_length=1, max_length=10_000)

class AnswerItem(RequestModel):
    field: str = Field(min_length=1, max_length=64)
    answer: str = Field(min_length=1, max_length=2_000)

class SubmitAnswersRequest(RequestModel):
    answers: list[AnswerItem] = Field(default_factory=list, max_length=3)
    use_defaults: bool = False

class UpdateBriefRequest(RequestModel):
    updates: dict[str, Any]

class UpdateShotRequest(RequestModel):
    updates: dict[str, Any]

class ConfirmTreatmentRequest(RequestModel):
    production_pack_id: Optional[str] = None

class ApplyAuteurProfileRequest(RequestModel):
    profile_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    variant_id: Optional[str] = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,99}$")
    intensity: Literal["subtle", "balanced", "strong"] = "balanced"
    preserve: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(default_factory=list, max_length=20)

class RenderShotRequest(RequestModel):
    project_id: str = Field(pattern=r"^prj_[0-9a-f]{8}$")

PROJECT_ID_RE = re.compile(r"^prj_[0-9a-f]{8}$")
SHOT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

def project_file(project_id: str, *parts: str):
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise HTTPException(status_code=400, detail="Invalid project ID")
    root = (settings.data_dir / project_id).resolve()
    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Invalid project path")
    return path

# 10.1 Projects & Dialogue
@router.post("/projects", summary="创建新项目并执行初始意图抽取")
async def create_project(req: CreateProjectRequest):
    project = project_service.create_project(req.source_text, req.title)
    q_resp = await project_service.analyze_input(project["id"])
    return {
        "project": project_service.get_project(project["id"]),
        "questions_response": q_resp,
    }

@router.get("/projects", summary="获取所有项目列表")
async def list_projects():
    return project_service.list_projects()

@router.get("/projects/{project_id}", summary="获取指定项目详情")
async def get_project(project_id: str):
    project = project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    messages = db.get_messages(project_id)
    return {
        "project": project,
        "messages": messages,
    }

@router.post("/projects/{project_id}/messages", summary="发送用户消息并更新意图分析")
async def send_message(project_id: str, req: SendMessageRequest):
    try:
        q_resp = await project_service.analyze_input(project_id, new_user_text=req.content)
        return q_resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.get("/projects/{project_id}/questions", summary="获取当前待回答的问题")
async def get_questions(project_id: str):
    try:
        return project_service.get_questions(project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/projects/{project_id}/answers", summary="提交问题答案并进入下一轮或简报确认")
async def submit_answers(project_id: str, req: SubmitAnswersRequest):
    try:
        answers_dicts = [a.model_dump() for a in req.answers]
        q_resp = await project_service.answer_questions(project_id, answers_dicts, req.use_defaults)
        return q_resp
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.patch("/projects/{project_id}/brief", summary="局部修改创作简报")
async def update_brief(project_id: str, req: UpdateBriefRequest):
    try:
        updated = project_service.update_brief(project_id, req.updates)
        return updated
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/projects/{project_id}/brief/confirm", summary="确认剧情拆解并进入导演模板选择")
async def confirm_brief(project_id: str, brief_data: Optional[dict[str, Any]] = None):
    try:
        brief = await project_service.confirm_brief(project_id, brief_data)
        return {
            "status": "success",
            "message": "简报已确认，请选择导演模板和方案",
            "brief": brief,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# 10.2 Screenplay & Shots
@router.get("/production-packs", summary="获取导演语法与生成方案模板")
async def list_production_packs():
    return production_pack_registry.list()

@router.get("/auteur-profiles", summary="获取名导技法档案及代表作模式")
async def list_auteur_profiles():
    return auteur_profile_registry.list()

@router.put("/projects/{project_id}/auteur-profile", summary="为项目选择名导技法模式")
async def apply_auteur_profile(project_id: str, req: ApplyAuteurProfileRequest):
    try:
        return project_service.apply_auteur_profile(
            project_id,
            req.profile_id,
            req.variant_id,
            req.intensity,
            req.preserve,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/auteur-profile", summary="获取项目当前名导技法模式")
async def get_auteur_profile(project_id: str):
    context = project_service.get_auteur_context(project_id)
    if not context:
        raise HTTPException(status_code=404, detail="Auteur profile not selected")
    return context

@router.delete("/projects/{project_id}/auteur-profile", summary="移除项目名导技法模式")
async def clear_auteur_profile(project_id: str):
    try:
        project_service.clear_auteur_profile(project_id)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/projects/{project_id}/treatments/generate", summary="生成可选择的导演方案")
async def generate_treatments(project_id: str):
    try:
        return await project_service.generate_treatments(project_id)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/treatments", summary="获取当前导演方案")
async def get_treatments(project_id: str):
    package = project_service.get_treatments(project_id)
    if not package:
        raise HTTPException(status_code=404, detail="Treatments not found")
    return package

@router.post("/projects/{project_id}/treatments/{treatment_id}/confirm", summary="确认导演方案，准备生成制作流程")
async def confirm_treatment(project_id: str, treatment_id: str, req: ConfirmTreatmentRequest):
    try:
        selected = await project_service.confirm_treatment(project_id, treatment_id, req.production_pack_id)
        return {"status": "success", "selected_treatment": selected}
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/projects/{project_id}/screenplay/generate", summary="生成/重新生成剧本与场景")
async def generate_screenplay(project_id: str):
    try:
        pkg = await project_service.generate_screenplay(project_id)
        return pkg
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/screenplay", summary="获取当前剧本与场景设定")
async def get_screenplay(project_id: str):
    data = project_service.get_screenplay(project_id)
    if not data:
        raise HTTPException(status_code=404, detail="Screenplay not found")
    return data

@router.post("/projects/{project_id}/shots/generate", summary="生成分镜镜头表")
async def generate_shots(project_id: str):
    try:
        shots = await project_service.generate_shots(project_id)
        return shots
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/shots", summary="获取镜头表及连续性校验报告")
async def get_shots(project_id: str):
    shots = project_service.get_shots(project_id)
    cont_art = db.get_latest_artifact(project_id, "continuity_report")
    grammar_art = db.get_latest_artifact(project_id, "grammar_report")
    auteur_art = db.get_latest_artifact(project_id, "auteur_report")
    return {
        "shots": shots,
        "continuity_issues": cont_art["content"] if cont_art else [],
        "grammar_issues": grammar_art["content"] if grammar_art else [],
        "auteur_issues": auteur_art["content"] if auteur_art else [],
        "total_duration": sum(s.get("duration_seconds", 0) for s in shots),
    }

@router.patch("/projects/{project_id}/shots/{shot_id}", summary="局部编辑镜头")
async def update_shot(project_id: str, shot_id: str, req: UpdateShotRequest):
    try:
        shot = project_service.update_shot(project_id, shot_id, req.updates)
        return shot
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/projects/{project_id}/shots/confirm", summary="确认镜头表并编译生成包与工作流")
async def confirm_shots(project_id: str):
    try:
        res = await project_service.confirm_shots(project_id)
        return {
            "status": "success",
            "message": "镜头表已确认，Prompt包和工作流JSON已编译就绪",
            "shots": res,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# 10.3 Prompt Packages & Workflows
@router.post("/projects/{project_id}/packages/generate", summary="编译提示词包与注入工作流")
async def compile_packages(project_id: str):
    try:
        packages = await project_service.compile_packages(project_id)
        return packages
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/packages", summary="获取编译后的提示词包与工作流规划")
async def get_packages(project_id: str):
    data = project_service.get_packages(project_id)
    return data

@router.get("/workflows", summary="获取已注册的所有 ComfyUI 工作流模板")
async def list_workflows():
    return list(workflow_registry.profiles.values())

@router.get("/projects/{project_id}/workflow/{shot_id}", summary="下载指定镜头的 patched workflow JSON")
async def download_patched_workflow(project_id: str, shot_id: str, format: Literal["api", "ui"] = "api"):
    if not SHOT_ID_RE.fullmatch(shot_id):
        raise HTTPException(status_code=400, detail="Invalid shot ID")
    plans = project_service.get_packages(project_id)["workflow_plans"]
    if not any(plan.get("shot_id") == shot_id and plan.get("status") == "matched" for plan in plans):
        raise HTTPException(status_code=404, detail="Active patched workflow not found")
    file_path = project_file(project_id, "patched_workflows", f"{shot_id}_workflow.json")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Patched workflow not found")
    if format == "ui":
        import json
        plan = next(p for p in plans if p["shot_id"] == shot_id)
        try:
            graph = ui_workflow(workflow_registry, plan["workflow_id"], json.loads(file_path.read_text()))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if graph is None:
            raise HTTPException(status_code=404, detail="此旧模板只有 API 格式")
        return Response(json.dumps(graph, ensure_ascii=False), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{shot_id}_ui.json"'})
    return FileResponse(path=str(file_path), filename=f"{shot_id}_api.json", media_type="application/json")

@router.get("/projects/{project_id}/delivery", summary="检查工作流交付包与素材依赖")
async def get_delivery(project_id: str):
    try:
        return delivery_snapshot(project_service, project_id)[0]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/export", summary="下载完整 ComfyUI 制作包 ZIP")
async def export_project(project_id: str):
    project_file(project_id)
    try:
        data = build_archive(project_service, project_id)
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{project_id}_comfyui.zip"', "Cache-Control": "no-store"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# Render & Execution
@router.post("/projects/{project_id}/auto_pipeline", summary="后台生成剧本、分镜、提示词和工作流（不渲染）")
async def auto_pipeline(project_id: str):
    try:
        return project_service.start_auto_pipeline(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/auto_pipeline", summary="查询生成集编排状态（步骤日志 + 每镜头渲染状态）")
async def get_pipeline_status(project_id: str):
    try:
        return project_service.get_pipeline_status(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/shots/{shot_id}/render", summary="执行单个镜头渲染 (ComfyUI / 仿真)")
async def render_shot(shot_id: str, req: RenderShotRequest):
    try:
        run = await project_service.render_shot(req.project_id, shot_id)
        return run
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/projects/{project_id}/render_all", summary="批量执行所有镜头渲染")
async def render_all_shots(project_id: str):
    try:
        runs = await project_service.render_all_shots(project_id)
        return runs
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/renders/{render_id}", summary="查询渲染运行状态")
async def get_render_run(render_id: str):
    run = db.get_render_run(render_id)
    if not run:
        raise HTTPException(status_code=404, detail="Render run not found")
    return run

@router.post("/projects/{project_id}/rough_cut", summary="调用 FFmpeg 合成粗剪短片")
async def create_rough_cut(project_id: str):
    try:
        rough_cut_file = await project_service.create_rough_cut(project_id)
        return {
            "status": "success",
            "message": "粗剪短片合成完毕",
            "file_path": rough_cut_file,
            "download_url": f"/api/projects/{project_id}/rough_cut/download",
        }
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/projects/{project_id}/outputs/{filename}", summary="读取项目生成素材")
async def get_output(project_id: str, filename: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", filename):
        raise HTTPException(status_code=400, detail="Invalid output filename")
    file_path = project_file(project_id, "outputs", filename)
    if filename == "rough_cut.mp4" and not db.get_latest_artifact(project_id, "rough_cut"):
        raise HTTPException(status_code=404, detail="Current rough cut not found")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Output not found")
    media_types = {".mp4": "video/mp4", ".webm": "video/webm", ".png": "image/png", ".jpg": "image/jpeg"}
    media_type = media_types.get(file_path.suffix.lower())
    if not media_type:
        raise HTTPException(status_code=400, detail="Unsupported output type")
    return FileResponse(path=str(file_path), filename=filename, media_type=media_type)

@router.get("/projects/{project_id}/rough_cut/download", summary="下载粗剪短片 MP4")
async def download_rough_cut(project_id: str):
    rough_cut_file = project_file(project_id, "outputs", "rough_cut.mp4")
    if not db.get_latest_artifact(project_id, "rough_cut") or not rough_cut_file.exists():
        raise HTTPException(status_code=404, detail="Rough cut video not found")
    return FileResponse(path=str(rough_cut_file), filename=f"{project_id}_rough_cut.mp4", media_type="video/mp4")
