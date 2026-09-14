"""Run fixed ablations; all outputs stay in an isolated evaluation directory."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true", help="Use the currently configured services (may incur their normal costs)")
    parser.add_argument("--output", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--reference", type=Path, help="Existing PNG/JPEG used as an explicit default reference")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    folder = args.output.resolve() / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    os.environ["DATA_DIR"] = str(folder / "projects")
    os.environ["SQLITE_DB_PATH"] = str(folder / "projects" / "evaluation.db")
    if not args.real:
        os.environ["LLM_MOCK_MODE"] = "true"
        os.environ["COMFYUI_MOCK_MODE"] = "true"
        os.environ["RENDER_BACKEND"] = "comfyui"
    else:
        os.environ["LLM_MOCK_MODE"] = "false"
        os.environ["COMFYUI_MOCK_MODE"] = "false"
    asyncio.run(evaluate(args, folder))


async def evaluate(args, folder):
    from agent.service import ProjectService
    from agent.media import AssetMetadata, command
    from server.config import settings
    import hashlib, sys
    from importlib.metadata import version
    environment = {"python": sys.version, "packages": {name: version(name) for name in ("pydantic", "fastapi", "httpx", "pyyaml")},
                   "source_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for folder_name in ("agent", "server", "prompts") for path in sorted(Path(folder_name).iterdir()) if path.suffix in (".py", ".md")}}
    cases = json.loads((Path(__file__).parent / "cases.json").read_text())[:args.limit]
    reference = args.reference
    if not args.real and reference is None:
        reference = folder / "synthetic-reference.png"
        await command("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:size=64x64", "-frames:v", "1", str(reference))
    rows = []
    for case in cases:
        for mode in ("baseline", "rules", "full"):
            service = ProjectService()
            pid = service.create_project(case["idea"])["id"]
            if reference:
                await service.register_asset(pid, reference.read_bytes(), AssetMetadata(purpose="reference", project_default=True,
                    source="User supplied evaluation reference" if args.real else "Explicit synthetic test reference", rights="pending"))
            try:
                await service.run_auto_pipeline(pid, evaluation_mode=mode)
            except Exception as exc:
                print(f"{case['id']} / {mode}: {type(exc).__name__}: {str(exc)[:150]}", flush=True)
            report = service.evidence_report(pid)
            actual = report["pipeline"]["status"]
            row = {"case": case["id"], "mode": mode, "expected": case["expected"], "actual": actual,
                   "expected_behavior": actual == case["expected"], **report["metrics"]}
            rows.append(row)
            (folder / f"{case['id']}-{mode}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"{case['id']} / {mode}: {actual}", flush=True)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    summary = {"environment": environment, "simulation": not args.real, "git_revision": revision, "model": settings.openai_model,
               "backend": settings.render_backend, "rows": rows, "actual_cost": None,
               "manual_quality": "待人工盲评", "reference_supplied": bool(reference),
               "note": "baseline 保留安全与结构检查；rules 增加电影语法及硬约束验收；full 增加 LLM 内容质检和最多两轮修正。每个项目使用独立固定镜头种子，比较包含生成随机性。"}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    lines = ["# 固定输入消融评测", "", f"运行模式：{'仿真' if not args.real else '真实服务'}。不代表艺术质量评分。", "",
             "| 组别 | 样本 | 成片数 | 预期行为符合数 |", "| --- | --- | --- | --- |"]
    for mode in ("baseline", "rules", "full"):
        selected = [r for r in rows if r["mode"] == mode]
        lines.append(f"| {mode} | {len(selected)} | {sum(r['completed'] for r in selected)} | {sum(r['expected_behavior'] for r in selected)} |")
    lines += ["", "真实成本未提供；画面、叙事和声音盲评待验收。完整失败原因见 JSON。", "", summary["note"]]
    (folder / "summary.md").write_text("\n".join(lines))
    print(f"Report: {folder / 'summary.md'}", flush=True)


if __name__ == "__main__":
    main()
