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

> 严格遵循《电影Agent详细实现方案.md》真实落地的高水准全链路电影制作 Agent 系统。
> 支持从用户一句创意、故事梗概或剧本片段出发，通过有限轮次（最多 3 轮、每轮最多 3 问）高影响度反问澄清需求，输出结构化剧本 (Screenplay)、人物与场景圣经 (ProjectBible)、可执行镜头表 (ShotSpec)、多层分层提示词包 (PromptPackage)，并确定性注入 ComfyUI 模板生成素材，最后通过 FFmpeg 自动合成粗剪短片。

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
【ComfyUI 客户端】HTTP POST /prompt + WebSocket 监听 + /history 输出追踪 + 失败重试 + 本地高保真仿真兜底
        ↓
【粗剪成片】FFmpeg 自动拼接所有镜头视频、混音、生成完整短片 MP4
```

---

## 📁 真实落地的项目结构

```text
dy/
├── app/
│   ├── __init__.py            # 模块入口与版本
│   ├── config.py              # 配置中心（Pydantic BaseSettings，加载环境变量/.env）
│   ├── models.py              # 核心数据模型（CreativeBrief, ShotSpec, ProjectBible等，extra="forbid"）
│   ├── db.py                  # SQLite3 持久化（projects, messages, artifacts, render_runs 等）
│   ├── questions.py           # 反问引擎（优先级计算、问题库、3 轮终止规则、安全默认策略）
│   ├── prompt_compiler.py     # 提示词编译器（8 层正向提示词组装、负向去重、画幅分辨率映射）
│   ├── workflow.py            # 工作流注册中心（模板加载、能力匹配算法、PatchMap 确定性注入）
│   ├── comfyui.py             # ComfyUI 客户端（/prompt, WebSocket 监听, /history, 产物下载与仿真）
│   ├── continuity.py          # 视听连续性检查（ID 引用、光影跃迁、起始帧承接）
│   ├── llm.py                 # 结构化 LLM 服务（支持 OpenAI/DeepSeek/Qwen + 自修复重试 + 离线仿真）
│   ├── service.py             # 核心业务编排与状态机（状态转换、全流程管线、FFmpeg 粗剪）
│   ├── api.py                 # FastAPI REST 路由（满足详细实现方案第 10 节全部端点）
│   ├── main.py                # 服务入口与静态页面挂载
│   └── cli.py                 # 命令行交互工具
├── prompts/                   # 结构化 Prompt 模板
│   ├── extract_brief.md       # 调用 A：输入要素抽取
│   ├── build_screenplay.md    # 调用 B：剧本拆解与人物场景圣经
│   ├── build_shots.md         # 调用 C：分镜镜头拆解
│   ├── compile_shot_prompt.md # 调用 D：语义提示词编译
│   └── continuity_review.md   # 视听连续性审查
├── workflows/                 # ComfyUI API 工作流模板集
│   ├── flux_character_sheet_v1/ # Flux 角色与场景概念图工作流
│   ├── wan_i2v_v1/              # Wan2.1 图生视频工作流
│   └── cogvideox_t2v_v1/        # CogVideoX 文生视频工作流
├── static/                    # 现代暗黑电影质感 Web UI 前端
│   ├── index.html             # 四步式向导界面
│   ├── styles.css             # 响应式极简暗色主题
│   └── app.js                 # 完整前端交互与 API 联动
├── tests/                     # 最小测试集与端到端测试
│   ├── test_questions.py      # 反问引擎与优先级计算测试
│   ├── test_prompt_compiler.py# 提示词分层与角色锁定测试
│   ├── test_workflow_patch.py # PatchMap 注入与不变性测试
│   ├── test_continuity.py     # 视听连续性检查测试
│   ├── test_api.py            # FastAPI 端点生命周期集成测试
│   └── test_end_to_end.py     # 3 个典型场景端到端真实生成与粗剪测试
├── pytest.ini                 # 测试配置
├── .env.example               # 环境变量配置模板
└── README.md                  # 说明文档
```

---

## 🚀 快速开始

### 1. 激活虚拟环境

项目已配置好专用虚拟环境：

```bash
source .venv/bin/activate
```

### 2. 配置环境变量（可选）

复制 `.env.example` 并填入模型 API Key（如果不填，系统内置的仿真生成器也将支持 100% 流程自测）：

```bash
cp .env.example .env
```

```env
OPENAI_API_KEY=sk-xxxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# 若本地已启动 ComfyUI（默认端口 8188）
COMFYUI_HOST=127.0.0.1
COMFYUI_PORT=8188
COMFYUI_MOCK_MODE=false
```

### 3. 启动 Web 页面与 API 服务

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

打开浏览器访问：
👉 **http://localhost:8000**

即可看到完整的 4 步制作界面：
1. **创意与反问**：输入电影创意，实时交互答题，观察右侧要素解析度与 Agent 默认假设。
2. **创作简报确认**：直接审阅和修改片长、画幅、对白模式、主角设定与核心危机。
3. **剧本与分镜**：查看场景与角色固定外貌，检查每个镜头的机位运镜与起承转合，观察时长守恒仪表与连续性提醒。
4. **生成包与粗剪**：查看每个镜头的 Patched Workflow JSON，点击单镜头渲染或一键批量渲染，最后使用 FFmpeg 一键合成粗剪短片并在网页中直接播放！

---

## 💻 CLI 命令行使用

除网页端外，系统提供了完整的 CLI 交互与批量执行工具：

```bash
# 查看所有已登记的 ComfyUI 工作流模板
python -m app.cli workflows

# 依据一句话创意全自动执行端到端生成（自动确认并编译工作流）
python -m app.cli create --idea "做一个赛博朋克侦探在雨夜追凶的45秒预告片" --auto

# 列出所有项目
python -m app.cli list

# 批量执行镜头生成
python -m app.cli render --id prj_xxxxxxxx

# 调用 FFmpeg 一键粗剪拼接 MP4
python -m app.cli rough-cut --id prj_xxxxxxxx
```

---

## 🧪 运行完整测试集

包含反问引擎、Prompt 编译、PatchMap 注入、连续性质检、FastAPI 接口与端到端粗剪的 19 项全量自动化测试：

```bash
.venv/bin/pytest -v
```

全部测试通过（19 passed）。
