from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from server.api import router
from server.config import settings
from server.db import init_db
from agent.workflow import workflow_registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.workflows_dir.mkdir(parents=True, exist_ok=True)
    settings.prompts_dir.mkdir(parents=True, exist_ok=True)
    settings.web_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    workflow_registry.load_all()
    yield

app = FastAPI(
    title="Movie Agent - AI Film Production System",
    description="从一句话创意到分镜表与 ComfyUI 工作流参数包的电影 Agent 系统",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Mount outputs/media directory
settings.data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(settings.data_dir)), name="media")

# Mount web frontend files
settings.web_dir.mkdir(parents=True, exist_ok=True)
app.mount("/web", StaticFiles(directory=str(settings.web_dir)), name="web")
app.mount("/static", StaticFiles(directory=str(settings.web_dir)), name="static")

@app.get("/")
async def root():
    index_file = settings.web_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Movie Agent API is running. Please access /docs for API documentation."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
