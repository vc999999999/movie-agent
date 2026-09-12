from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
    title="幕间 - AI Film Production System",
    description="从一句话创意到分镜表与 ComfyUI 工作流参数包的幕间 系统",
    version="0.2.0",
)

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
    return {"message": "幕间 API is running. Please access /docs for API documentation."}
