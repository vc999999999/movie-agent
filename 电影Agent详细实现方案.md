# 电影 Agent 详细实现方案

> 基于《电影Agent技术方案.md》细化。第一版聚焦：通过有限轮次反问，把用户的模糊创意整理成可确认的创作简报、剧本拆解、镜头表，以及可注入既有 ComfyUI 模板的执行参数包。

## 1. 产品目标

### 1.1 一句话定义

用户输入一句创意、故事梗概或已有剧本后，Agent 主动识别缺失信息，只追问会显著影响成片的问题；信息足够后，输出结构化剧本、分镜和每个镜头的 ComfyUI 生成方案。

### 1.2 MVP 输入

支持三类输入，最终都归一化成同一个 `CreativeBrief`：

1. 一句话创意，例如“做一个赛博朋克侦探在雨夜追凶的 45 秒预告片”。
2. 故事梗概，例如人物、冲突、结局已经给出，但没有镜头信息。
3. 完整或半完整剧本，Agent 保留原剧情，只补生产所需信息。

可选输入：

- 角色参考图、场景参考图、风格参考图。
- 目标平台，例如抖音、B 站、YouTube Shorts。
- 已有 ComfyUI API workflow JSON。
- 可用模型、LoRA、自定义节点和机器显存信息。

### 1.3 MVP 输出

一次“已确认”的项目输出以下文件或等价 JSON：

```text
project_bible.json        项目固定设定
screenplay.json           场景化剧本
shot_list.json            可执行镜头表
prompt_package.json       每个镜头的正负提示词和生成参数
workflow_plan.json        工作流选择、PatchMap 和依赖检查结果
production_report.md      给用户阅读和确认的制作说明
```

### 1.4 第一版边界

第一版不让 LLM 从零自由拼装任意 ComfyUI 节点图。它只做三件事：

1. 从已登记模板中选择兼容工作流。
2. 生成模板所需的语义参数。
3. 通过 `PatchMap` 确定性写入 workflow JSON。

原因：ComfyUI 节点 ID、模型、插件和输入结构与本机环境强相关。自由生成 JSON 很容易得到“格式正确但无法运行”的工作流。若没有匹配模板，系统输出明确的 `WorkflowRequirement`，不伪造可执行结果。

## 2. 用户体验流程

### 2.1 主流程

```text
用户输入
  ↓
提取已知事实与约束
  ↓
识别高影响缺口
  ├── 有缺口 → 每轮追问 1～3 个问题 → 合并答案 → 再判断
  └── 信息足够
  ↓
展示 CreativeBrief 摘要
  ├── 用户修改 → 更新摘要
  └── 用户确认
  ↓
生成 ProjectBible + Screenplay
  ↓
生成 SceneSpec + ShotSpec
  ↓
用户审阅镜头表
  ├── 局部修改 → 只重算受影响镜头
  └── 确认
  ↓
生成 PromptPackage
  ↓
匹配工作流模板并生成 patched_workflow.json
  ↓
导出，或提交到 ComfyUI
```

### 2.2 反问体验原则

- 每轮最多 3 个问题，优先提供选项，也允许自由回答。
- 不重复询问用户已经明确表达的信息。
- 不询问可以安全采用默认值的低影响参数。
- 每个问题说明它会影响什么，例如“这会影响镜头节奏和镜头数量”。
- 用户回答“你决定”时，记录为 Agent 默认，而不是继续追问。
- 最多 3 轮；仍缺少低风险信息时采用默认值并在确认页标出。
- 角色身份、目标时长、画幅、内容限制等高风险冲突不能静默猜测。

### 2.3 首轮优先确认的信息

按影响从高到低排序：

| 信息 | 为什么重要 | 缺省策略 |
|---|---|---|
| 成片目的和平台 | 决定节奏、画幅和文案密度 | 通用网络短片 |
| 成片时长 | 决定场景和镜头预算 | 45 秒 |
| 核心人物与目标 | 决定叙事主线 | 从输入推断；不确定则追问 |
| 冲突与结局 | 决定故事是否闭环 | 预告片可保留悬念 |
| 视觉风格 | 决定模型、提示词和工作流 | 写实电影感 |
| 画幅 | 决定分辨率与构图 | 平台已知则自动选择，否则 16:9 |
| 是否有人声对白 | 决定口型、配音和镜头设计 | 旁白优先 |
| 参考资产 | 决定角色一致性方案 | 无参考时先生成角色定妆图 |

## 3. 不用“多 Agent 群聊”的 MVP 架构

第一版采用一个编排服务、若干确定性步骤和 4 类结构化 LLM 调用。`Script Agent`、`Storyboard Agent` 等先作为 Prompt 模块，而不是独立自治进程。

```text
FastAPI
  └── ProjectService
       ├── analyze_input()       LLM：提取信息
       ├── choose_questions()    代码：选择缺口
       ├── build_screenplay()    LLM：剧本结构化
       ├── build_shot_list()     LLM：分镜结构化
       ├── compile_prompts()     代码 + LLM：提示词编译
       ├── patch_workflow()      纯代码：修改 workflow JSON
       └── submit_comfyui()      HTTP/WebSocket：可选执行
```

暂不引入 LangGraph。一个带枚举状态的状态机已经能覆盖 MVP；当出现并行渲染、人工审批分支、跨进程恢复和复杂重试后，再迁移 LangGraph。

## 4. 状态机

### 4.1 项目状态

```python
ProjectStatus = Literal[
    "collecting",          # 正在理解输入/反问
    "brief_review",        # 等待用户确认创作简报
    "screenplay_ready",    # 剧本拆解完成
    "shots_review",        # 等待用户确认镜头表
    "package_ready",       # Prompt 和工作流参数包完成
    "rendering",           # 可选：正在执行 ComfyUI
    "completed",
    "failed",
]
```

### 4.2 状态转换规则

| 当前状态 | 动作 | 下一状态 |
|---|---|---|
| collecting | 提交答案且仍有关键缺口 | collecting |
| collecting | 信息足够或达到反问上限 | brief_review |
| brief_review | 修改简报 | brief_review |
| brief_review | 确认简报 | screenplay_ready |
| screenplay_ready | 生成分镜 | shots_review |
| shots_review | 修改镜头 | shots_review |
| shots_review | 确认镜头 | package_ready |
| package_ready | 提交 ComfyUI | rendering |
| rendering | 全部成功 | completed |
| rendering | 不可恢复错误 | failed |

所有状态转换由后端校验。LLM 可以建议下一步，但不能直接修改状态。

## 5. 核心数据模型

以下字段是 MVP 必需集合。字段应使用 Pydantic `extra="forbid"`，防止模型输出悄悄增加未处理字段。

### 5.1 CreativeBrief

```python
class CreativeBrief(BaseModel):
    title: str | None = None
    logline: str
    purpose: Literal["short_film", "trailer", "ad", "music_video", "social_video"]
    audience: str | None = None
    platform: Literal["douyin", "bilibili", "youtube", "other"] = "other"
    duration_seconds: int = Field(ge=10, le=90)
    aspect_ratio: Literal["16:9", "9:16", "1:1", "2.39:1"]
    genre: list[str]
    tone: list[str]
    visual_style: str
    story_summary: str
    protagonist: str
    protagonist_goal: str
    conflict: str
    ending: str | None = None
    dialogue_mode: Literal["none", "voiceover", "dialogue", "mixed"]
    language: str = "zh-CN"
    content_constraints: list[str] = []
    user_must_keep: list[str] = []
    agent_assumptions: list[str] = []
```

### 5.2 CharacterBible

```python
class CharacterBible(BaseModel):
    character_id: str
    name: str
    narrative_role: str
    age_range: str | None
    gender_presentation: str | None
    fixed_appearance: str
    fixed_costume: str
    personality: list[str]
    voice: str | None
    reference_asset_ids: list[str]
    forbidden_changes: list[str]
```

`fixed_appearance` 和 `fixed_costume` 是后续每个相关镜头都要复用的固定描述，不能由分镜阶段重新发挥。

### 5.3 LocationBible

```python
class LocationBible(BaseModel):
    location_id: str
    name: str
    fixed_visual_description: str
    layout_notes: str
    time_of_day: str
    weather: str | None
    lighting_baseline: str
    reference_asset_ids: list[str]
    forbidden_changes: list[str]
```

### 5.4 SceneSpec

```python
class SceneSpec(BaseModel):
    scene_id: str
    order: int
    heading: str
    location_id: str
    time_of_day: str
    estimated_duration: float
    purpose: str
    characters: list[str]
    setup: str
    action_beats: list[str]
    dialogue: list[DialogueLine]
    transition_in: str
    transition_out: str
    continuity_in: list[str]
    continuity_out: list[str]
```

### 5.5 ShotSpec

```python
class ShotSpec(BaseModel):
    shot_id: str
    scene_id: str
    order: int
    duration_seconds: float = Field(gt=0, le=12)
    narrative_purpose: str
    subject_ids: list[str]
    location_id: str
    start_frame: str
    action: str
    end_frame: str
    shot_size: Literal["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"]
    camera_angle: str
    camera_movement: str
    composition: str
    lens: str | None
    fps: int = 24
    lighting: str
    mood: str
    dialogue: str | None
    voiceover: str | None
    sound_effects: list[str]
    music_cue: str | None
    continuity_requirements: list[str]
    reference_asset_ids: list[str]
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"]
    first_frame_required: bool
    last_frame_required: bool
```

关键约束：

- 所有镜头时长总和应接近目标时长，误差不超过 5%。
- 常规单镜头控制在 2～6 秒；超过 8 秒必须说明原因。
- `start_frame → action → end_frame` 必须可观察，避免“感到孤独”这类无法直接生成的动作。
- 相邻镜头的服装、道具、人物位置和时间变化必须有解释。

### 5.6 PromptPackage

```python
class ShotPrompt(BaseModel):
    shot_id: str
    prompt_language: Literal["en", "zh"] = "en"
    positive_prompt: str
    negative_prompt: str
    image_prompt: str | None
    video_prompt: str
    reference_asset_ids: list[str]
    seed: int
    steps: int | None
    cfg: float | None
    width: int
    height: int
    frame_count: int
    fps: int
    workflow_id: str | None
    unsupported_requirements: list[str]
```

### 5.7 WorkflowProfile

```python
class WorkflowProfile(BaseModel):
    workflow_id: str
    version: str
    name: str
    generation_mode: Literal["text_to_image", "image_to_video", "text_to_video"]
    supported_aspect_ratios: list[str]
    min_vram_gb: int
    max_frames: int
    required_models: list[str]
    required_nodes: list[str]
    accepted_references: list[Literal["character", "style", "first_frame", "last_frame"]]
    patch_map_path: str
    workflow_path: str
```

## 6. 反问引擎

### 6.1 两步实现

反问不应完全交给 LLM 自由发挥。

第一步，LLM 只负责把用户输入抽取成：

```json
{
  "known": {"duration_seconds": 45, "genre": ["赛博朋克", "悬疑"]},
  "unknown": ["ending", "dialogue_mode", "aspect_ratio"],
  "conflicts": [],
  "confidence": {"duration_seconds": 1.0, "visual_style": 0.78}
}
```

第二步，代码根据字段优先级、置信度和当前可用工作流选择问题。这样能保证问题稳定、可测试，也不会每轮改变标准。

### 6.2 问题选择规则

每个候选问题计算：

```text
priority = impact × uncertainty × blocking
```

- `impact`：对故事、镜头或技术路线的影响，1～5。
- `uncertainty`：字段缺失为 1；低置信度为 `1 - confidence`。
- `blocking`：不回答是否无法继续，阻塞为 2，否则为 1。

取分数最高的 3 个；同一主题只问一个。冲突项始终优先于缺失项。

### 6.3 固定问题库示例

```python
QUESTION_BANK = {
    "duration_seconds": {
        "text": "你希望成片多长？这会决定场景数量和镜头节奏。",
        "choices": ["30 秒", "45 秒", "60 秒", "90 秒"],
        "impact": 5,
        "blocking": True,
    },
    "ending": {
        "text": "结尾要完整收束，还是停在悬念上？",
        "choices": ["完整结局", "反转", "开放式", "预告片式悬念"],
        "impact": 5,
        "blocking": False,
    },
    "dialogue_mode": {
        "text": "声音以哪种方式讲故事？这会影响口型和镜头设计。",
        "choices": ["无对白", "旁白", "角色对白", "混合"],
        "impact": 4,
        "blocking": False,
    },
}
```

### 6.4 结束反问的条件

满足以下条件即可进入简报确认：

- `logline`、目标时长、主角、目标、冲突、风格、画幅已明确或有安全默认值。
- 不存在互相矛盾的硬约束。
- 已经完成 3 轮反问。
- 用户明确要求“直接生成”。

系统必须在 `agent_assumptions` 中列出所有自动补全内容。

## 7. LLM 调用设计

### 7.1 调用 A：输入抽取

输入：原始用户文本、上传资产摘要、上一轮 `CreativeBrief`、本轮回答。

输出：`BriefExtraction`。

系统要求：

- 只提取或合并信息，不写剧本。
- 保留用户明确措辞和 `user_must_keep`。
- 区分事实、推断和缺失项。
- 不制造参考图、模型或工作流能力。

### 7.2 调用 B：剧本拆解

前置条件：用户确认 `CreativeBrief`。

输入：确认后的简报、角色和场景参考资产摘要。

输出：`ProjectBible + list[SceneSpec]`。

系统要求：

- 总时长守恒。
- 每场戏必须服务于主线。
- 短片优先 1～3 个场景、1～3 个核心角色。
- 把心理描述改成可见动作、表情、台词或声音。
- 不改变 `user_must_keep`。

### 7.3 调用 C：镜头拆解

输入：已确认剧本、项目圣经、工作流能力摘要。

输出：`list[ShotSpec]`。

系统要求：

- 每个镜头只能描述一个主要视觉动作。
- 镜头之间满足时间、空间和动作连续性。
- 不使用当前工作流无法表达的功能；必须使用时写入技术备注。
- 镜头 ID 稳定，局部改稿时不得无故重排全部 ID。

### 7.4 调用 D：语义 Prompt 编译

输入：单个 `ShotSpec`、相关角色/场景固定描述、目标模型的提示词规范。

输出：只包含语义提示词字段，不包含节点 ID。

同一批镜头可以在镜头表确认后并行调用。角色固定描述、场景固定描述由代码拼接，禁止模型改写。

## 8. Prompt 编译器

### 8.1 Prompt 分层

最终正向提示词按固定顺序拼装：

```text
[项目风格锁]
[角色固定描述]
[场景固定描述]
[镜头起始状态]
[主体动作]
[镜头景别、角度、运动与构图]
[灯光、色彩与情绪]
[画质和模型特定词]
```

负向提示词由三部分合并并去重：

```text
工作流默认负面词
+ 项目级禁用内容
+ 当前镜头容易出现的问题
```

### 8.2 不让模型控制的参数

以下参数由代码计算或工作流默认值提供：

- `width`、`height`：由画幅和渲染档位映射。
- `frame_count`：由 `duration_seconds × fps` 计算，并受模板上限约束。
- `seed`：首次随机生成后持久化；重做时由用户选择复用或换种子。
- `steps`、`cfg`：采用工作流模板默认值，除非用户进入高级设置。
- 节点 ID 和输入名：只从 `PatchMap` 读取。

### 8.3 模型特定 Prompt 规则

每个工作流可附带一个短规则文件，例如：

```yaml
prompt_language: en
max_prompt_chars: 1800
motion_style: natural_sentence
supports_negative_prompt: true
defaults:
  steps: 28
  cfg: 5.5
```

Prompt 编译器读取规则后再调用 LLM。第一版不做通用 DSL。

## 9. 工作流模板与选择

### 9.1 模板目录

```text
workflows/
  flux_character_sheet_v1/
    workflow_api.json
    profile.json
    patch_map.json
    prompt_rules.yaml
  wan_i2v_v1/
    workflow_api.json
    profile.json
    patch_map.json
    prompt_rules.yaml
```

ComfyUI 必须保存 API 格式 workflow，不使用仅供前端显示的普通 workflow JSON。

### 9.2 PatchMap

```json
{
  "positive_prompt": {"node": "12", "input": "text", "required": true},
  "negative_prompt": {"node": "13", "input": "text", "required": false},
  "seed": {"node": "7", "input": "seed", "required": true},
  "width": {"node": "21", "input": "width", "required": true},
  "height": {"node": "21", "input": "height", "required": true},
  "first_frame": {"node": "31", "input": "image", "required": true},
  "frame_count": {"node": "40", "input": "length", "required": true}
}
```

打补丁前必须检查：节点存在、输入存在、必需值非空、值类型正确、文件引用位于允许目录。

### 9.3 工作流选择算法

按以下顺序过滤：

1. `generation_mode` 匹配。
2. 所需参考图类型被支持。
3. 画幅和帧数可支持。
4. 本机已安装依赖。
5. 显存满足要求。

过滤后只有一个模板则直接选择；有多个时按项目默认模板优先，不让 LLM随意选择。没有模板时输出：

```json
{
  "status": "unsupported",
  "shot_id": "s01_sh03",
  "reason": "需要首尾帧约束，但当前模板只支持首帧图生视频",
  "required_capabilities": ["image_to_video", "first_frame", "last_frame"]
}
```

### 9.4 工作流依赖预检

读取 ComfyUI `/object_info` 和本机模型清单，检查：

- 自定义节点 class 是否存在。
- checkpoint、VAE、LoRA、ControlNet 文件是否存在。
- PatchMap 指向的节点和输入是否存在。
- 输出节点是否可追踪。

预检失败时不提交任务，直接返回可操作错误。

## 10. API 设计

### 10.1 项目和对话

```text
POST   /api/projects
GET    /api/projects/{project_id}
POST   /api/projects/{project_id}/messages
GET    /api/projects/{project_id}/questions
POST   /api/projects/{project_id}/answers
POST   /api/projects/{project_id}/brief/confirm
PATCH  /api/projects/{project_id}/brief
```

`POST /messages` 返回当前提取结果、下一批问题和简报完成度，不直接开始分镜。

### 10.2 剧本与分镜

```text
POST   /api/projects/{project_id}/screenplay/generate
GET    /api/projects/{project_id}/screenplay
PATCH  /api/projects/{project_id}/scenes/{scene_id}
POST   /api/projects/{project_id}/shots/generate
GET    /api/projects/{project_id}/shots
PATCH  /api/projects/{project_id}/shots/{shot_id}
POST   /api/projects/{project_id}/shots/confirm
```

局部修改镜头时，后端标记该镜头和相邻镜头的 PromptPackage 为过期，不重做整份项目。

### 10.3 Prompt 与工作流

```text
POST   /api/projects/{project_id}/packages/generate
GET    /api/projects/{project_id}/packages
POST   /api/shots/{shot_id}/workflow/compile
POST   /api/shots/{shot_id}/render
GET    /api/renders/{render_id}
POST   /api/renders/{render_id}/retry
```

### 10.4 关键响应示例

```json
{
  "project_id": "prj_01",
  "status": "collecting",
  "brief_completion": 0.78,
  "questions": [
    {
      "question_id": "q_ending",
      "text": "结尾要完整收束，还是停在悬念上？",
      "choices": ["完整结局", "反转", "开放式", "预告片式悬念"],
      "affects": ["story_structure", "last_shot"]
    }
  ],
  "assumptions": ["未指定平台，暂按通用网络短片处理"]
}
```

## 11. 持久化

MVP 使用 SQLite，保留以下最小表：

```text
projects
  id, status, title, source_text, brief_json, created_at, updated_at

messages
  id, project_id, role, content, created_at

artifacts
  id, project_id, kind, version, content_json, status, created_at

assets
  id, project_id, kind, path, sha256, metadata_json, approved_at

workflow_templates
  id, version, profile_json, workflow_path, patch_map_path, enabled

render_runs
  id, project_id, shot_id, workflow_id, status, request_json,
  prompt_id, output_json, error_json, created_at, finished_at
```

不为 Scene、Shot、Character 分别建表；MVP 将它们作为版本化 artifact JSON 保存。只有出现大量局部查询或多人协作时再拆表。

每次用户确认后创建不可变 artifact 版本。最新草稿可以覆盖，但已用于渲染的版本不得覆盖。

## 12. 文件结构

```text
movie-agent/
├── app/
│   ├── api.py                 # FastAPI 路由
│   ├── models.py              # Pydantic 模型
│   ├── service.py             # 状态转换和用例编排
│   ├── llm.py                 # 结构化 LLM 调用
│   ├── questions.py           # 固定问题库和选择规则
│   ├── prompt_compiler.py     # Prompt 确定性拼装
│   ├── workflow.py            # 模板选择、校验和 PatchMap
│   ├── comfyui.py             # HTTP/WebSocket 客户端
│   ├── db.py                  # sqlite3 持久化
│   └── main.py
├── prompts/
│   ├── extract_brief.md
│   ├── build_screenplay.md
│   └── build_shots.md
├── workflows/
├── tests/
│   ├── test_questions.py
│   ├── test_prompt_compiler.py
│   └── test_workflow_patch.py
└── projects/
```

先不拆 `agents/`、`domain/`、`adapters/` 多层目录。代码增长到单文件职责难以维护时再拆。

## 13. 前端页面

MVP 只需要 4 个页面或步骤：

### 13.1 创意输入与反问

- 大文本框、参考图上传、已有 workflow 上传。
- 对话区展示每轮 1～3 个问题。
- 侧栏实时显示“已确定 / Agent 假设 / 待确认”。

### 13.2 创作简报确认

- 展示故事一句话、时长、风格、角色、冲突、结局和技术约束。
- 用户可直接编辑字段。
- Agent 推断内容使用不同标记。

### 13.3 剧本与镜头表

- 左侧场景，右侧镜头卡片。
- 镜头卡显示时长、画面、运镜、台词、声音和生成方式。
- 支持单镜头修改、删除、复制和锁定。
- 页面底部显示总时长和连续性警告。

### 13.4 生成包与执行

- 每个镜头显示所选模板、Prompt、参考资产和依赖状态。
- 支持复制 Prompt、下载 workflow JSON、低清试跑。
- 不兼容镜头显示原因，不显示伪造的“可运行”按钮。

## 14. 连续性实现

第一版不需要独立 Continuity Agent。使用“固定资产 + 规则校验 + 一次 LLM 审阅”即可。

### 14.1 确定性校验

- ShotSpec 引用的角色和场景 ID 必须存在。
- 相邻镜头同一角色的服装版本必须一致。
- 道具状态变化必须出现在 `action` 或转场说明中。
- 同一时间段的天气和主光方向不得无理由变化。
- 下一镜头 `start_frame` 应能承接上一镜头 `end_frame`。

### 14.2 LLM 审阅

只把相邻镜头对发送给 LLM，输出 `ContinuityIssue[]`：

```python
class ContinuityIssue(BaseModel):
    severity: Literal["warning", "error"]
    shot_ids: list[str]
    field: str
    explanation: str
    suggested_fix: str
```

Agent 只建议，不自动改已确认的镜头。

## 15. ComfyUI 执行

### 15.1 提交流程

```text
加载 WorkflowProfile
→ 依赖预检
→ 深拷贝 workflow_api.json
→ 按 PatchMap 写值
→ 保存本次 patched_workflow.json
→ POST /prompt
→ 记录 prompt_id
→ WebSocket 监听
→ /history/{prompt_id} 获取输出
→ 保存 RenderRun 和素材哈希
```

### 15.2 重试策略

- 网络超时、ComfyUI 短暂不可用：自动重试 2 次，指数退避。
- 缺节点、缺模型、PatchMap 错误：不重试，直接报告依赖问题。
- OOM：自动降低到预览档一次；仍失败则停止。
- 生成结果不满意：不属于系统错误，由用户选择“保持 Seed 调参数”或“换 Seed 重做”。

### 15.3 幂等与复现

对以下内容计算 SHA-256：

```text
workflow 模板版本
+ patched 参数
+ Prompt
+ Seed
+ 引用资产哈希
```

相同指纹已有成功结果时直接复用。每次运行保存 ComfyUI prompt_id、模型名、模板版本、参数和输出哈希。

## 16. 校验与错误模型

统一错误结构：

```json
{
  "code": "WORKFLOW_DEPENDENCY_MISSING",
  "message": "工作流缺少 VHS_VideoCombine 节点",
  "details": {"missing_nodes": ["VHS_VideoCombine"]},
  "retryable": false,
  "suggested_action": "安装 VideoHelperSuite 后重新预检"
}
```

LLM 输出依次经过：

1. JSON 解析。
2. Pydantic Schema 校验。
3. 业务规则校验，例如时长守恒和 ID 引用。
4. 最多一次“带校验错误的修复调用”。
5. 仍失败则保留原响应和错误，不进入下一状态。

## 17. 安全与内容边界

- 上传文件限制类型、大小和文件名，保存时改用系统生成 ID。
- Workflow JSON 视为不可信输入，只允许白名单节点；不自动安装未知自定义节点。
- 模型和引用资产路径不得越过配置的数据目录。
- API 密钥只保存在环境变量，不写入项目 artifact 或 RenderRun。
- 用户提交渲染前展示模型、节点和成本/耗时预估。
- 涉及真人肖像时记录用户对素材使用权的确认。

## 18. 最小测试集

### 18.1 反问引擎

- 已明确“45 秒竖屏无对白”时不再询问时长、画幅或声音模式。
- 输入中出现“30 秒”和“1 分钟”时优先询问冲突。
- 三轮后停止追问，并记录低风险默认值。

### 18.2 剧本和镜头

- 45 秒目标的镜头总时长误差不超过 2.25 秒。
- 每个 ShotSpec 的角色和场景 ID 都能在 ProjectBible 找到。
- 修改一个镜头只使该镜头及相邻连续性结果失效。

### 18.3 Prompt 编译

- 角色固定描述逐字出现在所有相关镜头 Prompt 中。
- 负面词合并后无重复项。
- 画幅能映射到正确分辨率。

### 18.4 Workflow Patch

- PatchMap 能写入目标节点且不改变其他节点。
- 缺少节点、输入或必需值时拒绝生成。
- 原始 workflow 模板保持不变。

### 18.5 集成验收样例

准备 3 个固定样例：

1. 一句话 30 秒竖屏预告片。
2. 带两名角色和对白的 60 秒剧情短片。
3. 已有完整剧本和角色参考图的 90 秒短片。

每次改 Prompt 或模型后运行并对比结构化字段、问题数量、总时长和工作流预检结果。

## 19. 开发阶段与交付物

### 阶段 0：固定一个真实工作流，1～2 天

交付：

- 选定一个 ComfyUI 图生视频 API workflow。
- 导出 `workflow_api.json`。
- 写 `profile.json` 和 `patch_map.json`。
- 用手写 ShotPrompt 成功生成一个镜头。

这是最先做的技术验证。若工作流无法稳定 API 化，先解决它，不继续搭 Agent。

### 阶段 1：反问与创作简报，3～5 天

交付：

- `CreativeBrief` Schema。
- 输入抽取 Prompt。
- 固定问题库、优先级和三轮终止规则。
- 简报确认 API 和简单页面。
- 反问引擎测试。

验收：用一句话输入，Agent 能在不超过三轮内得到可确认简报，不重复问题。

### 阶段 2：剧本与镜头拆解，4～6 天

交付：

- Character、Location、Scene、Shot Schema。
- 剧本拆解和分镜 Prompt。
- 时长、ID、连续性基础校验。
- 镜头表编辑和确认。

验收：30～90 秒输入能生成 3～15 个可观察、可生成的镜头，总时长合规。

### 阶段 3：Prompt 和工作流编译，4～6 天

交付：

- Prompt 编译器。
- WorkflowProfile、模板选择和依赖预检。
- PatchMap 修改器。
- 每镜头 workflow JSON 下载。

验收：至少 3 个镜头能生成各自的可提交 workflow，模板本身不被修改。

### 阶段 4：ComfyUI 执行，3～5 天

交付：

- `/prompt`、WebSocket、`/history` 和素材保存。
- RenderRun、错误分类、两次瞬时故障重试。
- 低清预览档。

验收：批量执行 3 个镜头，成功任务可复现，失败任务可定位。

### 阶段 5：粗剪，按需增加

交付：按镜头顺序用 FFmpeg 拼接、混入音轨、生成字幕和 MP4。不要在前四阶段完成前提前实现。

## 20. MVP 验收标准

给定一句用户创意和一个已登记的 ComfyUI 工作流：

1. Agent 在最多 3 轮、每轮最多 3 问内完成需求澄清。
2. 用户能看到并修改 Agent 的推断和默认值。
3. 生成结构化 ProjectBible、1～3 场戏和 3～15 个 ShotSpec。
4. 镜头总时长与目标误差不超过 5%。
5. 每个镜头都有可直接阅读的画面描述、摄影设计、声音设计和连续性要求。
6. 每个镜头生成正向、负向、视频动作 Prompt 和确定性参数。
7. 系统只选择能力匹配且预检通过的工作流模板。
8. 输出 patched workflow 时不修改原始模板。
9. 至少 3 个镜头可通过 ComfyUI API 执行，并完整记录 Seed、Prompt、模板和输出。
10. 缺模型、缺节点、超帧数或不支持能力时给出明确错误，不伪造成功。

## 21. 推荐的第一条纵向切片

不要先分别完成所有 Agent。第一条可用链路只实现一个固定场景：

```text
一句话创意
→ 最多三轮反问
→ 45 秒 CreativeBrief
→ 3 个 ShotSpec
→ 使用一个图生视频模板
→ 生成 3 份 PromptPackage 和 patched workflow
→ 用户手动下载或提交 ComfyUI
```

这条链路跑通后，再加入角色定妆图、多模板选择、自动渲染、连续性质检和 FFmpeg。这样最早能验证的不是“Agent 架构是否漂亮”，而是用户是否愿意采用它给出的分镜与工作流。
