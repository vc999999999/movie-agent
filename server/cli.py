from __future__ import annotations

import argparse
import asyncio

from server.db import init_db
from agent.service import project_service
from agent.workflow import workflow_registry

async def run_cli():
    parser = argparse.ArgumentParser(description="Movie Agent CLI - AI Film Production Agent")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: create
    create_parser = subparsers.add_parser("create", help="Create a new movie project from an idea")
    create_parser.add_argument("--idea", type=str, required=True, help="User idea or script")
    create_parser.add_argument("--title", type=str, default=None, help="Project title")
    create_parser.add_argument("--auto", action="store_true", help="Automatically confirm defaults and generate end-to-end")

    # Command: list
    subparsers.add_parser("list", help="List all projects")

    # Command: info
    info_parser = subparsers.add_parser("info", help="Get project details")
    info_parser.add_argument("--id", type=str, required=True, help="Project ID")

    # Command: render
    render_parser = subparsers.add_parser("render", help="Render all shots in a project")
    render_parser.add_argument("--id", type=str, required=True, help="Project ID")

    # Command: rough-cut
    cut_parser = subparsers.add_parser("rough-cut", help="Stitch shots into unified MP4 video with FFmpeg")
    cut_parser.add_argument("--id", type=str, required=True, help="Project ID")

    # Command: workflows
    subparsers.add_parser("workflows", help="List available ComfyUI workflow templates")

    args = parser.parse_args()
    init_db()
    workflow_registry.load_all()

    if args.command == "create":
        print(f"\n🎬 正在创建电影 Agent 项目...")
        project = project_service.create_project(args.idea, args.title)
        pid = project["id"]
        print(f"✅ 项目已创建! ID: {pid}")

        # Step 1: Initial analysis
        print("🔍 正在分析创意并提炼创作要素...")
        q_resp = await project_service.analyze_input(pid)

        if args.auto or q_resp.status == "brief_review":
            print("⚡ 自动模式：确认创作简报...")
            await project_service.confirm_brief(pid)
            print("✅ 剧本与分镜镜头表已生成!")

            print("📦 正在确认镜头并编译 Prompt 包及注入 ComfyUI 工作流...")
            await project_service.confirm_shots(pid)
            print("✅ 提示词包与工作流生成完毕!")

            packages = project_service.get_packages(pid)
            print("\n" + "="*50)
            print(packages["production_report"])
            print("="*50)
            print(f"\n🎉 项目 {pid} 准备就绪！可运行 `python -m app.cli render --id {pid}` 执行生成。")
        else:
            print(f"\n❓ 当前需要澄清的问题 (轮次 {q_resp.round}/3):")
            for q in q_resp.questions:
                print(f"  • [{q.field}] {q.text}")
                print(f"    可选选项: {', '.join(q.choices)}")
            print(f"\n提示：可在 Web 端查看并交互，或使用 `--auto` 参数自动采用最佳设定。")

    elif args.command == "list":
        projects = project_service.list_projects()
        print(f"\n📋 项目列表 ({len(projects)} 个):")
        for p in projects:
            print(f"  • [{p['id']}] {p.get('title', '无标题')} (状态: {p['status']}) - {p['created_at']}")

    elif args.command == "info":
        project = project_service.get_project(args.id)
        if not project:
            print(f"❌ 找不到项目 {args.id}")
            return
        print(f"\n🎬 项目: {project.get('title')} ({project['id']})")
        print(f"状态: {project['status']}")
        print(f"原始创意: {project.get('source_text')}")
        packages = project_service.get_packages(args.id)
        if packages.get("production_report"):
            print("\n" + packages["production_report"])

    elif args.command == "render":
        print(f"\n🚀 开始执行项目 {args.id} 的所有镜头渲染...")
        runs = await project_service.render_all_shots(args.id)
        for r in runs:
            print(f"  • 镜头 {r.shot_id}: 状态 {r.status} (Run: {r.id})")
        print(f"✅ 渲染执行完毕！")

    elif args.command == "rough-cut":
        print(f"\n🎞️ 正在调用 FFmpeg 合成项目 {args.id} 的粗剪短片...")
        cut_path = await project_service.create_rough_cut(args.id)
        print(f"✅ 粗剪视频合成成功: {cut_path}")

    elif args.command == "workflows":
        print(f"\n🛠️ 已登记的 ComfyUI 工作流模板:")
        for wf in workflow_registry.profiles.values():
            print(f"  • [{wf.workflow_id}] {wf.name} ({wf.generation_mode})")
            print(f"    支持画幅: {', '.join(wf.supported_aspect_ratios)} | 显存要求: {wf.min_vram_gb}GB")
    else:
        parser.print_help()

if __name__ == "__main__":
    asyncio.run(run_cli())
