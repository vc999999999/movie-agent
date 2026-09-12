---
title: 幕间 - 剧情到 ComfyUI 工作流
emoji: 🎬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 幕间

输入剧情或场景 Prompt，确认拆解结果，选择导演模板和方案，生成完整制作资料并导出 ComfyUI 工作流包。在线视频渲染和粗剪是可选功能。

## 主流程

1. **剧情拆解**：输入场景／大纲／剧本，补充问题或采用默认设定，编辑并确认简报。
2. **导演模板**：选择原创模式，或名导技法模式、强度和必须保留的内容。内置都市情绪、悬疑信息控制、对称舞台构图、日常生活观察四套原创模板（各 2 种模式），以及诺兰技法档案的 4 种模式，共 5 套模板、12 种模式。
3. **导演方案**：比较生成的候选方案，由用户明确选择。系统不会替用户选择推荐方案。
4. **制作流程**：后台生成角色、场景、剧本、分镜、提示词及工作流。可查看进度、审阅分镜并编辑；错误后重试已有流程的未完成步骤。
5. **导出工作流**：下载 ZIP；按说明准备素材，在接收者自己的 ComfyUI 上运行。

确认简报只保存设定；确认导演方案只保存选择；`auto_pipeline` 只生成制作资料，到 `package_ready` 结束。它不会渲染视频，也不会生成粗剪。`completed` 保留为可选粗剪的旧状态，现有项目无需迁移数据库。

## 导出包

- `README.md`：使用顺序及未完成项。
- `manifest.json`：完整性、各镜头文件、素材与依赖。
- `brief.json`、`screenplay.json`、`shots.json`：剧情、人物场景、剧本和分镜。
- `prompts.json`、`production_report.md`：正负提示词、参数和制作报告。
- `auteur_profile.json`、`selected_treatment.json`、`production_pack.json`：已选择的模板／方案（存在时导出）。
- `workflows/ui/*.json`：可拖入 ComfyUI 的可视化工作流，当前由官方 Wan 原生图生视频模板提供。
- `workflows/api/*.json`：已注入镜头参数的 API 工作流，供 `/prompt` 使用。
- `assets/requirements.json`：逐镜头首帧提示词、文件名和尺寸；实际图片需用户准备。
- `dependencies/models_and_nodes.json`：所需模型及节点；不包含模型权重。

导出不连接服务器的 ComfyUI、不检查服务器显存。模板匹配与参数编译不等于实际渲染验证。部分不匹配镜头在清单中明确标记，不会伪造工作流。旧模板若没有 UI 版本，仅提供 API 文件。旧 Wan 工作流须重新编译才能用升级后的 UI 模板导出。

Wan 模板依据 [ComfyUI 官方示例](https://comfyanonymous.github.io/ComfyUI_examples/wan/) 更新，补齐文本编码器、VAE、视觉编码和原生采样链路；帧数按 4n+1 对齐。UI 与 API 文件使用同一组节点和参数。参考来源记录在 `workflows/wan_i2v_v1/SOURCE.md`。实际模型效果、显存和执行仍需在目标机器验证。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm --prefix web install
npm --prefix web run build
cp .env.example .env
# 在 .env 中配置 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL。
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

打开 http://localhost:8000 。开发前端可使用 `npm --prefix web run dev`。

只有本地演示或测试才设置 `LLM_MOCK_MODE=true`；界面会明确显示演示模式。测试数据不代表真实 LLM 的创作质量。主流程不需要设置 `COMFYUI_MOCK_MODE`，也不需要运行 ComfyUI。可选在线渲染需要配置真实 ComfyUI 或 ModelScope 后端。

## API / SDK

```python
from agent import MovieAgent

agent = MovieAgent()
project = agent.create_project("做一个雨夜车站的30秒悬疑短片")
pid = project["id"]
await agent.analyze_input(pid)
await agent.confirm_brief(pid)
# 可选：agent.apply_auteur_profile(pid, profile_id, variant_id)
treatments = await agent.generate_treatments(pid)
# 展示 treatments.options 给用户，取得明确选择的 treatment_id。
await agent.confirm_treatment(pid, treatment_id)
agent.start_auto_pipeline(pid)
# 轮询 agent.get_pipeline_status(pid)，直到完成或失败。
```

关键接口：

| 操作 | 接口 |
|---|---|
| 保存剧情 | `POST /api/projects/{id}/brief/confirm` |
| 生成方案 | `POST /api/projects/{id}/treatments/generate` |
| 确认方案 | `POST /api/projects/{id}/treatments/{treatment_id}/confirm` |
| 开始／查询制作 | `POST / GET /api/projects/{id}/auto_pipeline` |
| 校验并重新编译 | `POST /api/projects/{id}/packages/generate` |
| 交付清单 | `GET /api/projects/{id}/delivery` |
| ZIP 导出 | `GET /api/projects/{id}/export` |
| 单镜头下载 | `GET /api/projects/{id}/workflow/{shot_id}?format=ui`（默认 api） |

上游修改会使下游产物失效，旧文件即使仍在磁盘上也不能通过导出接口获取。后台制作中阻止修改，避免新旧内容混合。制作任务在单进程后台运行；服务重启后可依据已存产物重试，运行日志不跨重启保存。多 worker 部署需要外部任务队列，不应直接共用内存任务状态。

## CLI

```bash
.venv/bin/python -m server.cli create --idea "30秒雨夜侦探短片"
.venv/bin/python -m server.cli export --id prj_12345678 --output ./production.zip
```

CLI `create --auto` 是明确授权采用默认值和推荐方案的便捷模式，直接输出制作包；Web 主流程始终由用户选择。

## 验证

```bash
.venv/bin/pytest -q
npm --prefix web run build
```

测试覆盖状态顺序、显式方案选择、离线导出、UI/API 参数一致性、素材清单、时长与连续性校验、上游失效、并发保护，以及可选仿真渲染／粗剪。使用隔离临时数据库，不改动真实项目。历史技术方案文档保留作为设计记录，当前行为以本 README 与实现为准。

## ModelScope Studio 部署

Docker 镜像包含全部前端产物、后端、提示词和模板，并在构建时检查关键文件。默认将项目与 SQLite 存储在 `/mnt/workspace/movie-agent`。启动脚本仅为专用存储目录设置权限，随后切换到普通用户运行服务。`/api/health` 可核对部署版本和完整性。

从旧版迁移时可通过一次性 Studio Secret `PROJECT_MIGRATION_B64` 注入压缩备份。迁移只创建不存在的项目，不覆盖已有数据；迁移完成后应删除该 Secret。备份不进入 Git 或镜像。
