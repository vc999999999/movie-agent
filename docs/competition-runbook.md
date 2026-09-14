# 参赛版运行与验收

## 本轮实现

SQLite 项目租约（15 秒续期、60 秒过期）覆盖制作写入口；生成指纹包含工作流、提示词、后端和参考文件哈希。恢复时验证媒体后复用成功镜头。已知远端 ID 优先查询，无法判断是否提交的任务阻止重复提交，可通过核实接口恢复。

制片规划、编剧、分镜导演和质检通过版本化产物交接。质检使用独立提示词，返回具体场景/镜头依据；修订最多两轮，导演只能改授权镜头，编剧可改相关场景及镜头。文本检查不等于视觉验证。

素材上传支持 PNG/JPEG 和可识别音频，默认 50MB、10 分钟、2400 万像素限制。图片可设为全片默认首帧或单镜头绑定。缺失首帧会阻止图生视频执行；系统不会自动制作参考图或替换成其他模型。云端现有文生视频适配器不宣称支持参考图。

时间线支持已有配音、音乐和音效的偏移、入点、出点、音量；配音期间音乐压低；成片含可切换字幕轨。静音镜头明确保持静音；字幕不能代替配音。画面起中末抽帧用于人工对照。全片逐帧分配时长，避免小数镜头累积取整误差，最多容忍两帧媒体边界差异，较大短缺停止合成。

输出按运行保存为不可变文件，通过 FFprobe 和解码检查后更新当前成片指针；失败不覆盖上一版成片。旧项目无需删除，缺少新指纹的旧镜头不直接复用。

## 本地检查

需要 Python 3.10+、FFmpeg/FFprobe 和 Node.js。保持原有部署、模型配置。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pytest pytest-asyncio
.venv/bin/python -m pytest -q
npm ci --prefix web
npm run build --prefix web
```

仿真运行会生成纯色视频，仅验证流程。测试显式登记合成参考图，不使用工作流占位首帧。现有仿真剧本固定一名角色，因此多人测试应暴露约束失败；不得据此声称多人生成已实测成功。

## SDK 完整示例

```python
import asyncio
from pathlib import Path
from agent import MovieAgent
from agent.media import AssetMetadata

async def main():
    agent = MovieAgent()
    pid = agent.create_project("30秒竖屏，无对白：雨夜侦探发现自己留下的证据")["id"]
    # 提供现有工作流需要的真实参考图，不自动选模型或生成替代素材。
    await agent.register_asset(pid, Path("reference.png").read_bytes(), AssetMetadata(
        purpose="reference", project_default=True, source="我的原创角色参考图",
        rights="confirmed", license_note="本人原创并持有使用权",
    ))
    await agent.run_auto_pipeline(pid)
    print(agent.get_pipeline_status(pid))
    print(await agent.export_evidence(pid))

asyncio.run(main())
```

网页创建项目后，可点击顶部“一句话全自动生成”。若首帧缺失，在生成工作台上传并设为默认首帧，点击“恢复生成”。如有硬约束冲突，使用“澄清或调整明确要求”；不会静默把 120 秒改成 90 秒。

## 新增接口

原接口兼容；单镜头渲染增加可选 `force`。全部路径以 `/api/projects/{project_id}` 开头，结构详情见运行中的 `/docs`。

| 路径 | 方法 | 用途 |
| --- | --- | --- |
| `/auto_pipeline` | POST / GET | 启动或恢复；查询角色交接、修订、尝试和复用记录 |
| `/quality/repair`、`/quality` | POST、GET | 最多两轮质检修订；查询历次报告 |
| `/constraints` | PUT | 用 `text` 显式澄清要求；原文证据保留 |
| `/assets?metadata=…` | POST | 二进制请求体上传；metadata 是 URL 编码的 AssetMetadata JSON |
| `/assets`、`/assets/{asset_id}/file` | GET | 素材清单及文件 |
| `/assets/{asset_id}` | PATCH | 提交 `rights` 和 `license_note` 更新授权记录 |
| `/timeline` | GET / PUT | 音频片段与可编辑字幕；时长以秒为单位 |
| `/comparison` | POST / GET | 生成或读取每镜头三帧对照 |
| `/shots/{shot_id}/feedback` | POST | 用 `note` 记录人工画面反馈 |
| `/renders/{run_id}/reconcile` | POST | `evidence` 加 `task_id` 或 `not_submitted=true`，核实未决提交 |
| `/evidence`、`/evidence/export` | GET、POST | 实测指标；下载包含报告、时间线、使用素材与成片的 ZIP |

`/evidence/export?competition=true` 要求真实成片、文本验收通过、已使用素材授权确认及所需配音补齐。声明仅记录来源和提交者依据，不自动授予素材使用权。仓库许可证未代替权利人选择。

项目执行冲突返回 409；输入或质量问题返回 400/422；不存在的新增接口项目返回 404。后台流程细分 `needs_clarification`、`quality_failed`、`interrupted`。项目原状态枚举保留兼容性，详情以流水线状态为准。

## 固定输入与消融

```bash
# 默认使用隔离目录、显式仿真，不访问真实服务。
.venv/bin/python -m evaluation.run
# 已配置服务，手动选择真实评测；现有供应商可能正常计费。
.venv/bin/python -m evaluation.run --real --reference /absolute/path/reference.png
```

12 条输入分别运行 baseline、rules、full，共 36 次；baseline 保留安全结构检查，rules 加入电影语法和硬约束验收，full 加入独立 LLM 内容质检和修正。每组是独立项目，种子不同，比较包含生成随机性；结果不是严格控制随机性的模型能力实验。JSON 保留逐例失败原因，Markdown 汇总成片数与预期行为符合数；矛盾输入正确提出澄清不计成片成功。

耗时统计覆盖自动流水线，不含前置素材上传。LLM token 用量仅记录供应商实际返回值，缺失留空；真实成本始终留空，待接入真实账单。角色交接和修订差异可查。既有仿真回退不会在内容修复缺少样例时假装成功。

## 故障恢复演示

```bash
.venv/bin/python -m pytest tests/test_competition.py -q
```

覆盖第三镜头失败后前两镜头不重复提交、媒体损坏失效、并发冲突、过期租约写入阻止、远端 ID 恢复查询、提交不明禁止重发、质检局部修正和次数限制、首帧绑定、混音字幕及成片原子发布。

## 作品盲评表

每项由至少两位未参与制作的评审独立填写，保存原始表，不用模型自评填空。

| 项目 | 核查要点 | 结果 |
| --- | --- | --- |
| 叙事 | 目标、冲突、选择、结果能否看懂；铺垫是否兑现 | 待验收 |
| 画面 | 同一人物外观服装、场景、风格和运动方向是否连贯 | 待验收 |
| 声音 | 对白可懂、无削波、音乐压低自然、字幕同步 | 待验收 |
| 剪辑 | 镜头时长、节奏、转场与信息密度 | 待验收 |
| 完整度 | 片头到结尾、目标画幅、实际时长、素材出处 | 待验收 |

## 限制

SQLite 租约适用于共享同一个数据库文件的进程，不提供跨主机独立数据库协调或自动任务队列。重启后由用户或调用者恢复。租约不能撤销已发出的远端任务，未决记录需要查询或人工核实。没有新增视觉模型、语音服务、模型训练、量化或部署流程。

本轮测试结果与浏览器实操见 [验证记录](validation.md)。
