from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from server.config import settings

def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or settings.sqlite_db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def init_db(db_path: Optional[Path] = None) -> None:
    conn = get_db_connection(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            title TEXT,
            source_text TEXT,
            brief_json TEXT,
            round_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            version INTEGER NOT NULL,
            content_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS render_runs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            shot_id TEXT NOT NULL,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            request_json TEXT NOT NULL,
            prompt_id TEXT,
            output_json TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_artifacts_version
            ON artifacts(project_id, kind, version);
        CREATE INDEX IF NOT EXISTS idx_messages_project_created
            ON messages(project_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_render_runs_project_created
            ON render_runs(project_id, created_at);
        """)
        conn.execute("PRAGMA journal_mode = WAL")
    conn.close()

# Database helper functions
class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.sqlite_db_path
        init_db(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    # Projects
    def create_project(self, project_id: str, title: Optional[str], source_text: str, brief_dict: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        now = utc_now()
        brief_json = json.dumps(brief_dict, ensure_ascii=False) if brief_dict else "{}"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, status, title, source_text, brief_json, round_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, "collecting", title or "新项目", source_text, brief_json, 0, now, now)
            )
        return self.get_project(project_id)  # type: ignore

    def get_project(self, project_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            if res.get("brief_json"):
                res["brief"] = json.loads(res["brief_json"])
            else:
                res["brief"] = {}
            res.pop("brief_json", None)
            return res

    def update_project_status(self, project_id: str, status: str) -> None:
        now = utc_now()
        with self._conn() as conn:
            conn.execute("UPDATE projects SET status = ?, updated_at = ? WHERE id = ?", (status, now, project_id))

    def update_project_brief(self, project_id: str, brief_dict: dict[str, Any], title: Optional[str] = None) -> None:
        now = utc_now()
        brief_json = json.dumps(brief_dict, ensure_ascii=False)
        with self._conn() as conn:
            if title:
                conn.execute("UPDATE projects SET brief_json = ?, title = ?, updated_at = ? WHERE id = ?", (brief_json, title, now, project_id))
            else:
                conn.execute("UPDATE projects SET brief_json = ?, updated_at = ? WHERE id = ?", (brief_json, now, project_id))

    def append_project_source(self, project_id: str, text: str) -> str:
        now = utc_now()
        with self._conn() as conn:
            row = conn.execute("SELECT source_text FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not row:
                raise ValueError(f"Project {project_id} not found")
            source_text = f"{row['source_text']}\n{text}" if row["source_text"] else text
            conn.execute(
                "UPDATE projects SET source_text = ?, updated_at = ? WHERE id = ?",
                (source_text, now, project_id),
            )
            return source_text

    def increment_project_round(self, project_id: str) -> int:
        now = utc_now()
        with self._conn() as conn:
            conn.execute("UPDATE projects SET round_count = round_count + 1, updated_at = ? WHERE id = ?", (now, project_id))
            row = conn.execute("SELECT round_count FROM projects WHERE id = ?", (project_id,)).fetchone()
            return row["round_count"] if row else 1

    def list_projects(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
            result = []
            for r in rows:
                item = dict(r)
                item["brief"] = json.loads(item["brief_json"]) if item.get("brief_json") else {}
                item.pop("brief_json", None)
                result.append(item)
            return result

    # Messages
    def add_message(self, project_id: str, role: str, content: str) -> str:
        msg_id = f"msg_{uuid.uuid4().hex[:8]}"
        now = utc_now()
        with self._conn() as conn:
            conn.execute("INSERT INTO messages (id, project_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                         (msg_id, project_id, role, content, now))
        return msg_id

    def get_messages(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE project_id = ? ORDER BY created_at ASC", (project_id,)).fetchall()
            return [dict(r) for r in rows]

    # Artifacts
    def save_artifact(self, project_id: str, kind: str, content: dict[str, Any] | list[Any], status: str = "draft") -> int:
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT MAX(version) as max_v FROM artifacts WHERE project_id = ? AND kind = ?", (project_id, kind)).fetchone()
            next_v = (row["max_v"] or 0) + 1
            art_id = f"art_{kind}_{next_v}_{uuid.uuid4().hex[:6]}"
            now = utc_now()
            content_json = json.dumps(content, ensure_ascii=False)
            conn.execute(
                "INSERT INTO artifacts (id, project_id, kind, version, content_json, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (art_id, project_id, kind, next_v, content_json, status, now)
            )
            return next_v

    def get_latest_artifact(self, project_id: str, kind: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE project_id = ? AND kind = ? AND status != 'stale' ORDER BY version DESC LIMIT 1",
                (project_id, kind)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["content"] = json.loads(res["content_json"])
            return res

    def invalidate_artifacts(self, project_id: str, kinds: list[str]) -> None:
        if not kinds:
            return
        placeholders = ",".join("?" for _ in kinds)
        with self._conn() as conn:
            conn.execute(
                f"UPDATE artifacts SET status = 'stale' WHERE project_id = ? AND kind IN ({placeholders})",
                [project_id, *kinds],
            )

    # Render runs
    def create_render_run(self, run: dict[str, Any]) -> str:
        created_at = run.get("created_at") or utc_now()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO render_runs (id, project_id, shot_id, workflow_id, status, request_json, prompt_id, output_json, error_json, created_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run["id"], run["project_id"], run["shot_id"], run["workflow_id"],
                    run["status"], json.dumps(run.get("request_json", {}), ensure_ascii=False),
                    run.get("prompt_id"),
                    json.dumps(run.get("output_json"), ensure_ascii=False) if run.get("output_json") else None,
                    json.dumps(run.get("error_json"), ensure_ascii=False) if run.get("error_json") else None,
                    created_at, run.get("finished_at")
                )
            )
        return run["id"]

    def update_render_run(self, run_id: str, status: str, prompt_id: Optional[str] = None, output_json: Optional[dict[str, Any]] = None, error_json: Optional[dict[str, Any]] = None) -> None:
        now = utc_now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE render_runs SET status = ?, prompt_id = COALESCE(?, prompt_id),
                   output_json = COALESCE(?, output_json), error_json = COALESCE(?, error_json),
                   finished_at = CASE WHEN ? IN ('success', 'failed') THEN ? ELSE finished_at END
                   WHERE id = ?""",
                (
                    status, prompt_id,
                    json.dumps(output_json, ensure_ascii=False) if output_json else None,
                    json.dumps(error_json, ensure_ascii=False) if error_json else None,
                    status, now, run_id
                )
            )

    def get_render_run(self, run_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM render_runs WHERE id = ?", (run_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["request_json"] = json.loads(res["request_json"]) if res.get("request_json") else {}
            res["output_json"] = json.loads(res["output_json"]) if res.get("output_json") else None
            res["error_json"] = json.loads(res["error_json"]) if res.get("error_json") else None
            return res

    def get_latest_successful_render(self, project_id: str, shot_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM render_runs
                   WHERE project_id = ? AND shot_id = ? AND status = 'success'
                   ORDER BY finished_at DESC LIMIT 1""",
                (project_id, shot_id),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["request_json"] = json.loads(result["request_json"])
            result["output_json"] = json.loads(result["output_json"]) if result.get("output_json") else None
            result["error_json"] = json.loads(result["error_json"]) if result.get("error_json") else None
            return result

db = Database()
