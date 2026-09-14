from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from agent.execution import ProjectBusy, NeedsClarification, QualityFailed, SubmissionUncertain
from pydantic import ValidationError
from starlette.types import Scope

from server.api import router
from server.config import settings


class ImmutableStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

app = FastAPI(
    title="Movie Agent - AI Film Production System",
    description="从一句话创意到分镜表与 ComfyUI 工作流参数包的电影 Agent 系统",
    version="0.2.0",
)

@app.middleware("http")
async def record_human_actions(request, call_next):
    response = await call_next(request)
    import re
    from server.db import db
    match = re.fullmatch(r"/api/projects/(prj_[0-9a-f]{8})/(.+)", request.url.path)
    if match and request.method in ("POST", "PUT", "PATCH") and response.status_code < 300:
        operation = match[2]
        if operation in ("constraints", "timeline", "quality/repair") or operation.endswith("/confirm") or request.method == "PATCH":
            db.save_artifact(match[1], "human_intervention", {"operation": operation, "method": request.method})
    return response


@app.exception_handler(ProjectBusy)
async def busy_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(SubmissionUncertain)
async def uncertain_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": str(exc), "status": "interrupted"})


@app.exception_handler(RuntimeError)
async def runtime_handler(request, exc):
    return JSONResponse(status_code=502, content={"detail": str(exc)[:2000] or type(exc).__name__})


@app.exception_handler(ValueError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)[:3000]})


# Include API routes
app.include_router(router)

# Static frontend: prefer the Vite build output, fall back to web/ root
settings.web_dir.mkdir(parents=True, exist_ok=True)
dist_dir = settings.web_dir / "dist"
static_root = dist_dir if dist_dir.is_dir() else settings.web_dir

assets_dir = static_root / "assets"
if assets_dir.is_dir():
    app.mount("/assets", ImmutableStaticFiles(directory=str(assets_dir)), name="assets")

if not dist_dir.is_dir():
    legacy_dir = settings.web_dir / "legacy"
    if legacy_dir.is_dir():
        app.mount("/static/legacy", StaticFiles(directory=str(legacy_dir)), name="legacy")


@app.get("/")
@app.get("/studio")
async def root():
    index_file = static_root / "index.html"
    if index_file.exists():
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
    return {"message": "Movie Agent API is running. Please access /docs for API documentation."}
