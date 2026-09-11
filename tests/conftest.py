import os
import atexit
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("LLM_MOCK_MODE", "true")
os.environ.setdefault("COMFYUI_MOCK_MODE", "true")

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="movie-agent-tests-"))
os.environ.setdefault("DATA_DIR", str(TEST_DATA_DIR))
os.environ.setdefault("SQLITE_DB_PATH", str(TEST_DATA_DIR / "movie_agent.db"))
atexit.register(shutil.rmtree, TEST_DATA_DIR, ignore_errors=True)
