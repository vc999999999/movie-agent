# 电影 Agent 技术方案

## 1. 项目定位

构建一个“剧本到短片”的电影制作 Agent：用户输入想法、剧本或参考作品，Agent 自动理解意图，拆分场景和镜头，调用预设的 ComfyUI 工作流生成素材，检查连续性，最后合成可预览的短片。

第一版目标不是自动生成整部长片，而是稳定完成 **30～90 秒短片或预告片**。

## 2. 核心分工

```text
用户想法 / 剧本
        ↓
电影 Agent：理解、规划、管理、检查
        ↓
结构化镜头任务 + ComfyUI workflow.json
        ↓
ComfyUI API：调用模型和节点执行生成
        ↓
图片 / 视频 / 音频素材
        ↓
FFmpeg：合成、配音、字幕、粗剪
        ↓
短片
```

ComfyUI 不负责理解剧本；它负责执行工作流。电影 Agent 的价值在于把人的想法转换成可执行的制作计划，并管理多个镜头之间的关系。

## 3. 推荐技术栈

### 后端

- Python
- FastAPI：项目、任务、素材和审核接口
- Pydantic：结构化输入输出和数据校验
- LangGraph：有状态的 Agent 流程、分支、人工确认和重试
- SQLite：单用户 MVP
- PostgreSQL：多人或正式部署

### 生成与后期

- ComfyUI HTTP API：提交工作流任务
- ComfyUI WebSocket：监听任务进度
- ComfyUI workflow JSON：作为可复用生成模板
- FFmpeg：镜头拼接、音频、字幕、视频导出

### 前端

第一版使用简单网页即可，不做 ComfyUI 式节点编辑器。页面只需要支持：

- 输入剧本
- 查看场景和镜头表
- 审核角色与场景设定
- 生成、重做和接受镜头
- 查看素材
- 导出粗剪视频

## 4. 多 Agent 团队设计

采用“一个总控 + 少量专业 Agent”的方式，不做开放式群聊。

```text
Director / Orchestrator Agent
        ├── Script Agent
        ├── Storyboard Agent
        ├── Continuity Agent
        ├── Render Agent
        └── QA / Editor Agent
```

### 4.1 Director / Orchestrator Agent

职责：

- 接收用户目标
- 决定当前阶段和下一步 Agent
- 检查输入是否完整
- 管理人工确认点
- 处理失败、重试和回退

它不负责直接生成图像或视频。

### 4.2 Script Agent

输入：剧本、故事梗概或用户描述。

输出：

- 故事主题
- 场景列表
- 角色列表
- 时间和地点
- 剧情动作
- 台词和情绪
- 场景之间的因果关系

### 4.3 Storyboard Agent

把场景拆成可执行的镜头，输出 `ShotSpec`。它负责：

- 景别
- 镜头角度
- 镜头运动
- 时长
- 人物动作
- 光线和风格
- 对白和声音需求
- 使用哪个 ComfyUI 工作流

### 4.4 Continuity Agent

维护角色、场景和道具的一致性：

- 角色外貌和服装
- 场景布局
- 时间和天气
- 道具状态
- 镜头前后的动作衔接
- 参考图和资产版本

它不能随意创造新的角色版本，必须优先使用已经审核通过的资产。

### 4.5 Render Agent

这是最接近 ComfyUI 的执行 Agent，但应该保持低创造性：

- 选择已批准的工作流
- 将 Prompt 和参数注入 workflow JSON
- 传入参考图
- 调用 ComfyUI API
- 监听进度
- 保存输出和运行记录
- 处理缺少节点、模型或生成失败

### 4.6 QA / Editor Agent

职责：

- 检查人物、服装和场景连续性
- 检查镜头是否符合 ShotSpec
- 标记画面瑕疵、闪烁、肢体异常和文字错误
- 给出重做建议
- 调用 FFmpeg 合成粗剪

FFmpeg 本身是确定性工具，不应让 Agent 手写复杂剪辑逻辑。

## 5. Prompt 设计

每个 Agent 的上下文分为四层：

```text
固定 System Prompt
        ↓
项目设定：角色圣经、场景圣经、视觉风格
        ↓
当前任务：场景、镜头、目标动作
        ↓
工具结果：模型、节点、参考图、ComfyUI 日志
```

### System Prompt

固定写入：

- Agent 身份
- 负责范围
- 禁止做的事情
- 可用工具
- 输出 JSON Schema
- 错误处理规则
- 不得伪造模型、文件和生成结果

### 注入 Prompt

每次只注入当前任务所需内容，不把全部历史聊天记录传给 Agent。注入内容包括：

- 当前项目设定
- 当前场景和镜头
- 已审核的角色与场景资产
- 用户本次修改意见
- 技术限制，例如时长、尺寸和显存

## 6. 核心数据结构

### ProjectBible

保存整个项目的创作约束：

```json
{
  "title": "短片名称",
  "genre": "科幻悬疑",
  "visual_style": "冷色、写实、低饱和",
  "aspect_ratio": "16:9",
  "characters": ["anna_v1"],
  "locations": ["old_house_v1"]
}
```

### ShotSpec

```json
{
  "shot_id": "s01_sh03",
  "scene_id": "s01",
  "duration": 5,
  "character_ids": ["anna_v1"],
  "location_id": "old_house_v1",
  "action": "女主角推开旧木门",
  "camera": "中近景，缓慢推进",
  "lighting": "冷色月光",
  "dialogue": "谁在那里？",
  "references": ["anna_v1_front", "old_house_v1_wide"],
  "workflow_id": "wan_video_v1",
  "seed": 12345
}
```

### RenderRun

每次生成都记录：

- 项目 ID、场景 ID、镜头 ID
- 使用的 workflow 版本
- 模型文件名和版本
- 自定义节点版本
- System Prompt 版本
- 注入 Prompt
- Seed 和全部参数
- ComfyUI 任务 ID
- 输出文件
- 错误日志
- 审核结果

这些记录是后续复现和排错的基础。

## 7. ComfyUI 工作流模板机制

参考工作流不直接改成一大段 Prompt，而是拆成四部分：

```text
workflow.json
PromptTemplate
PatchMap
ModelManifest
```

### PatchMap 示例

```json
{
  "positive_prompt": {"node": 12, "input": "text"},
  "negative_prompt": {"node": 13, "input": "text"},
  "seed": {"node": 7, "input": "seed"},
  "width": {"node": 21, "input": "width"},
  "height": {"node": 21, "input": "height"}
}
```

Agent 只生成语义字段和参数，系统根据 `PatchMap` 修改对应节点。不要依赖模糊的节点名称或全局字符串替换。

### Prompt 组装顺序

```text
视觉风格
+ 角色固定描述
+ 场景固定描述
+ 当前动作
+ 镜头语言
+ 光线和情绪
+ 负面提示词
```

角色和场景固定描述由资产库提供，不能每个镜头重新生成，否则很容易发生漂移。

## 8. Agent 状态图

```text
输入剧本
  ↓
解析剧本
  ↓
建立 ProjectBible
  ↓
生成场景和镜头表
  ↓
人工确认
  ↓
创建角色/场景参考资产
  ↓
人工确认
  ↓
生成镜头
  ↓
自动质检
  ├── 不通过 → 修改参数并重试
  └── 通过 → 保存素材
  ↓
FFmpeg 粗剪
  ↓
人工确认和导出
```

场景拆解和部分镜头生成可以并行，但角色和场景资产需要先锁定，避免多个 Agent 同时修改同一个设定。

## 9. ComfyUI API 调用流程

```text
1. Render Agent 读取 ShotSpec
2. 加载 workflow.json
3. 根据 PatchMap 注入 Prompt、Seed 和参数
4. 通过 POST /prompt 提交任务
5. 通过 WebSocket /ws 监听进度
6. 根据任务 ID 查询 /history/{prompt_id}
7. 获取 /view 输出文件
8. 写入 Asset 和 RenderRun
9. 返回 QA Agent
```

如果使用云端模型，增加 `ModelAdapter`：

```text
ShotSpec
  ├── ComfyUIAdapter
  ├── ComfyCloudAdapter
  └── ProviderAPIAdapter
```

不同生成平台都实现同一个 `submit/render/status/result` 接口，Agent 不直接绑定某一个模型平台。

## 10. 项目目录建议

```text
movie-agent/
├── app/
│   ├── api/
│   ├── agents/
│   ├── domain/
│   ├── adapters/
│   ├── workers/
│   └── main.py
├── prompts/
│   ├── script_v1.md
│   ├── storyboard_v1.md
│   ├── continuity_v1.md
│   └── qa_v1.md
├── workflows/
│   ├── wan_video_v1.json
│   └── flux_image_v1.json
├── projects/
├── tests/
└── README.md
```

## 11. 开发阶段

### Phase 1：剧本拆解

完成：

- 输入剧本
- 输出 ProjectBible
- 输出 SceneSpec 和 ShotSpec
- 支持人工修改和确认

暂时不接生成模型。

### Phase 2：单工作流生成

完成：

- 接入一个可运行的 ComfyUI 工作流
- 支持 Prompt、Seed、尺寸和参考图注入
- 生成单个镜头
- 保存运行记录

### Phase 3：多镜头生产

完成：

- 批量生成镜头
- 任务状态和进度
- 失败重试
- 角色和场景资产库
- 连续性检查

### Phase 4：粗剪成片

完成：

- 镜头排序
- 配音和背景音乐
- 字幕
- FFmpeg 导出 MP4
- 人工审核和版本对比

### Phase 5：云端和多人协作

再增加：

- 云端 GPU
- 云端模型 API
- PostgreSQL
- 对象存储
- 多用户权限
- 多 GPU 并发队列

## 12. 第一版验收标准

给定一份剧本和一个参考工作流，系统应能：

1. 生成结构化场景和镜头表。
2. 让用户修改并确认镜头计划。
3. 自动把每个镜头的参数注入 ComfyUI 工作流。
4. 批量生成至少 3 个镜头。
5. 记录每个镜头的模型、Seed、Prompt 和工作流版本。
6. 对失败任务进行重试。
7. 将通过审核的镜头合成为一个可播放视频。

## 13. 关键风险

### 一致性风险

解决方案：角色和场景资产版本化，使用参考图和固定描述，不让每个镜头独立创造角色。

### 工作流兼容风险

解决方案：保存模型清单、节点清单和工作流版本；生成前检查依赖。

### 生成结果不可复现

解决方案：记录 Seed、模型、节点版本、参数、Prompt 和硬件环境。

### Agent 失控

解决方案：所有输出通过 Pydantic 校验；Agent 只能调用白名单工具；生成和剪辑必须经过状态机。

### 成本过高

解决方案：先低分辨率预览，审核通过后再高清渲染；缓存相同参数的生成结果。

## 14. 明确不做的事情

第一版不做：

- 多 Agent 自由聊天
- 自动训练模型
- 自研视频生成模型
- 复杂节点编辑器
- 自动生成整部长片
- 一开始接入几十个模型平台
- 没有审核的无限自动重试

## 15. 最终结论

这个产品不是简单的 ComfyUI 套壳。ComfyUI 负责单个镜头的模型推理，电影 Agent 负责：

```text
理解人的意图
→ 设计电影结构
→ 管理角色和场景记忆
→ 拆分可执行镜头
→ 选择和填充工作流
→ 批量生成和检查
→ 组织素材并输出成片
```

最小可行产品应聚焦于：

> **输入剧本和参考工作流，自动生成 3～10 个连续镜头，并合成一段可播放短片。**

