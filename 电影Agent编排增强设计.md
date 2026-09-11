# 电影 Agent 编排增强设计

> 本文只设计 Agent 编排、结构化产物和工具调用，不涉及前端。目标是在覆盖“导演、编剧、视觉、分镜、生成、审核、剪辑”完整流程的同时，做出比常见 Movie-Agent 更可控、更可改、更节省生成成本的体验。

## 1. 产品重新定位

Movie Agent 的价值不应是“七个 Agent 同时说话”，而应是：

```text
把用户的模糊创意
→ 转换为一套可确认的导演方案
→ 编译成遵守电影语言的镜头计划
→ 根据真实模型能力生成可执行任务
→ 维护镜头之间的状态连续性
→ 允许局部改稿、局部重算和失败恢复
→ 最终生成有版本、有依据、可追踪的成片
```

系统的核心成果不是某一次生成结果，而是一个持续可编辑的 `ProductionGraph`（电影生产图）。剧本、Visual Bible、镜头、参考资产、工作流、渲染结果和剪辑时间线都是图中的版本化节点。

### 1.1 必须覆盖的基础能力

与参考 Movie-Agent 对齐：

1. 一句话创意输入。
2. 导演、编剧、视觉、分镜、生成、审核、剪辑七类职责。
3. 故事规划和剧本拆解。
4. Visual Bible。
5. Storyboard 和 ShotSpec。
6. ComfyUI 镜头生成。
7. 连续性质检。
8. 时间线剪辑。
9. 声音、配音和字幕计划。
10. Final Cut 输出。
11. 流程可修改、可恢复、可追踪。

### 1.2 应形成差异的增强能力

1. 不直接给唯一剧本，而是先给 2～3 个“导演方案”供选择。
2. 使用可执行的“导演语法包”，而不是只有风格形容词。
3. 在定稿前检查镜头是否能被当前 ComfyUI 工作流实现。
4. 连续性不是生成后找错，而是在每个镜头间传递状态。
5. 用户改一句话时，系统先计算影响范围，只重算必要节点。
6. 每个高风险镜头同时有“稳定方案”和“野心方案”。
7. QA 必须依据 ShotSpec 和连续性证据评分，不能只回答“画面不错”。

## 2. 重新整理“镜头语言风格模板”

你想表达的内容可以命名为：

> **导演语法包（Directing Grammar Pack）**

它是一套可机器执行的电影表达规则，规定“这种片子通常如何讲、如何拍、如何剪、如何听”，而不只是给 Prompt 加上“电影感、35mm、唯美”等词。

### 2.1 一个完整制作包的组成

```text
Film Production Pack
├── Narrative Pattern       叙事结构模板
├── Directing Grammar       镜头语言和场面调度规则
├── Visual Style Bible      视觉、色彩、材质和角色一致性规则
├── Generation Recipe       ComfyUI 工作流与模型能力映射
├── Editing Rhythm          剪辑节奏和转场规则
└── Sound Grammar           对白、声音、音乐和静默规则
```

第一版只需要真正实现 `Directing Grammar + Generation Recipe`，其余字段先作为结构化数据供编剧、分镜和剪辑阶段读取。

### 2.2 Narrative Pattern：叙事结构模板

它描述短片的时间如何分配，不直接写剧情。

例如“45 秒悬疑预告片”：

```yaml
narrative_pattern:
  id: mystery_trailer_45s
  duration_range: [35, 60]
  beats:
    - role: hook
      ratio: 0.12
      purpose: 用异常画面或声音立即制造问题
    - role: setup
      ratio: 0.18
      purpose: 建立人物、目标和空间
    - role: escalation
      ratio: 0.38
      purpose: 用线索、阻碍和节奏升级扩大危机
    - role: rupture
      ratio: 0.20
      purpose: 出现反转、威胁或视觉高潮
    - role: sting
      ratio: 0.12
      purpose: 用最后一个信息点留下悬念
```

它解决的问题是：不同类型的短片不应该使用同一套“平均分成十个镜头”的方法。

### 2.3 Directing Grammar：导演语法

它描述镜头之间如何形成语义。

```yaml
directing_grammar:
  id: neo_noir_suspense
  name: 新黑色悬疑
  intent: 通过信息遮蔽、空间压迫和延迟揭示制造不安

  shot_vocabulary:
    preferred_sizes: [WS, MCU, CU, ECU]
    discouraged_sizes: [MLS]
    preferred_lenses: [28mm, 40mm, 75mm]
    camera_height: eye_or_low
    movement_budget: restrained

  sequence_patterns:
    reveal:
      - establish_obscured_space
      - insert_clue
      - reaction_hold
      - delayed_source_reveal
    confrontation:
      - spatial_master
      - asymmetric_closeup_a
      - withheld_reverse
      - detail_of_threat

  composition_rules:
    - 保留大量负空间，威胁可来自画外
    - 人物视线空间优先于居中构图
    - 同一段落避免连续三个相同景别

  movement_rules:
    - 正常调查使用固定镜头或不可察觉推进
    - 信息确认时才允许明显推进
    - 追逐段每四个镜头最多一个复杂运镜

  transition_rules:
    - 动作连续优先硬切
    - 时间跳跃可使用声音桥接
    - 禁止无叙事目的的叠化

  continuity_rules:
    axis_policy: preserve_180_degree_axis
    screen_direction: locked_per_sequence
    eyeline_match: required_for_dialogue

  forbidden_patterns:
    - 每个镜头都使用环绕运镜
    - 景别随机变化但没有信息目的
    - 为追求炫技破坏人物位置关系
```

### 2.4 Visual Style Bible：视觉风格模板

视觉模板只描述稳定的视觉约束，不包含当前镜头动作。

```yaml
visual_style:
  palette:
    dominant: [深蓝, 炭黑]
    accents: [低比例品红, 钠灯橙]
  contrast: high
  saturation: low
  texture: wet_asphalt_and_35mm_grain
  lighting:
    key: motivated_practical_light
    fill: minimal
    atmosphere: rain_mist
  skin_tone_policy: natural_not_neon
  forbidden:
    - 大面积高饱和霓虹铺满画面
    - 每个镜头使用不同调色方案
```

### 2.5 Generation Recipe：生成方案模板

它把电影语言映射到现有 ComfyUI 能力。

```yaml
generation_recipe:
  preferred_mode: image_to_video
  workflow_id: wan_i2v_v1
  capability_limits:
    max_duration_seconds: 5
    accepted_references: [first_frame, character]
    unsupported: [precise_lip_sync, two_complex_actions, last_frame_lock]
  prompt_policy:
    one_primary_action: true
    camera_motion_terms: controlled_vocabulary
    preserve_character_description_verbatim: true
  fallback_rules:
    - when: precise_lip_sync_required
      action: change_to_voiceover_or_reaction_shot
    - when: action_too_complex
      action: split_into_two_shots
    - when: duration_exceeds_limit
      action: split_on_action_boundary
```

### 2.6 Editing Rhythm：剪辑节奏模板

```yaml
editing_rhythm:
  average_shot_length: 3.8
  opening_shot_range: [2.0, 4.0]
  climax_shot_range: [1.2, 2.8]
  max_same_pace_run: 3
  cut_preferences: [action_cut, eyeline_cut, sound_bridge, hard_cut]
  music_sync: structural_only
```

### 2.7 Sound Grammar：声音语法模板

```yaml
sound_grammar:
  perspective: subjective_protagonist
  ambience_layers: [rain, distant_traffic, electrical_hum]
  signature_cues:
    clue_reveal: high_frequency_tone
    threat_appearance: low_frequency_impact
  silence_rules:
    - 高潮信息出现前保留 0.3～0.8 秒局部静默
  dialogue_policy:
    max_words_per_5_seconds: 12
    prefer_voiceover_when_lip_sync_is_unavailable: true
```

## 3. 模板不是“复制风格”，而是“约束生成”

模板必须分成三种强度：

```text
LOCK       必须遵守，例如角色服装、画幅、轴线方向
PREFER     优先采用，例如景别比例、镜头长度
AVOID      尽量避免，例如无意义环绕、连续相同景别
```

每条规则都需要：

- `rule_id`：稳定 ID。
- `scope`：project、sequence、scene 或 shot。
- `strength`：LOCK、PREFER、AVOID。
- `reason`：它服务的叙事目的。
- `validator`：能否由代码检查。
- `repair`：违反后应如何修正。

示例：

```yaml
- rule_id: no_three_same_sizes
  scope: sequence
  strength: AVOID
  reason: 防止镜头信息密度和视觉节奏单一
  validator: adjacent_shot_size_run <= 2
  repair: 将中间镜头改为反应特写或环境插入镜头
```

LLM 负责在规则内创作，代码负责检查可确定的规则。不要让 LLM 同时制定规则、执行规则并判断自己是否合格。

## 4. 七类职责如何真正编排

系统可以对用户称为七个 Agent，但实现上应是一个 Orchestrator 调用七种角色能力。每个角色只接收所需上下文，并输出固定 Schema。

| 角色能力 | 核心输入 | 核心输出 | 不允许做的事 |
|---|---|---|---|
| Director | 用户输入、限制、模板目录 | CreativeBrief、TreatmentOption、创作锁 | 直接渲染 |
| Writer | 已确认 Treatment、叙事模板 | Screenplay、StoryBeat | 决定模型和节点 |
| Visual | 剧本、参考图、视觉模板 | VisualBible、角色/场景资产任务 | 随镜头改变角色版本 |
| Storyboard | 剧本、导演语法、VisualBible | SequenceSpec、ShotSpec | 使用未声明的工作流能力 |
| Generation | ShotSpec、资产、能力清单 | ShotExecutionPlan、workflow JSON | 修改故事内容 |
| Review | ShotSpec、连续性状态、输出素材 | QAReport、重做指令 | 以个人审美替代规则 |
| Editor | 通过审核的素材、节奏和声音模板 | EDL、AudioPlan、SubtitlePlan、FinalCut | 使用未通过审核的镜头 |

## 5. 总状态机

```text
intake
  ↓
clarifying
  ↓
treatment_review          用户选择导演方案
  ↓
screenplay_review         用户确认故事结构
  ↓
visual_bible_review       锁定角色、场景和风格
  ↓
storyboard_review         确认镜头计划
  ↓
production_preflight      检查模型、节点、时长和参考资产
  ↓
preview_rendering         低成本生成候选
  ↓
shot_review               自动 QA + 用户选择
  ├── revise_plan         修改 ShotSpec 后局部重算
  ├── retry_render        保持 ShotSpec，只改生成参数
  └── accept
  ↓
final_rendering
  ↓
editing                   EDL、声音、字幕和混音
  ↓
final_review
  ↓
completed
```

状态只能由 Orchestrator 修改。专业角色返回结果或建议，不能自行跳过确认点。

## 6. 差异化功能一：导演方案分叉

普通系统收到一句创意后立刻写一个剧本，过早锁死方向。增强版先输出 2～3 个 `TreatmentOption`。

例如用户输入：

> 一个宇航员在废弃空间站里发现另一个自己。

Agent 可以返回：

```json
{
  "options": [
    {
      "treatment_id": "psychological",
      "name": "心理悬疑",
      "core_question": "另一个自己是真实存在还是缺氧幻觉？",
      "structure": "缓慢建立空间异常，最后停在身份反转",
      "visual_strategy": "长焦压缩、固定镜头、反射和遮挡",
      "production_risk": "low",
      "estimated_shots": 8
    },
    {
      "treatment_id": "survival",
      "name": "生存追逐",
      "core_question": "两个自己中谁能离开空间站？",
      "structure": "快速冲突、追逐、气闸高潮",
      "visual_strategy": "广角手持、短镜头、强运动",
      "production_risk": "high",
      "estimated_shots": 13
    }
  ],
  "recommendation": "psychological",
  "recommendation_reason": "更适合当前 45 秒时长，也更容易维持单角色双重身份的一致性"
}
```

这不是多生成几份完整剧本。每个 Treatment 只保留影响选择的摘要，用户选定后才继续展开。

## 7. 差异化功能二：自适应创作诊断

反问不只补字段，还要识别“创作方向”和“生产难度”的矛盾。

问题分四类：

1. 叙事阻塞：主角、目标、冲突、结局。
2. 体验选择：紧张、浪漫、荒诞、纪实等观感。
3. 生产约束：时长、画幅、参考图、可用模型、显存。
4. 风险冲突：多人打斗、复杂口型、文字生成、连续长镜头等。

反问策略：

```text
先问会改变故事的问题
→ 再问会改变导演方案的问题
→ 最后只问会阻塞生成的问题
→ 其他内容使用显式默认值
```

每轮最多三问，且问题必须给出影响说明。用户说“你决定”后，Agent 应记录一条 `CreativeDecision`：

```json
{
  "decision_id": "dec_014",
  "field": "dialogue_mode",
  "value": "voiceover",
  "source": "agent_default",
  "reason": "当前工作流没有稳定口型能力",
  "locked": false
}
```

## 8. 差异化功能三：电影语言编译器

Storyboard Agent 不应直接“凭感觉”生成 ShotSpec。它先选择 Sequence Pattern，再将每个叙事 Beat 编译成镜头功能。

### 8.1 编译过程

```text
StoryBeat
→ 选择 SequencePattern
→ 分配每个镜头的 narrative_purpose
→ 应用景别、轴线、视线和运动规则
→ 分配时长预算
→ 检查相邻镜头语法
→ 输出 ShotSpec
```

### 8.2 ShotSpec 新增字段

```json
{
  "shot_id": "s01_sh04",
  "beat_id": "beat_reveal_02",
  "grammar_pack_id": "neo_noir_suspense_v1",
  "sequence_pattern": "reveal",
  "shot_function": "reaction_hold",
  "information_revealed": "主角认出照片中的人是自己",
  "information_withheld": "照片拍摄者身份",
  "screen_direction": "left_to_right",
  "axis_id": "axis_corridor_01",
  "entry_state_id": "state_s01_sh03_out",
  "exit_state_id": "state_s01_sh04_out"
}
```

这些字段让系统知道镜头为什么存在，并能判断删除或替换它会破坏什么。

### 8.3 确定性语法检查

- 镜头总时长是否守恒。
- 单镜头是否超过工作流能力。
- 是否连续三个以上相同景别。
- 对话正反打是否满足视线和轴线。
- 同一段落是否存在多个互相冲突的主运镜。
- 镜头是否只包含一个主要可观察动作。
- 每个镜头是否揭示、隐藏或强化至少一个信息点。
- 删除镜头后，故事 Beat 是否仍被覆盖。

## 9. 差异化功能四：生成可行性前置编译

普通流程先写理想分镜，再在 ComfyUI 阶段失败。增强流程在 Storyboard 定稿前生成 `ShotFeasibilityReport`。

```json
{
  "shot_id": "s02_sh06",
  "feasibility": "risky",
  "score": 0.58,
  "reasons": [
    "镜头包含两个人物快速肢体接触",
    "要求 8 秒连续环绕运镜，超过当前模板稳定区间",
    "需要角色对白口型同步"
  ],
  "stable_rewrite": {
    "action": "先用手部特写表现争夺，再切到人物反应",
    "split_into": 2
  },
  "required_capabilities": ["multi_character_reference", "lip_sync"]
}
```

### 9.1 两轨镜头计划

对 `risky` 镜头给出：

- `hero_plan`：创作效果最好，但生成风险高。
- `safe_plan`：叙事信息不变，降低人物、动作和运镜复杂度。

默认先生成 safe preview。用户明确选择后再尝试 hero plan。它能减少把 GPU 时间浪费在明显不可执行的镜头上。

### 9.2 风险评分维度

```text
人物数量
+ 动作数量和肢体接触
+ 运镜复杂度
+ 镜头时长
+ 口型精度
+ 文字或标识要求
+ 首尾帧约束
+ 参考资产完整度
+ 当前工作流历史成功率
```

第一版采用规则分数，不训练预测模型。积累足够 RenderRun 后再用历史数据校准权重。

## 10. 差异化功能五：连续性状态账本

连续性不能只靠把上一张图当参考图。每个镜头都应读取 `entry_state`，并产出 `exit_state`。

```json
{
  "state_id": "state_s01_sh04_out",
  "shot_id": "s01_sh04",
  "characters": {
    "anna_v1": {
      "costume": "coat_v1_wet",
      "position": "corridor_left_wall",
      "facing": "camera_right",
      "emotion": "recognition_shock",
      "held_props": ["photo_v1"]
    }
  },
  "props": {
    "photo_v1": {
      "owner": "anna_v1",
      "condition": "wet_corner_torn",
      "visible_information": "portrait_revealed"
    }
  },
  "environment": {
    "location_id": "corridor_v1",
    "lighting_state": "emergency_red_pulse",
    "weather": null
  },
  "camera": {
    "axis_id": "axis_corridor_01",
    "screen_direction": "left_to_right"
  }
}
```

### 10.1 状态传递规则

- 下一镜头默认继承上一镜头全部状态。
- ShotSpec 只能声明发生变化的字段。
- 道具损坏、服装变湿、人物换位等变化必须由画面动作或场间跳转解释。
- QA 同时检查生成画面与 `expected_exit_state`。
- 用户接受镜头后，实际观察结果写入 `observed_exit_state`，下一镜头以它为准。

这使连续性从“事后发现错误”变成“生成前约束 + 生成后校准”。

## 11. 差异化功能六：改稿影响图和局部重算

用户修改内容时，Agent 先返回 `ChangeImpact`，不立即重做全部内容。

用户指令：

> 把主角的红色风衣改成白色，但雨夜和悬疑感不变。

系统返回：

```json
{
  "change_id": "chg_023",
  "parsed_change": {
    "target": "anna_v1.fixed_costume",
    "from": "red trench coat",
    "to": "white trench coat"
  },
  "preserved_locks": ["rainy_night", "mystery_tone", "story_structure"],
  "affected": {
    "visual_bible": ["anna_v1"],
    "shots": ["s01_sh01", "s01_sh02", "s02_sh03"],
    "prompts": ["s01_sh01", "s01_sh02", "s02_sh03"],
    "renders": ["run_101", "run_102", "run_207"],
    "timeline": []
  },
  "unaffected": ["screenplay", "dialogue", "music_plan"],
  "estimated_rerenders": 3,
  "requires_confirmation": true
}
```

### 11.1 依赖传播规则

```text
故事主题变更
→ Treatment、Screenplay、VisualBible、Shots、Render、Edit 全部失效

角色外观变更
→ 角色资产、相关 Shots Prompt、相关 Render 失效

单镜头动作变更
→ 当前 Shot、当前 Render、相邻连续性、时间线时长失效

单次生成参数变更
→ 仅当前 Render 失效

字幕文字修正
→ SubtitlePlan 和 FinalCut 失效，镜头素材不失效
```

### 11.2 修改操作必须可撤销

每次改稿创建新 artifact 版本，不覆盖已确认版本：

```text
branch/main/v12
  └── change/chg_023/v13
       ├── accept → main/v13
       └── reject → main/v12
```

第一版只需要线性版本和撤销到上一确认点，不必实现 Git 式任意分支合并。

## 12. Visual Agent 的实际职责

Visual Agent 不是写更多风格词，而是生成并锁定可复用资产规范。

### 12.1 VisualBible 输出

```text
项目视觉规则
角色定妆规格
角色视图需求：正面、侧面、全身、表情
场景空间规格：平面关系、入口、出口、光源
关键道具规格
色彩和材质约束
角色与场景参考资产版本
禁止漂移字段
```

### 12.2 资产生成顺序

```text
角色文字设定
→ 角色候选图
→ 用户/QA 选择
→ 生成角色多视图参考
→ 锁定 character_asset_version

场景文字设定
→ 场景概念图
→ 生成主角度与反打角度
→ 锁定 location_asset_version
```

未锁定 VisualBible 时，不允许并行生成正式镜头。

## 13. Generation Agent 的实际职责

Generation Agent 保持低创造性，只执行计划。

每个镜头先生成 `ShotExecutionPlan`：

```json
{
  "shot_id": "s01_sh04",
  "workflow_id": "wan_i2v_v1",
  "workflow_version": "1.0.0",
  "reference_bindings": {
    "first_frame": "asset_anna_corridor_v3",
    "character": "asset_anna_sheet_v2"
  },
  "prompt_package_version": 7,
  "render_ladder": [
    {"stage": "draft", "resolution": "480p", "candidates": 2},
    {"stage": "selected", "resolution": "720p", "candidates": 1},
    {"stage": "final", "resolution": "1080p", "candidates": 1}
  ],
  "estimated_gpu_seconds": 80,
  "fallback_plan_id": "s01_sh04_safe"
}
```

### 13.1 渲染阶梯

```text
Draft Preview     低分辨率检查动作和构图
→ Candidate       选择 Seed 和参考资产组合
→ Final Render    只对已选择候选进行高质量生成
→ Post Process    插帧、放大、去闪烁等确定性后处理
```

不同阶段使用同一个 `ShotSpec`，只改变生成参数，避免候选和最终镜头语义漂移。

## 14. Review Agent 的实际职责

QA 必须输出证据化报告：

```json
{
  "shot_id": "s01_sh04",
  "decision": "retry",
  "scores": {
    "spec_alignment": 0.91,
    "character_consistency": 0.62,
    "motion_quality": 0.74,
    "continuity": 0.86,
    "technical_quality": 0.80
  },
  "issues": [
    {
      "type": "character_costume_drift",
      "evidence": "人物右袖由白色变成黑色",
      "frames": [42, 56],
      "severity": "error"
    }
  ],
  "repair": {
    "scope": "render_parameters",
    "keep_seed": true,
    "prompt_patch": "preserve white sleeves throughout",
    "requires_shot_rewrite": false
  }
}
```

### 14.1 QA 路由

```text
构图、动作或叙事不符合 ShotSpec
→ 返回 Storyboard Agent 改镜头

角色漂移、闪烁、肢体错误
→ 返回 Generation Agent 改参数或参考资产

相邻镜头衔接错误
→ 返回 Continuity 处理，最多影响相邻镜头

仅色彩或声音问题
→ 进入后期修正，不重做画面
```

自动 QA 不应直接“接受”高成本最终镜头。它可以淘汰明显失败结果，并推荐候选，最终接受权由用户或明确配置决定。

## 15. Editor Agent 的实际职责

Editor Agent 输出结构化剪辑决策，而不是直接写 FFmpeg shell。

### 15.1 EditDecisionList

```json
{
  "timeline_version": 4,
  "fps": 24,
  "tracks": {
    "video": [
      {
        "shot_id": "s01_sh01",
        "asset_id": "asset_run_301",
        "source_in": 0.2,
        "source_out": 3.8,
        "timeline_in": 0.0,
        "transition_out": "hard_cut"
      }
    ],
    "dialogue": [],
    "voiceover": [],
    "music": [],
    "effects": []
  }
}
```

FFmpeg 只执行已经校验的 EDL。

### 15.2 声音和字幕

声音拆成：

- `DialoguePlan`：角色、文本、情绪、时长、口型需求。
- `VoiceoverPlan`：旁白文本和时间区间。
- `SoundEffectPlan`：画内音、画外音、环境音和转场音。
- `MusicPlan`：节拍点、情绪段落、淡入淡出。
- `SubtitlePlan`：文本、语言、时间码和安全区。

字幕时间由最终音频时长生成，不使用剧本阶段的预估时间。

## 16. Orchestrator 的决策规则

Orchestrator 只做以下事情：

1. 校验当前状态允许什么操作。
2. 组装当前角色需要的最小上下文。
3. 调用角色 Prompt 或确定性工具。
4. 校验结构化输出。
5. 记录决策、版本和依赖。
6. 根据错误类型路由到正确阶段。
7. 在人工确认点停止。

它不编写剧本、不生成图像，也不替 QA 判断画面。

### 16.1 最小上下文注入

| 角色 | 注入内容 |
|---|---|
| Director | 原始输入、已回答问题、生产限制、可用模板摘要 |
| Writer | 已确认 Treatment、CreativeLocks、NarrativePattern |
| Visual | 剧本中的角色/场景、VisualStyle、参考资产 |
| Storyboard | StoryBeat、DirectingGrammar、VisualBible、能力限制 |
| Generation | 单个 ShotSpec、相关状态、相关资产、WorkflowProfile |
| Review | ShotSpec、entry/exit state、生成素材、相邻镜头摘要 |
| Editor | 已接受素材、EditingRhythm、SoundGrammar、目标时长 |

不得把完整聊天历史和全部项目文件发送给每个角色。

## 17. 需要新增的核心数据结构

```text
FilmProductionPack
NarrativePattern
DirectingGrammar
VisualStyle
EditingRhythm
SoundGrammar

TreatmentOption
CreativeDecision
CreativeLock
StoryBeat
SequenceSpec

ShotFeasibilityReport
ShotExecutionPlan
ContinuityState
ObservedShotState

QAReport
ChangeRequest
ChangeImpact
EditDecisionList
AudioPlan
SubtitlePlan
```

不要一次把所有结构都做完。第一批只实现：

```text
DirectingGrammar
TreatmentOption
CreativeDecision
ShotFeasibilityReport
ContinuityState
ChangeImpact
```

## 18. Artifact 与依赖图

```text
CreativeBrief
  └── Treatment
       ├── Screenplay
       │    ├── VisualBible
       │    │    └── ReferenceAssets
       │    └── StoryBeats
       │         └── ShotList
       │              ├── ContinuityStates
       │              ├── FeasibilityReports
       │              └── PromptPackages
       │                   └── RenderRuns
       │                        └── AcceptedAssets
       └── ProductionPack
                            AcceptedAssets
                                  └── EDL
                                       ├── AudioPlan
                                       ├── SubtitlePlan
                                       └── FinalCut
```

每个 artifact 记录：

- `artifact_id`、`kind` 和 `version`。
- `parent_versions`：它依赖的精确版本。
- `status`：draft、confirmed、stale、failed。
- `created_by`：user、director、writer、tool 等。
- `prompt_version` 和模型信息。
- 内容哈希。

下游只允许读取 `confirmed` 且父版本仍有效的 artifact。

## 19. 错误恢复和可恢复执行

### 19.1 Checkpoint

在以下阶段保存恢复点：

```text
treatment_confirmed
screenplay_confirmed
visual_bible_confirmed
storyboard_confirmed
shot_accepted
timeline_confirmed
```

服务重启后，Orchestrator 从最后一个合法 checkpoint 恢复，不重新调用已经成功的 LLM 或 ComfyUI 任务。

### 19.2 幂等键

```text
artifact parent versions
+ prompt version
+ workflow version
+ reference asset hashes
+ seed and generation parameters
```

相同幂等键已有成功结果时直接复用。

### 19.3 重试边界

- 网络错误：自动重试。
- Schema 错误：修复调用一次。
- 缺模型或节点：不重试。
- 生成质量问题：创建新 RenderRun，不覆盖旧结果。
- 故事或镜头问题：返回上游，不靠增加负面词掩盖。

## 20. 建议新增的 Agent 工具

```text
list_production_packs()
get_pack_summary(pack_id)
validate_directing_grammar(shot_list, pack_id)
estimate_shot_feasibility(shot, workflow_profiles)
build_continuity_state(previous_state, shot_delta)
compare_observed_state(expected_state, media)
calculate_change_impact(change_request, production_graph)
invalidate_descendants(artifact_ids)
create_render_candidates(shot_execution_plan)
build_edl(accepted_assets, editing_rhythm)
validate_edl(edl, target_duration)
```

其中能确定计算的工具使用普通代码；只有语义理解、创意方案和视觉判断使用 LLM 或视觉模型。

## 21. 对当前代码的最小落地方式

保持现有 `ProjectService` 主入口，不创建七个常驻 Agent 类。

### 21.1 第一批文件变化

```text
新增：
  agent/production_packs.py        加载和校验导演语法包
  production_packs/*.yaml         模板内容

修改：
  agent/models.py                 增加第一批 Schema
  agent/llm.py                    增加 Treatment 与状态抽取调用
  agent/service.py                增加状态和编排步骤
  agent/continuity.py             从告警升级为状态传递
  agent/workflow.py               增加可行性检查
```

不要新增 `director_agent.py`、`writer_agent.py` 等七个只有一层转发的类。角色差异先由 Prompt、输入 Schema 和状态权限表达。

### 21.2 新增状态

```python
ProjectStatus = Literal[
    "collecting",
    "brief_review",
    "treatment_review",
    "screenplay_review",
    "visual_bible_review",
    "shots_review",
    "preflight_review",
    "preview_rendering",
    "shot_review",
    "editing",
    "final_review",
    "completed",
    "failed",
]
```

### 21.3 新增编排方法

```python
generate_treatments(project_id)
confirm_treatment(project_id, treatment_id)
select_production_pack(project_id, pack_id)
build_visual_bible(project_id)
run_storyboard_preflight(project_id)
get_change_impact(project_id, instruction)
apply_change(project_id, change_id)
accept_render(project_id, shot_id, render_id)
build_edit_plan(project_id)
```

方法名称是用例，不需要为每个方法再包一层 Agent 类。

## 22. 分阶段实现顺序

### Phase A：导演语法和方案选择

实现：

- 3 个 Production Pack：悬疑预告、情绪短片、动作追逐。
- 每个 Pack 有叙事节拍、镜头语法和生成限制。
- Director 生成最多 3 个 TreatmentOption。
- 用户确认 Treatment 和 Production Pack。
- Storyboard 根据语法生成并校验镜头。

验收：同一个故事选择不同 Pack 后，镜头结构、景别、节奏和转场有可解释差异，而不是只更换风格词。

### Phase B：可行性和连续性状态

实现：

- ShotFeasibilityReport。
- hero/safe 两轨镜头方案。
- ContinuityState 的 entry/exit 传递。
- 镜头生成前依赖检查。

验收：系统能在提交 ComfyUI 前识别超时长、复杂动作、口型和参考能力缺失，并提供保留叙事意义的稳定改写。

### Phase C：局部改稿和恢复

实现：

- ChangeRequest 语义解析。
- ChangeImpact 依赖传播。
- 用户确认后只让下游 artifact 失效。
- 从 checkpoint 恢复。

验收：修改一名角色服装时，不重写剧本、不重做无关镜头，只标记相关资产、Prompt 和 RenderRun。

### Phase D：QA、剪辑和声音

实现：

- 证据化 QAReport。
- 镜头候选接受机制。
- EDL、AudioPlan、SubtitlePlan。
- FFmpeg 确定性执行。

验收：Final Cut 只能引用已接受且版本有效的镜头；字幕时间基于最终音频；修改字幕不会触发画面重做。

## 23. 第一批模板建议

### 23.1 悬疑预告片

- 核心：信息延迟、遮挡、反应镜头、声音桥。
- 适合：侦探、惊悚、科幻谜团。
- 低风险：单角色、少对白、固定或缓推镜头。

### 23.2 情绪叙事短片

- 核心：环境细节、人物微动作、视觉母题、留白。
- 适合：爱情、成长、回忆、公益。
- 低风险：旁白、少场景、慢节奏、静态构图。

### 23.3 动作追逐短片

- 核心：方向连续、动作匹配剪辑、远中近节奏组合。
- 适合：追车、逃亡、战斗预告。
- 高风险：多人接触、快速运动和复杂镜头需要自动拆分。

先做这三套即可，它们能验证模板是否真的改变电影语言。

## 24. 衡量功能是否“有实际意义”

不要用 Agent 数量衡量。记录以下指标：

```text
用户确认 Treatment 前的平均反问轮数
用户第一次接受的镜头计划比例
进入 ComfyUI 后因能力不支持而失败的镜头比例
每个被接受镜头的平均渲染次数
角色/道具连续性错误率
一次修改导致的平均失效镜头数
从中断到恢复所需的重复调用数
最终成片中使用的生成素材比例
```

增强功能有效时，应看到：无效渲染减少、局部修改范围缩小、镜头接受率提高，而不是生成了更多中间文本。

## 25. 第一条增强纵向切片

第一版增强功能只跑通这条链：

```text
一句创意
→ 最多三轮反问
→ 生成两个 Treatment
→ 用户选择 Treatment
→ 选择一个 Directing Grammar Pack
→ 生成 5～8 个带 shot_function 的镜头
→ 语法检查 + ComfyUI 可行性检查
→ 每个高风险镜头给出 safe rewrite
→ 用户修改一个镜头
→ 系统只让该镜头和相邻连续性失效
→ 编译可执行 PromptPackage 和 workflow JSON
```

这条链跑通，就已经比“七个 Agent 顺序生成一堆文本”更有产品意义。Visual Bible、自动 QA、声音和 Final Cut 在这条链稳定后依次接入。

## 26. 明确暂不实现

- 七个 Agent 自由群聊或互相辩论。
- 用户风格的长期跨项目记忆。
- 自动学习导演风格或训练 LoRA。
- 任意工作流节点图自动生成。
- 自动接受最终镜头。
- 复杂分支合并和多人协作权限。
- 为所有电影类型一次性制作模板。

这些功能等核心链路有真实使用数据后再决定，不进入第一批开发。

## 27. 名导技法模式

名导功能定义为 `AuteurTechniqueProfile`，用于提取公开作品中的通用电影技法，不把导演姓名直接写进生成 Prompt，也不复制具体作品的人物、对白或标志性场面。

```text
AuteurProfile                 导演级档案
└── AuteurVariant             代表作方法分型
    └── AuteurTechnique       可执行的叙事/摄影/剪辑/声音规则
```

项目选择记录为：

```json
{
  "profile_id": "christopher_nolan_technique_study",
  "variant_id": "parallel_time_pressure",
  "intensity": "balanced",
  "preserve": ["主角身份", "火车站", "父女重逢结局"]
}
```

编排链路：

```text
选择名导档案与代表作模式
→ 生成带 technique_plan 的 Treatment
→ 将技法落实为场景顺序和动作
→ ShotSpec 记录 technique_ids 与 technique_rationale
→ Auteur Validator 检查档案绑定和无效技法
→ 通过后继续编译 ComfyUI 工作流
```

名导档案与 `FilmProductionPack` 独立叠加：前者控制创作方法，后者控制类型镜头语法与生成能力。第一版内置诺兰技法研究档案，包含非线性身份谜题、多层现实、平行时间压力、宏大尺度中的私人情感四种代表作模式。

后端接口：

```text
GET    /api/auteur-profiles
PUT    /api/projects/{project_id}/auteur-profile
GET    /api/projects/{project_id}/auteur-profile
DELETE /api/projects/{project_id}/auteur-profile
```
