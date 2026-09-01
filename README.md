<p align="center">
  <img src="static/assets/viralx-signal-orbit-1024.webp" width="420" alt="ViralX 短视频证据工作台主视觉">
</p>

<h1 align="center">ViralX</h1>

<p align="center">
  <strong>把爆款拆到每一秒，也把每个结论还给证据。</strong><br>
  短视频发现、原片采集、逐镜取证与复刻分析工作台。
</p>

<p align="center">
  <a href="https://github.com/chongchonghaoman/ViralX/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/chongchonghaoman/ViralX/ci.yml?branch=main&style=flat-square&label=tests"></a>
  <a href=".agents/skills/viralx-agent"><img alt="Agent-native Skill" src="https://img.shields.io/badge/Codex-Agent--native-4DC5E5?style=flat-square"></a>
  <a href=".agents/skills/viralx"><img alt="Web API Skill" src="https://img.shields.io/badge/Codex-Web_API-111111?style=flat-square"></a>
  <img alt="Web product" src="https://img.shields.io/badge/Product-Web-111111?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10--3.12-3776AB?style=flat-square">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-111111?style=flat-square"></a>
</p>

<p align="center">
  <a href="#工作逻辑">工作逻辑</a> ·
  <a href="#在-codex-中直接调用-viralx">Codex Skill</a> ·
  <a href="DESIGN.md">设计合同</a>
</p>

![ViralX 网页首页](docs/assets/viralx-homepage.png)

## ViralX 是什么

ViralX 是一个证据优先的短视频拆解系统，同时提供 Web 工作台和 Agent-native Skill。它不会把视频链接直接丢给模型并让模型凭印象作答，而是先确认帖子身份、下载真实原片、生成可核验的视觉与文本证据，再进行综合分析。

```text
关键词 ─→ TikTok API23 ─成功────────┐
                  └失败 / 无候选─→ Scraper7 ─┤
视频直链 ─────────────────────────────┤
                                      ├→ TK Note 下载真实原片与平台证据
                                      │   搜索媒体提示 → yt-dlp → 隔离 Chrome 兜底
                                  ↓ 同一份本地原片
                         ShotLoom Core 切镜与抽帧
                                  ↓ 上方视觉模型识别逐镜事实
                         统一证据包 + 质量门禁
                                  ↓ 同一模型基于完整证据终审
                         最终报告与可执行复刻脚本
```

面向人的产品界面是 Web；需要 Python、OpenCV、TK Note、本地缓存或 LibTV CLI 登录态的能力由站点所有者运行的 ViralX Worker 执行，网页访客无需安装 Connector。仓库同时提供 Agent-native Skill，让 Codex 等 Agent 直接运行同一套证据方法，不需要第二套客户端界面。

## 本次重点更新：从“模型猜测”改为“证据流水线”

这次重构首先解决四个问题：找的是不是目标视频、下载的是不是同一条原片、模型实际看到了什么、证据失败后系统是否会停止。

- **搜索自动容灾**：关键词先调用 TikTok API23；服务异常、业务状态非零、空结果、帖子 ID 无效、品类不匹配或点赞筛选后无候选时，同一次任务自动转到 Scraper7。两项服务共用一个 `RAPIDAPI_KEY` 配置位。
- **TK Note 是固定采集阶段**：搜索链找到的每个候选都会进入 TK Note，下载对应 `source.mp4`、帖子元数据、字幕 / ASR 与评论证据；失败就阻断后续步骤。
- **采集不再单押 yt-dlp**：搜索响应若含真实媒体地址只在内存中交给 TK Note；网页挑战出现时自动使用隔离的本机 Chrome / Edge 播放器兜底，不导出 Cookie，也不保存签名地址。
- **刷新不会破坏有效原片**：网页上的“刷新证据”保留已校验 `source.mp4`，只重建字幕、ASR 与派生证据；显式重下也必须先校验临时文件，再原子替换旧原片。
- **ShotLoom Core 只负责切镜与抽帧**：它直接读取 TK Note 的同一份原片，不是第二个分析模型，也不会重复下载视频。
- **默认复用上方视觉模型**：推荐 Qwen3-VL Flash；同一套 Base URL、API Key 和模型 ID 先识别关键帧中的可见事实，再基于合并证据完成终审与复刻脚本。
- **LibTV 改为显式故障回退**：标准流程不会调用 LibTV；只有用户选择“失败后回退 LibTV”或“仅 LibTV”时才需要官方 CLI 登录。
- **统一证据合同**：镜头层输出 `viralx.shot_evidence.v1`，合并层输出 `viralx.evidence_bundle.v1`；每个镜头都有 ID、时间范围、关键帧、视觉事实、未知项、置信度和原片哈希。
- **质量门禁阻止猜测**：时间线覆盖不足、镜头 ID 冲突、原片哈希缺失或视觉事实为空时，最终模型不会运行。
- **报告引用门禁**：事实必须引用真实 `[SHOT:Sxxx]`、`[META:*]` 或 `[TK:*]`；没有评论正文时不得声称“用户认为”。
- **搜索与下载身份核对**：搜索候选和 TK Note 下载结果的视频 ID 必须一致，避免搜索链接与实际原片错配。
- **声音证据单独取证**：声音、台词和字幕只能来自 TK Note 字幕或 ASR，不能从静态关键帧推断。
- **失败成为正式状态**：采集、镜头、合并或模型任一阶段失败都会明确阻断，不再把“任务结束”写成“可信分析完成”。
- **Agent-native Skill**：`$viralx-agent` 使用 TK Note、FFmpeg 和当前 Codex 模型完成取证与分析，不要求用户额外购买模型 API。
- **网页改为集中式 Worker**：Edge 前端通过受限 HTTPS API 调用同一套证据链；访客不再连接自己的 `127.0.0.1`，离线时仍可浏览产品方法与界面内容。

原有能力继续保留：TikTok API23 + Scraper7 关键词发现、品类消歧、TK Note、共享 Whisper / Qwen3-ASR、ShotLoom、可选 LibTV、Obsidian 导出、模型预设、自定义 API、Web API Skill 和 Agent-native Skill。

![ViralX 网页设置](docs/assets/viralx-settings.png)

## 工作逻辑

![ViralX 证据优先分析流程](docs/assets/viralx-workflow.svg)

流程图源码：[docs/assets/viralx-workflow.mmd](docs/assets/viralx-workflow.mmd)

| 阶段 | 责任 | 成功条件 | 失败后的行为 |
| --- | --- | --- | --- |
| 01 · 发现视频 | API23 优先；失败或无有效候选自动回退 Scraper7；直链跳过 | 可打开的真实帖子 URL 与平台指标 | 两条链路都无候选才停止 |
| 02 · TK Note 采集 | 缓存优先；搜索媒体提示、yt-dlp、隔离 Chrome 依次采集原片，再生成元数据、字幕 / ASR 与资产清单 | 原片非空、可解码；帖子 ID 一致 | 保留旧证据；无可用原片才阻断 |
| 03 · 镜头取证 | ShotLoom 切镜、抽帧；上方视觉模型识别逐镜事实 | 完整时间线、镜头 ID、视觉事实、原片哈希 | 阻断；仅显式配置时回退 LibTV |
| 04 · 合并证据 | 合并平台、TK Note 与镜头证据 | `viralx.evidence_bundle.v1` | 保存部分证据并阻断最终模型 |
| 05 · 最终分析 | 只基于命名证据生成事实、推断与创意提案 | 每项事实引用对应证据 | 拦截不可信输出 |

三个角色不能混淆：

- TikTok API23 与 Scraper7 组成**关键词发现链**，不是原片下载器；API23 是主链路，Scraper7 是自动回退。视频直链不需要 RapidAPI。
- TK Note 是**固定的原片和平台证据采集器**，每个候选都必须经过；它会复用已验证缓存，并在 yt-dlp 受阻时使用隔离浏览器兜底，后续分析始终读取同一份 `source.mp4`。
- ShotLoom Core 是**切镜与关键帧编排器**，不是另一个模型；关键帧事实由上方配置的视觉模型识别。
- 上方视觉模型同时承担**逐镜事实识别与最终证据综合**，但任何上游失败都不能靠模型猜测兜底。

## 使用方式与 API 边界

| 使用方式 | 必需项 | 可选项 |
| --- | --- | --- |
| 粘贴单条 TikTok / 抖音链接 | ViralX Worker、TK Note、ShotLoom、可用视觉模型 API | LibTV 故障回退；RapidAPI 不需要 |
| 输入关键词搜索并分析 | 上述配置 + API23 / Scraper7 共用的 `RAPIDAPI_KEY` | LibTV 备用 |
| `只采集` 模式 | ViralX Worker + TK Note | 不调用镜头模型和最终模型 |
| Codex 中使用 `$viralx-agent` | Codex 当前模型、Python、FFmpeg；直链再需要 TK Note | **不需要独立模型 API**；关键词发现服务另算 |

标准完整流程要求上方模型具备视觉输入能力，推荐 Qwen3-VL Flash。DeepSeek 等纯文本模型不能完成默认的逐镜事实识别；若坚持使用，需要在专家设置中单独配置视觉模型。LibTV 只在被明确选择为故障回退时需要官方 CLI 登录。

## 网页能力

| 能力 | 实际行为 |
| --- | --- |
| TikTok 双链路搜索 | 先调用 API23 `/api/search/video`；无可用候选时自动调用 Scraper7 `/feed/search`，统一归一化帖子 ID、链接、互动数据与语义相关性 |
| 品类消歧 | 区分 `picture light` 与 `light painting` 等相邻但不同的内容 |
| TK Note 采集 | 缓存优先，按搜索媒体提示 → yt-dlp → 隔离 Chrome 兜底；保存原片、元数据、字幕 / ASR、资产清单和警告 |
| ShotLoom Core | 本地切镜与关键帧采样；把帧交给上方视觉模型并检查时间线质量 |
| LibTV 备用 | 通过官方 CLI 登录，仅在显式回退或显式选择时生成拉片证据 |
| 上方视觉模型 | 默认复用一套自定义 Base URL、API Key 与模型 ID，先识别逐镜事实，再基于统一证据终审 |
| 流式进度 | NDJSON 返回发现、采集、镜头、合并和最终分析五个真实阶段 |
| 审计文件 | 保存证据包、镜头证据和最终原始输出，便于追查结论 |
| Obsidian | 本地写入，或生成 URI / 下载 Markdown |

## 在 Codex 中直接调用 ViralX

仓库提供两个职责不同、可同时安装的 Skill：

| Skill | 模型在哪里运行 | 独立模型 API Key |
| --- | --- | --- |
| [`$viralx-agent`](.agents/skills/viralx-agent) | 当前 Codex 会话 | **不需要** |
| [`$viralx`](.agents/skills/viralx) | ViralX Web / Worker 配置的模型 | 完整分析需要 |

### 推荐：Agent-native

把仓库链接发给 Codex，并说明：

```text
请安装这个仓库的 .agents/skills/viralx-agent 和 .agents/skills/tk-note，
然后使用 $viralx-agent 分析下面的 TikTok 直链或本地 MP4。
```

也可以使用 Codex 自带的 Skill 安装器安装：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo chongchonghaoman/ViralX `
  --path .agents/skills/viralx-agent .agents/skills/tk-note
```

`$viralx-agent` 的脚本只负责 TK Note 采集、字幕 / 本地 ASR、原片哈希、FFmpeg 抽帧和引用校验。当前 Codex 模型按时间顺序检查生成的本地图片，再输出带 `[FRAME:Fxxx@时间]`、`[META:*]` 和 `[TK:transcript]` 的报告。

它分析的是从原片提取的时间戳帧、字幕和元数据，不会伪装成原生连续观看视频。视频直链和本地 MP4 不需要 RapidAPI；只有关键词发现可能需要搜索服务。

## 运行边界

公开网页只负责输入、状态、结果和可选会话级 BYOK；ViralX Worker 集中运行搜索、采集、镜头取证和模型调用。公开 Worker 不挂载设置写入、缓存清理、文件系统导出或 LibTV 账号控制端点，浏览器也不能指定服务器 Cookie、代理、目录或 LibTV 运行方式。API Key、Cookie、代理地址和代理凭据不会出现在健康状态、分析结果或日志中。

本地开发、Worker 配置和故障排查见 [USAGE.md](USAGE.md)。README 只描述产品能力，不包含站点部署步骤或个人环境信息。

## Web API 与结果合同

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 无密钥的运行时与模型就绪状态 |
| `/api/keywords` | GET | 常用主题 |
| `/api/analyze` | POST | NDJSON 流式分析 |
| `/api/generate_variants` | POST | 基于已完成证据报告生成脚本变体 |

本地 Flask 另外提供设置、缓存、文件导出与可选 LibTV 管理接口；这些管理能力不属于公开 Worker。

关键结果字段：

```json
{
  "pipeline_status": "completed | blocked | error",
  "shot_provider": "shotloom | libtv | none",
  "shot_status": "completed | blocked",
  "shot_evidence_quality": {
    "timeline_coverage": 1.0,
    "analyzed_coverage": 1.0
  },
  "shot_block_reason": "",
  "fallback_used": false,
  "fallback_chain": [],
  "model_status": "completed | blocked | error"
}
```

## 架构

```text
Browser
├── 首页与设置页
├── 可选会话级 BYOK
├── 流式进度、报告与导出
└── HTTPS → owner-operated ViralX Worker
    ├── TikTok API23 → Scraper7（关键词发现与自动回退）
    ├── TK Note（缓存 / 搜索媒体提示 / yt-dlp / 隔离 Chrome）
    ├── ShotLoom Core（默认镜头证据）
    ├── official LibTV CLI（可选回退）
    ├── evidence merge + quality gates
    └── selected final model（只接收证据）
```

## 项目结构

```text
ViralX/
├── .agents/skills/viralx-agent/    Codex 原生分析 Skill
├── .agents/skills/viralx/          ViralX Web API Skill
├── .agents/skills/tk-note/         原片、字幕与平台证据采集 Skill
├── templates/                      首页与设置页
├── static/                         设计 token、GSAP 动效与交互
├── tiktok_viral_analyzer.py        搜索与语义筛选
├── video_ingest.py                 TK Note / yt-dlp 原片采集
├── shot_analyzers.py               ShotLoom、LibTV adapter 与质量门禁
├── ai_analyzer.py                  证据流水线与最终报告门禁
├── worker_server.py                公网受限 Worker 安全边界
├── web_app.py                      本地 Flask Web API
├── tests/                          后端、前端、Worker 与证据合同测试
└── DESIGN.md                       视觉、交互与状态合同
```

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 设计与动效

- 中性画布、双悬浮导航与深色证据工作台。
- Hanken Grotesk + Noto Sans SC，主标题使用项目字体资产。
- GSAP + ScrollTrigger，并为 `prefers-reduced-motion` 完整降级。
- 桌面与移动端保持同一任务顺序；运行状态只来自真实后端事件。

完整约束见 [DESIGN.md](DESIGN.md)。

## License

[MIT](LICENSE)。ShotLoom 适配来源与第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
