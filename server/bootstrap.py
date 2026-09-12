"""Prepare Studio's persistent storage, then run the complete application."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import pwd
import zlib


def prepare_storage() -> None:
    """The platform mount can mask image-time permissions; fix our own folder only."""
    root = Path(os.environ.get("DATA_DIR", "/mnt/workspace/movie-agent"))
    database = Path(os.environ.get("SQLITE_DB_PATH", str(root / "movie_agent.db")))
    root.mkdir(parents=True, exist_ok=True)
    database.parent.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        account = pwd.getpwnam("movie-agent")
        os.chown(root, account.pw_uid, account.pw_gid)
        os.chown(database.parent, account.pw_uid, account.pw_gid)
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    probe = root / ".write-check"
    probe.write_text("ok")
    probe.unlink()


def restore_backup() -> None:
    """Optional one-time migration via a Studio secret, never via a public route."""
    encoded = os.environ.pop("PROJECT_MIGRATION_B64", "")
    if not encoded:
        return
    backup = json.loads(zlib.decompress(base64.b64decode(encoded)))
    if backup.get("version") != 1:
        raise ValueError("Unsupported project migration version")
    from server.db import db
    from agent.models import CreativeBrief, sanitize_brief_dict
    imported = 0
    for entry in backup["projects"]:
        project = entry["project"]
        pid = project["id"]
        # Never overwrite an already migrated or newly edited project.
        if db.get_project(pid):
            continue
        db.create_project(pid, project.get("title"), project.get("source_text", ""), project.get("brief", {}))
        for message in (entry.get("detail") or {}).get("messages", []):
            db.add_message(pid, message["role"], message["content"])
        brief = project.get("brief", {})
        if brief:
            db.save_artifact(pid, "creative_brief", brief, status="draft")
        if entry.get("questions"):
            db.save_artifact(pid, "questions", entry["questions"], status="current")
        if entry.get("auteur-profile"):
            db.save_artifact(pid, "auteur_profile", entry["auteur-profile"], status="confirmed")
        if entry.get("treatments"):
            db.save_artifact(pid, "treatments", entry["treatments"], status="draft")
        screenplay = entry.get("screenplay")
        if screenplay:
            db.save_artifact(pid, "project_bible", screenplay["project_bible"], status="confirmed")
            db.save_artifact(pid, "screenplay", screenplay["scenes"], status="confirmed")
        shots = entry.get("shots") or {}
        if shots.get("shots"):
            db.save_artifact(pid, "shot_list", shots["shots"], status="draft")
            for key, kind in [("continuity_issues", "continuity_report"), ("grammar_issues", "grammar_report"), ("auteur_issues", "auteur_report")]:
                db.save_artifact(pid, kind, shots.get(key, []), status="draft")
        # Do not restore server-specific absolute workflow paths. Recompile on demand.
        status = "shots_review" if shots.get("shots") else "treatment_review" if entry.get("treatments") else "brief_review" if brief else "collecting"
        if status == "brief_review":
            try:
                CreativeBrief(**sanitize_brief_dict(brief))
            except ValueError:
                status = "collecting"
        db.update_project_status(pid, status)
        with db._conn() as conn:
            conn.execute("UPDATE projects SET round_count=?, created_at=? WHERE id=?", (project.get("round_count", 0), project.get("created_at", ""), pid))
        imported += 1
    print(f"Persistent storage ready; migrated {imported} existing project(s).", flush=True)


if __name__ == "__main__":
    prepare_storage()
    restore_backup()
    os.execvp("uvicorn", ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "7860"])
