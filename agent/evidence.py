"""Export measured execution evidence without inventing quality scores or costs."""
from __future__ import annotations

import json
from pathlib import Path
import zipfile
import uuid

from agent.execution import exclusive
from agent.media import digest, probe
from server.config import settings


def report_markdown(report: dict) -> str:
    metrics = report["metrics"]
    return (f"# Movie Agent 运行证据\n\n项目：{report['project_id']}\n\n"
            f"模式：{'仿真' if report['simulation'] else '真实生成'}\n\n"
            f"状态：{report['pipeline'].get('status', 'idle')}\n\n"
            f"| 指标 | 结果 |\n| --- | --- |\n" + "".join(f"| {k} | {v if v is not None else '未提供'} |\n" for k, v in metrics.items()) +
            "\n## 验证边界\n\n文本质检不等于画面质检；画面一致性、叙事观感和声音效果需要人工盲评。真实成本无数据时留空。\n")


class EvidenceProduction:
    def evidence_report(self, project_id: str) -> dict:
        project = self.db.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        pipeline = self.get_pipeline_status(project_id)["pipeline"]
        runs = self.db.list_render_runs(project_id)
        latest = {}
        for run in runs:
            latest.setdefault(run["shot_id"], run)
        shots = self.get_shots(project_id)
        quality = self.db.get_latest_artifact(project_id, "quality_review")
        cut = self.db.get_latest_artifact(project_id, "rough_cut")
        meter = pipeline.get("metrics", {})
        errors = self.hard_constraint_errors(project_id) if project.get("brief") else ["简报未完成"]
        return {"project_id": project_id, "idea": project["source_text"], "simulation": settings.llm_mock_mode or (settings.render_backend == "comfyui" and self.comfyui.mock_mode),
                "pipeline": pipeline, "constraints": self.constraints(project_id), "constraint_errors": errors,
                "quality": quality["content"] if quality else None, "handoffs": self.db.list_artifacts(project_id, "handoff"),
                "revisions": self.db.list_artifacts(project_id, "revision"), "visual_feedback": self.db.list_artifacts(project_id, "visual_feedback"),
                "metrics": {"completed": bool(cut) and pipeline.get("status") == "completed", "shots": len(shots),
                            "successful_shots": sum(latest.get(s["shot_id"], {}).get("status") == "success" for s in shots),
                            "constraints_passed": not errors, "elapsed_seconds": pipeline.get("elapsed_seconds"),
                            "repair_count": len(self.db.list_artifacts(project_id, "revision")),
                            "human_interventions": len(self.db.list_artifacts(project_id, "human_intervention")) + len(self.db.list_artifacts(project_id, "visual_feedback")),
                            "render_attempts": len(runs), "llm_calls": meter.get("llm_calls"),
                            "input_tokens": meter.get("input_tokens") if meter.get("usage_available") else None,
                            "output_tokens": meter.get("output_tokens") if meter.get("usage_available") else None,
                            "actual_cost": None, "failure_reason": pipeline.get("error")},
                "manual_review": {"narrative": "待验收", "visual_consistency": "待验收", "sound": "待验收"}}

    @exclusive
    async def export_evidence(self, project_id: str, *, competition: bool = False) -> Path:
        report = self.evidence_report(project_id)
        artifact = self.db.get_latest_artifact(project_id, "rough_cut")
        cut = artifact["content"] if artifact else None
        used = set(cut.get("used_asset_ids", [])) if cut else set()
        assets = [a for a in self.assets(project_id) if a["id"] in used]
        if competition:
            if not cut or report["simulation"]:
                raise ValueError("参赛导出需要真实成片；仿真仅可导出预览证据")
            if used - {a["id"] for a in assets} or any(a["rights"] != "confirmed" for a in assets):
                raise ValueError("使用素材存在待审来源或授权")
            if cut.get("missing_voice_shots"):
                raise ValueError("对白或旁白配音尚未补齐")
            if not report["quality"] or not report["quality"]["passed"] or report["constraint_errors"]:
                raise ValueError("当前文本质量或硬约束尚未验收通过")
        path = settings.data_dir / project_id / "outputs" / f"evidence_{uuid.uuid4().hex[:10]}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        if cut:
            movie = self._project_file(project_id, cut["file_path"])
            if digest(movie) != cut["sha256"]:
                raise ValueError("成片文件已改变")
            await probe(movie)
        manifest = [{k: v for k, v in a.items() if k not in ("file_path", "media")} for a in assets]
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
            bundle.writestr("report.md", report_markdown(report))
            bundle.writestr("assets.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            bundle.writestr("generation-declaration.txt", "本作品包含 AI 生成内容。素材来源及权利声明由提交者提供，系统记录不构成法律授权证明。\n")
            bundle.writestr("timeline.json", json.dumps(self.timeline(project_id), ensure_ascii=False, indent=2))
            comparison = self.db.get_latest_artifact(project_id, "comparison_frames")
            if comparison:
                bundle.writestr("comparison.json", json.dumps(comparison["content"], ensure_ascii=False, indent=2))
                for item in comparison["content"]:
                    for filename in item["frames"]:
                        image = self._project_file(project_id, "outputs/" + filename)
                        if image.is_file():
                            bundle.write(image, "comparison/" + image.name)
            if cut:
                bundle.write(movie, "movie.mp4")
            for asset in assets:
                source = self.asset_file(project_id, asset["id"])
                bundle.write(source, "assets/" + source.name)
        return path
