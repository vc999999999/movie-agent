from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    deployment_revision: str = "local"

    # LLM Settings
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    llm_mock_mode: bool = False

    # ComfyUI Settings
    comfyui_host: str = "127.0.0.1"
    comfyui_port: int = 8188
    comfyui_mock_mode: bool = False
    comfyui_vram_gb: int = 24

    # Cloud generation backend (ModelScope API-Inference)
    # "comfyui" (default) or "modelscope"
    render_backend: str = "comfyui"
    modelscope_api_key: str = ""

    # Paths
    data_dir: Path = BASE_DIR / "projects"
    workflows_dir: Path = BASE_DIR / "workflows"
    production_packs_dir: Path = BASE_DIR / "production_packs"
    auteur_profiles_dir: Path = BASE_DIR / "auteur_profiles"
    prompts_dir: Path = BASE_DIR / "prompts"
    web_dir: Path = BASE_DIR / "web"
    sqlite_db_path: Path = BASE_DIR / "projects" / "movie_agent.db"

    # Agent Limits
    max_question_rounds: int = 3
    max_questions_per_round: int = 3

settings = Settings()
