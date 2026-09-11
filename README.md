---
title: Movie Agent - AI 电影制作智能体
emoji: 🎬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🎬 Movie Agent - AI 电影制作智能体

> 基于《电影Agent详细实现方案.md》的短片制作 Agent。
> 采用三层结构：
> - **Agent 核心引擎 (`agent/`)**：纯净无框架依赖的 Headless Agent SDK，可作为通用 Python 包独立使用；
> - **服务与存储层 (`server/`)**：负责 RESTful 路由、SQLite 审计持久化与 ModelScope/Docker 运行环境；
> - **独立前端界面 (`web/`)**：现代化暗黑电影质感 UI，前后端独立演进。

---

## 🌟 核心特性与架构

```text
用户输入（创意/大纲/剧本）
        ↓
【反问引擎】固定问题库 + 优先级公式 (Impact × Uncertainty × Blocking) + 最多 3 轮终止
        ↓
【创作简报】CreativeBrief（用户可直接核对、编辑与确认）
        ↓
【剧本拆解】ProjectBible（锁定角色外貌 fixed_appearance 与场景固定描述）+ SceneSpec
        ↓
【镜头拆解】ShotSpec（时长严格守恒在 5% 误差内、起幅/动作/落幅可观察、连续性校验）
        ↓
【Prompt 编译器】8 层确定性拼装（风格锁、角色锁、场景锁、起幅、动作、运镜、灯光、质感）+ 负向提示词去重
        ↓
【工作流引擎】PatchMap 确定性打补丁（不改动原始模板，校验节点/输入存在）
        ↓
【ComfyUI 客户端】HTTP POST /prompt + /history 输出追踪 + 失败重试；本地仿真须显式开启
        ↓
【粗剪成片】FFmpeg 自动拼接所有镜头视频、混音、生成完整短片 MP4
```

---

## 📁 解耦后的清晰项目结构

```text
dy/
├── agent/                    # 🧠 纯粹的 Agent 核心引擎 (Headless Agent SDK)
│   ├── __init__.py           # 导出 MovieAgent, ProjectService, Data Models
│   ├── models.py             # 核心领域数据模型 (Pydantic extra="forbid")
│   ├── service.py            # Agent 主流程状态机与用例编排
│   ├── questions.py          # 反问引擎 (优先级计算、3 轮终止、安全默认)
│   ├── prompt_compiler.py    # 8 层 Prompt 确定性编译器
│   ├── workflow.py           # 工作流注册中心、能力选择算法与 PatchMap 补丁引擎
│   ├── comfyui.py            # ComfyUI API 客户端与显式本地仿真
│   ├── continuity.py         # 视听连续性检查
│   └── llm.py                # 结构化 LLM 调用与自修复重试
│
├── server/                   # 🌐 服务端与持久化层 (FastAPI Backend & Storage)
│   ├── __init__.py
│   ├── config.py             # 集中配置中心 (Pydantic BaseSettings)
│   ├── db.py                 # SQLite 持久化与不可变版本控制
│   ├── api.py                # RESTful API 路由 (依赖并调用 agent.*)
│   ├── main.py               # FastAPI 服务入口、生命周期管理、静态资源挂载
│   └── cli.py                # 终端命令行 CLI 工具
│
├── web/                      # 🎨 独立前端界面 (Decoupled Web Frontend)
│   ├── index.html            # 4 步向导式界面 (创意反问/简报/分镜/粗剪)
│   ├── styles.css            # 暗黑电影质感 UI 样式
│   └── app.js                # 前端业务状态控制与 REST API 调用
│
├── prompts/                  # 结构化 Prompt 模板
│   ├── extract_brief.md       # 调用 A：输入要素抽取
│   ├── build_screenplay.md    # 调用 B：剧本拆解与人物场景圣经
│   └── build_shots.md         # 调用 C：分镜镜头拆解
├── workflows/                # ComfyUI API 工作流模板集
│   ├── flux_character_sheet_v1/ # Flux 角色与场景概念图工作流
│   ├── wan_i2v_v1/              # Wan2.1 图生视频工作流
│   └── cogvideox_t2v_v1/        # CogVideoX 文生视频工作流
├── tests/                    # 21 个测试函数覆盖核心流程
│   ├── test_questions.py      # 反问引擎与优先级计算测试
│   ├── test_prompt_compiler.py# 提示词分层与角色锁定测试
│   ├── test_workflow_patch.py # PatchMap 注入与原始模板不变性测试
│   ├── test_continuity.py     # 视听连续性校验测试
│   ├── test_api.py            # FastAPI 端点生命周期集成测试
│   ├── test_end_to_end.py     # 3 个典型场景端到端仿真与粗剪测试
│   └── test_comfyui.py        # ComfyUI 输出解析与断线失败测试
├── Dockerfile                # ModelScope Studio 容器构建规范 (端口 7860 + FFmpeg)
├── app.py                    # 根目录统一启动入口
├── requirements.txt          # 核心依赖清单
├── pytest.ini                 # 测试配置
└── .env.example               # 环境变量配置模板
```

---

## 🚀 快速开始

### 1. 启动 Web 页面与 API 服务

```bash
# 方式一：直接运行启动入口（默认端口 7860，兼容 ModelScope 创空间）
python app.py

# 方式二：通过 uvicorn 启动（可指定端口）
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

在浏览器中打开：👉 **http://localhost:8000** 或 **http://localhost:7860**

### 2. 作为独立 Headless Agent SDK 引入

在你的任何 Python 脚本或后台工作流中直接调用：

```python
import asyncio
from agent import MovieAgent

async def main():
    agent = MovieAgent()
    project = agent.create_project("做一个赛博朋克雨夜追凶预告片")
    await agent.analyze_input(project["id"])
    await agent.confirm_brief(project["id"])
    await agent.confirm_shots(project["id"])

asyncio.run(main())
```

### 3. 命令行 CLI 交互

```bash
# 查看所有已登记的 ComfyUI 工作流模板
python -m server.cli workflows

# 依据一句话创意全自动执行端到端生成
python -m server.cli create --idea "做一个赛博朋克侦探在雨夜追凶的45秒预告片" --auto

# 列出所有项目
python -m server.cli list
```

### 4. 运行全量测试套件

```bash
.venv/bin/pytest -v
```
21 项测试全部通过（21 passed）。
