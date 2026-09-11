# 电影 Agent Web 前端技术方案

## 1. 方案结论

现有 `web/index.html + styles.css + app.js` 可以继续作为功能演示，但不建议在它上面继续堆叠名导档案、Treatment 比较、镜头检查、工作流执行和渲染状态。

推荐将前端升级为一个桌面优先的电影制作工作台：

```text
Vite + React + TypeScript
+ TanStack Query 管理服务端状态
+ Motion 处理少量关键布局动画
+ CSS Variables / CSS Modules 构建设计系统
+ FastAPI 继续提供 API 与生产静态文件
```

不采用 Next.js：当前产品是登录后的创作工作台，没有 SEO 和服务端渲染需求，增加全栈框架只会重复 FastAPI 已有职责。

不引入全局状态库、Tailwind 和大型组件库：第一版由 TanStack Query 管服务端状态，React `useReducer` 管当前工作台交互，原生语义控件和少量自有组件足够。

## 2. 产品体验定位

界面不应像普通聊天机器人，也不应模仿 ComfyUI 节点编辑器。它应更接近：

> 高级电影前期制作台 + AI 导演控制室

用户始终知道三件事：

1. 当前正在决定什么。
2. Agent 为什么这样设计。
3. 下一步会生成或使哪些内容失效。

核心体验关键词：

```text
沉浸、克制、电影感、可解释、可控制、长任务不焦虑
```

## 3. 信息架构

将现有四步向导升级为七个制作阶段：

```text
01 创意 Brief
02 导演技法 Auteur
03 导演方案 Treatment
04 剧本圣经 Bible
05 分镜 Storyboard
06 生成工作台 Generate
07 粗剪 Preview
```

后端状态映射：

| 后端状态 | 前端主视图 | 用户主动作 |
|---|---|---|
| `collecting` | 创意与反问 | 回答关键问题 |
| `brief_review` | Brief 审阅 / 名导选择 | 锁定创作设定 |
| `treatment_review` | Treatment 对比 | 选择导演方案 |
| `screenplay_ready` | 项目圣经 | 审阅人物与场景 |
| `shots_review` | 分镜工作台 | 修正并确认镜头 |
| `package_ready` | 生成工作台 | 渲染镜头 |
| `rendering` | 任务坞 | 查看真实运行状态 |
| `completed` | 粗剪预览 | 播放与下载 |
| `failed` | 错误恢复 | 查看原因并重试 |

## 4. 工作台布局

桌面端采用固定四区布局：

```text
┌──────────────────────────────────────────────────────────────────┐
│ Project / 状态 / 保存时间                         GPU / Command │
├──────────┬───────────────────────────────────────┬───────────────┤
│ 制作阶段 │                                       │ Context       │
│ Rail     │          Main Creative Canvas         │ Inspector     │
│          │                                       │ Agent 理由    │
│ Brief    │  Treatment / Bible / Storyboard       │ 风险与约束    │
│ Auteur   │                                       │ 当前选择      │
│ Shots    │                                       │               │
├──────────┴───────────────────────────────────────┴───────────────┤
│ Render Task Dock：排队 / 运行 / 成功 / 失败                       │
└──────────────────────────────────────────────────────────────────┘
```

建议尺寸：

- 顶栏：64px。
- 左侧阶段栏：216px，可收起至 72px。
- 右侧检查器：320px，可隐藏。
- 底部任务坞：默认 52px，展开后最大 280px。
- 主画布最大内容宽度：1440px。

页面不使用无限宽卡片。剧本正文、表单和比较内容分别限制在适合阅读的宽度内。

## 5. 视觉系统：Obsidian Cinema

### 5.1 色彩

避免常见的蓝紫霓虹 SaaS 风格，采用黑曜石、骨白和低饱和香槟金：

```css
:root {
  --canvas: #07080c;
  --canvas-raised: #0d0f15;
  --glass: rgb(20 23 31 / 64%);
  --glass-strong: rgb(17 19 26 / 84%);
  --glass-hover: rgb(30 33 43 / 76%);
  --line: rgb(255 255 255 / 9%);
  --line-strong: rgb(255 255 255 / 16%);
  --text: #f2eee5;
  --text-secondary: #aaa8a3;
  --text-tertiary: #74747b;
  --champagne: #c8a96b;
  --champagne-soft: #e2c98f;
  --cyan: #78b9c5;
  --success: #78ad8a;
  --warning: #d49a5b;
  --danger: #c96f70;
}
```

香槟金只用于当前阶段、主按钮和确认状态；青色用于技术信息与 ComfyUI；红色只用于真实阻塞错误。

### 5.2 毛玻璃原则

毛玻璃只用于“漂浮层”：顶栏、阶段栏、检查器、弹窗和任务坞。正文卡片使用更稳定的半透明实体背景，避免整页嵌套模糊导致 GPU 开销和视觉发灰。

```css
.glass-panel {
  position: relative;
  background:
    linear-gradient(145deg, rgb(255 255 255 / 7%), transparent 42%),
    var(--glass);
  border: 1px solid var(--line);
  box-shadow:
    0 24px 80px rgb(0 0 0 / 38%),
    inset 0 1px 0 rgb(255 255 255 / 7%);
  backdrop-filter: blur(20px) saturate(125%);
  -webkit-backdrop-filter: blur(20px) saturate(125%);
}

@supports not (backdrop-filter: blur(1px)) {
  .glass-panel { background: #151820; }
}
```

限制：

- 同一区域最多一层 `backdrop-filter`。
- 不动画 `blur`、阴影半径和大面积渐变。
- 低性能设备和窄屏降级为不透明背景。
- 背景噪点使用一张静态小尺寸纹理，透明度不超过 3%，不做逐帧动画。

### 5.3 背景

页面背景由三层静态内容组成：

1. 黑曜石底色。
2. 两个低饱和径向光池，随当前阶段切换色温，但不持续运动。
3. 极弱胶片颗粒纹理。

不要使用星空粒子、跟随鼠标的大光斑、无限流动渐变。这些效果抢夺注意力，也会降低长时间编辑体验。

### 5.4 字体

- 中文正文：`Noto Sans SC` 或系统中文无衬线字体。
- 章节标题：`Noto Serif SC`，仅用于页面标题和 Treatment 名称。
- 数字、时码、镜头 ID：`JetBrains Mono` 或系统等宽字体。
- 生产部署时自托管字体子集，避免页面依赖外部字体服务。

### 5.5 圆角与空间

```text
大面板圆角 24px
普通卡片圆角 16px
按钮/输入框圆角 12px
标签圆角 999px
基础间距 4px，常用 8 / 12 / 16 / 24 / 32 / 48
```

## 6. 核心页面设计

### 6.1 创意首页

首页只保留一个强焦点：电影创意输入框。

```text
“你脑海里的第一场戏是什么？”

[ 大尺寸多行输入框                                  ]
[ 45 秒 ] [ 16:9 ] [ 悬疑 ] [ 有参考图 ]             [开始导演]
```

输入框下方展示三个真实示例，不使用自动轮播。提交后原地展开反问，不跳到传统聊天页面。

反问使用“决策卡”而不是聊天气泡：

- 问题标题。
- 为什么需要这个答案。
- 2～4 个选项。
- “交给导演决定”。
- 当前选择会影响的产物。

### 6.2 名导技法工作室

调用：

```text
GET /api/auteur-profiles
PUT /api/projects/{project_id}/auteur-profile
```

内容分三层：

1. 导演档案卡：姓名、方法摘要、研究性归纳声明。
2. 代表作模式：例如非线性身份谜题、平行时间压力、多层现实。
3. 应用控制：轻度 / 平衡 / 强烈，以及“必须保留”的内容标签。

右侧实时显示“技法预演”：

```text
原场景：男人在火车站等待女儿
技法变化：两条不等速时间线交叉
观众效果：逐渐意识到等待跨越了十年
生成方式：两个时期分别生成，通过剪辑和声音桥汇合
```

“选择”按钮文案使用“应用技法”，不使用“让诺兰替我导演”，避免造成本人参与或官方授权的误解。

### 6.3 Treatment 对比页

调用：

```text
POST /api/projects/{project_id}/treatments/generate
GET  /api/projects/{project_id}/treatments
POST /api/projects/{project_id}/treatments/{treatment_id}/confirm
```

2～3 个方案横向比较，每张卡固定展示同一组字段：

- 核心问题。
- 结构摘要。
- 视觉策略。
- 名导技法计划。
- 预期观众感受。
- 生成风险。
- 预计镜头数。

推荐方案只增加一条细金色描边和“导演推荐”，不放大尺寸，避免视觉上强迫用户。

支持“差异视图”：将三个方案相同内容折叠，只显示结构、风险和技法差异。

### 6.4 Project Bible

左侧显示角色、服装、场景、光线、色彩锁；右侧显示场景列表。每个固定字段都有锁图标：

- 金色：用户明确锁定。
- 灰色：Agent 默认，可修改。
- 红色：工作流暂不支持。

第一版只读展示已有 `ProjectBible`，修改能力等后端提供精确字段更新与影响分析后再开放。

### 6.5 Storyboard 分镜工作台

顶部是按时长比例绘制的胶片带，下面是镜头卡片列表；点击任意镜头，右侧 Inspector 显示完整信息。

镜头卡片第一屏只展示：

```text
镜头 ID / 时长 / 景别
起幅 → 主动作 → 落幅
镜头功能
名导技法标签
工作流模式
风险状态
```

更多摄影参数放进 Inspector，避免每张卡都成为字段表。

校验报告合并为统一问题栏：

- 连续性问题。
- 导演语法问题。
- 名导技法问题。

错误定位到具体镜头；点击问题自动选择镜头并高亮对应字段。警告允许继续，错误阻止确认。

编辑镜头使用右侧抽屉和显式“保存修改”。不做自动保存，因为镜头更新会让 Prompt、工作流和粗剪失效，用户需要看见这个影响。

### 6.6 生成工作台

不重做 ComfyUI 节点编辑器。每个镜头展示：

- 当前工作流名称与版本。
- 正向/负向 Prompt，可折叠。
- 分辨率、帧数、FPS、Seed。
- 工作流预检结果。
- 单镜头渲染按钮。
- 下载 patched workflow。
- 成功视频预览或失败原因。

批量渲染固定进入底部任务坞。当前后端批量接口为长请求，前端不得伪造百分比，只展示“已提交/等待服务器响应”。后端改为异步队列后，再显示真实完成数量和预计时间。

### 6.7 粗剪页

第一版只提供：播放器、总时长、镜头清单、下载按钮和制作报告。时间线拖拽、字幕轨和音频轨等后端有 EDL 接口后再实现。

## 7. 前端代码结构

```text
web/
├── index.html
├── package.json
├── vite.config.ts
├── tsconfig.json
├── src/
│   ├── main.tsx
│   ├── app/
│   │   ├── App.tsx
│   │   ├── StudioShell.tsx
│   │   └── queryClient.ts
│   ├── api/
│   │   ├── client.ts
│   │   ├── schema.d.ts
│   │   └── queries.ts
│   ├── features/
│   │   ├── brief/
│   │   ├── auteur/
│   │   ├── treatments/
│   │   ├── bible/
│   │   ├── storyboard/
│   │   ├── generation/
│   │   └── preview/
│   ├── components/
│   │   ├── Button.tsx
│   │   ├── GlassPanel.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── Dialog.tsx
│   │   └── ErrorNotice.tsx
│   └── styles/
│       ├── tokens.css
│       ├── global.css
│       └── motion.css
└── dist/                     # 构建产物，不提交源码仓库
```

每个 feature 只包含当前功能需要的组件和 hooks，不建立通用页面引擎、插件系统或二次封装的设计系统。

## 8. 数据与状态管理

### 8.1 服务端状态

TanStack Query 管理所有 API 数据：

```ts
const queryKeys = {
  project: (id: string) => ["project", id] as const,
  questions: (id: string) => ["questions", id] as const,
  auteurProfiles: ["auteur-profiles"] as const,
  treatments: (id: string) => ["treatments", id] as const,
  screenplay: (id: string) => ["screenplay", id] as const,
  shots: (id: string) => ["shots", id] as const,
  packages: (id: string) => ["packages", id] as const,
  render: (id: string) => ["render", id] as const,
};
```

变更后的失效关系与后端 Artifact 保持一致：

```text
更新 Brief
→ invalidate treatments / screenplay / shots / packages

应用名导档案
→ invalidate treatments / screenplay / shots / packages

确认 Treatment
→ invalidate screenplay / shots / packages

编辑 Shot
→ invalidate shots / packages / rough cut
```

前端不自行推测新数据，只触发重新获取。

### 8.2 本地状态

仅保存尚未提交的表单、当前选中镜头、Inspector 展开状态和 Treatment 比较模式。使用组件状态或一个 `useReducer`，不引入 Zustand/Redux。

当前项目 ID 写入 URL：

```text
/studio?project=prj_xxxxxxxx&stage=storyboard
```

刷新页面时根据项目状态恢复正确阶段，不能依赖内存中的 `currentProjectId`。

### 8.3 API 类型

从 FastAPI `/openapi.json` 生成 TypeScript 类型，并在 CI 中检查生成文件是否与后端一致。禁止手写第二套 `ShotSpec`、`CreativeBrief` 和 `AuteurProfile` 类型。

### 8.4 请求规则

- 所有请求通过一个薄 `fetch` 客户端。
- 非 2xx 响应统一解析 FastAPI `detail`。
- 页面切换时使用 `AbortSignal` 取消无用请求。
- 修改操作不自动重试，避免重复写入。
- GET 可对网络错误重试一次。
- 渲染状态只在 `pending/running` 时轮询，完成后停止。
- 不同时打开多个相同任务的轮询观察者。

## 9. 动效方案

动效服务于空间关系和状态变化，不做装饰性持续动画。

### 9.1 动效时长

```text
按钮反馈       100–140ms
卡片 hover     160ms
抽屉/弹窗      220–260ms
阶段切换       320–420ms
镜头重排       spring，仅 transform
```

### 9.2 Motion 使用边界

Motion 只用于：

- 阶段主画布切换。
- Treatment 选中后进入详情。
- Inspector 和任务坞展开。
- 镜头卡片未来的拖拽重排。

按钮 hover、边框、颜色和简单淡入全部使用 CSS transition。

### 9.3 动效性能

- 只动画 `transform` 和 `opacity`。
- 避免动画 `height: auto` 的大型列表，使用 grid rows 或显式测量。
- 不给每张镜头卡持续绑定鼠标视差。
- 视频播放时暂停非必要界面动画。
- 尊重 `prefers-reduced-motion`：关闭位移、缩放和视差，仅保留 80ms 淡入。

## 10. 响应式设计

这是生产工具，优先优化 1280px 以上桌面屏幕，但必须保证平板和手机可查看任务。

```text
>= 1280px  四区完整工作台
960–1279px 左栏收起，Inspector 变抽屉
< 960px    单列阶段页面，底部阶段导航
< 640px    只保留审阅、选择、状态查看和视频播放
```

手机端第一版不支持密集分镜编辑和工作流参数编辑，只支持反问、方案选择、渲染状态和预览。

## 11. 可访问性

- 所有交互使用 `button/input/select/dialog` 等语义元素。
- 完整键盘操作和清晰 `:focus-visible`。
- 当前步骤使用 `aria-current="step"`。
- 错误提示使用 `role="alert"`，异步状态使用 `aria-live="polite"`。
- 不仅靠颜色表达成功、警告和错误，始终配图标与文字。
- 正文对比度不低于 4.5:1。
- Dialog 打开时锁定焦点，关闭后归还触发按钮。
- 视频提供字幕轨接口预留，但不在没有字幕数据时展示虚假入口。

## 12. 性能方案

### 12.1 毛玻璃性能预算

- 同屏最多 4 个大面积模糊层。
- `blur` 建议 16–24px，不叠加。
- 滚动列表内的卡片不使用 backdrop blur。
- 移动端关闭大面积 blur。
- Chrome Performance 中滚动期间主线程长任务不得超过 50ms。

### 12.2 资源加载

- Vite 输出带 hash 的 JS/CSS。
- 名导档案封面和视频缩略图使用 AVIF/WebP。
- 非首屏图片 `loading="lazy"`。
- 视频设置 `preload="metadata"`，用户展开后再加载文件。
- 大型阶段按 feature 动态导入。
- 不对最多 30 个镜头提前引入虚拟列表；真实数据超过 100 条后再增加。

### 12.3 缓存

- `index.html`：`Cache-Control: no-cache`。
- hash 静态资源：`Cache-Control: public, max-age=31536000, immutable`。
- 项目数据由 TanStack Query 控制短期内存缓存，不写入 LocalStorage。
- 未提交草稿仅在明确需要崩溃恢复时才加入 IndexedDB。

## 13. 错误与长任务体验

统一错误结构：

```text
发生了什么
影响了什么
用户现在能做什么
技术详情（折叠）
```

示例：

```text
镜头 S01_SH04 无法进入生成
Wan 工作流最多支持 5 秒，当前镜头为 7.2 秒。
[拆分镜头] [返回编辑]
```

禁止使用浏览器 `alert()`。用三种方式替代：

- 表单字段错误：字段下方。
- 阶段阻塞错误：页面内错误卡。
- 操作完成：右下角轻量 Toast。

渲染失败必须保留已成功镜头，失败镜头提供“查看原因”和“重新执行”，不把整个页面切到通用错误页。

## 14. 安全

- React 默认文本转义，不使用 `dangerouslySetInnerHTML`。
- 制作报告 Markdown 使用不允许原始 HTML 的渲染配置，并做协议白名单。
- 所有项目 ID、镜头 ID 和下载文件名通过 API 客户端编码。
- 前端不保存 LLM Key、ComfyUI 凭证或服务端绝对路径。
- 生产添加 CSP：默认同源，只允许所需媒体、字体和 API 来源。
- 禁止将后端错误堆栈直接显示给普通用户。

## 15. 测试策略

最低测试组合：

```text
TypeScript strict + ESLint        静态约束
Vitest + Testing Library          核心组件与交互
Playwright                        三条主链路端到端
```

三条 E2E：

1. 一句话创意 → 回答问题 → 一键生成分镜。
2. 选择诺兰技法 → 选择代表作模式 → Treatment → 确认镜头。
3. 单镜头渲染失败 → 显示真实原因 → 重试 → 生成粗剪。

视觉回归只覆盖工作台壳、Treatment 比较和 Storyboard 三个高价值页面，不为每个小组件维护截图。

## 16. 构建与部署

开发环境：

```text
Vite dev server :5173
  └── /api 代理到 FastAPI :8000
```

生产环境：

```text
npm ci
npm run typecheck
npm test
npm run build
  └── web/dist

FastAPI
  ├── /api/*       API
  ├── /assets/*    Vite hash 资源
  └── /*           web/dist/index.html
```

Docker 使用多阶段构建：Node 阶段只编译前端，最终 Python 镜像只复制 `dist`，不包含 Node、源码依赖和开发服务器。

## 17. 分阶段实施

### Phase 1：工作台骨架与现有功能迁移

- 建立 Vite、React、TypeScript。
- 建立视觉 Token、GlassPanel、Button、Dialog、StatusBadge。
- 实现 URL 项目恢复和阶段导航。
- 迁移创意、反问、Brief、现有分镜和生成页。
- 删除内联 style、全局 `onclick` 和浏览器 `alert()`。

验收：现有全部流程功能不回退，刷新页面能恢复项目。

### Phase 2：名导与 Treatment 体验

- 名导档案和代表作模式选择。
- 技法强度与 preserve 锁定。
- Treatment 三栏对比与差异视图。
- 展示 technique plan、viewer effect 和免责声明。

验收：用户能完成“选择诺兰 → 平行时间压力 → Treatment → 分镜”。

### Phase 3：Storyboard 专业工作台

- 时长比例胶片带。
- 镜头选择与 Inspector。
- 三类校验报告统一定位。
- 镜头编辑、保存和下游失效提示。

验收：错误镜头不能被确认，点击错误能定位到对应镜头。

### Phase 4：生成任务与质量优化

- 单镜头任务状态轮询。
- 批量任务坞。
- 视频结果预览与失败恢复。
- 性能、键盘、移动端和视觉回归验收。

后端提供异步批量任务接口后，再升级真实批量进度；前端不模拟不存在的进度数据。

## 18. 验收指标

### 功能

- 刷新后能恢复当前项目与制作阶段。
- 所有 API 错误都有可操作提示。
- 名导技法、Treatment、镜头语法和 ComfyUI 工作流信息均可追踪。
- 上游修改后不展示已失效的下游内容。
- 重复点击不会重复提交创建、确认或渲染请求。

### 体验

- 主流程首次使用无需阅读说明文档。
- 用户在任何页面都能知道当前阶段和下一步。
- 任何超过 500ms 的操作都有状态反馈。
- 动效开启时无明显卡顿，关闭动效后功能完全可用。

### 性能

- 生产包按阶段拆分，首屏不加载 Storyboard 与播放器逻辑。
- 普通桌面设备滚动分镜时保持接近 60fps。
- 无嵌套毛玻璃导致的持续高 GPU 占用。
- 生产构建无 TypeScript 错误、无未处理 Promise rejection。

## 19. 第一版明确不做

- 不开发 ComfyUI 节点图编辑器。
- 不开发 Premiere 式多轨时间线。
- 不做多人实时协作。
- 不做可安装主题市场。
- 不用 WebSocket；当前渲染状态用条件轮询，后端任务规模增长后优先 SSE。
- 不为艺术感加入持续粒子、3D 摄像机和高耗能鼠标追踪效果。

这些功能不会提高当前“创意 → 导演方案 → 分镜 → ComfyUI”的完成率，应在核心工作台有真实使用数据后再决定。

## 20. 技术参考

- React TypeScript：https://react.dev/learn/typescript
- Vite：https://vite.dev/guide/
- TanStack Query：https://tanstack.com/query/latest/docs/framework/react/
- Motion for React：https://motion.dev/docs/react
- CSS backdrop-filter：https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/backdrop-filter
- prefers-reduced-motion：https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion
