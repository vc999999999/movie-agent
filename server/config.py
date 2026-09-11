from __future__ import annotations

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM Settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o")

    # ComfyUI Settings
    comfyui_host: str = os.getenv("COMFYUI_HOST", "127.0.0.1")
    comfyui_port: int = int(os.getenv("COMFYUI_PORT", "8188"))
    comfyui_mock_mode: bool = os.getenv("COMFYUI_MOCK_MODE", "false").lower() in ("true", "1", "yes")

    # Paths
    base_dir: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "projects"
    workflows_dir: Path = BASE_DIR / "workflows"
    prompts_dir: Path = BASE_DIR / "prompts"
    web_dir: Path = BASE_DIR / "web"
    sqlite_db_path: Path = BASE_DIR / "projects" / "movie_agent.db"

    # Agent Limits
    max_question_rounds: int = 3
    max_questions_per_round: int = 3
    default_fps: int = 24

    @property
    def comfyui_http_url(self) -> str:
        return f"http://{self.comfyui_host}:{self.comfyui_port}"

    @property
    def comfyui_ws_url(self) -> str:
        return f"ws://{self.comfyui_host}:{self.comfyui_port}/ws"

settings = Settings()
