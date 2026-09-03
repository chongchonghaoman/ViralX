<p align="center">
  <img src="static/assets/viralx-signal-orbit-1024.webp" width="420" alt="ViralX 短视频证据工作台主视觉">
</p>

<h1 align="center">ViralX</h1>

<p align="center">
  <strong>把爆款拆到每一秒，也把每个结论还给证据。</strong><br>
  短视频发现、原片采集、原片视觉理解与复刻分析工作台。
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
关键词 ─→ 多源无感搜索 ── 自动切换 / 合并 / 去重 ─┐
视频直链 ─────────────────────────────────────────┤
                                                  ├→ TK Note 下载真实原片与平台证据
                                                  │   搜索媒体提示 → yt-dlp → 隔离 Chrome 兜底
                                              ↓ 同一份本地原片
                                     原片送审准备：可读视频 + 哈希 + 目标产品
                                              ↓
                                     合并平台、TK Note 与可选镜头索引
                                              ↓ 原片 + 统一证据包
                                     Qwen3-VL 等视觉模型读取原片并生成报告
                                              ↓ 校验时间引用与目标产品一致性
                                     证据报告 + 高保真复刻脚本 + MD 源码复制

专业模式可在原片主证据之外增加 ShotLoom 镜头边界、关键帧和镜头 ID；它不再替代最终模型对原片的核验。
```

面向人的产品界面是 Web；需要 Python、OpenCV、TK Note、本地缓存或 LibTV CLI 登录态的能力由站点所有者运行的 ViralX Worker 执行，网页访客无需安装 Connector。仓库同时提供 Agent-native Skill，让 Codex 等 Agent 直接运行同一套证据方法，不需要第二套客户端界面。

## 本次重点更新：从“模型猜测”改为“证据流水线”

这次重构首先解决四个问题：找的是不是目标视频、下载的是不是同一条原片、模型实际看到了什么、证据失败后系统是否会停止。

- **七路无感搜索链**：关键词按 `API6 → ScrapTik → Scraper7 → Download5 Search → TokApi → Download1 Search → API15` 自动发现候选；任一路服务异常、配额受限、空结果或候选不足时，同一次任务无感换源。
- **跨源合并与去重**：所有来源先归一化成同一个帖子合同，再按真实数字帖子 ID 去重、语义相关性和互动数据排序；达到目标数量立即停止，避免无意义消耗配额。
- **一把搜索 Key**：已订阅的关键词搜索源共用一个 `RAPIDAPI_KEY` 配置位。API23 保留兼容代码，但因实测持续返回空候选，不进入默认生产链。
- **TK Note 是固定采集阶段**：搜索链找到的每个候选都会进入 TK Note，下载对应 `source.mp4`、帖子元数据、字幕 / ASR 与评论证据；失败就阻断后续步骤。
- **采集不再单押 yt-dlp**：搜索响应若含真实媒体地址只在内存中交给 TK Note；网页挑战出现时自动使用隔离的本机 Chrome / Edge 播放器兜底，不导出 Cookie，也不保存签名地址。
- **刷新不会破坏有效原片**：网页上的“刷新证据”保留已校验 `source.mp4`，只重建字幕、ASR 与派生证据；显式重下也必须先校验临时文件，再原子替换旧原片。
- **默认原片直读**：推荐 Qwen3-VL Flash；同一套 Base URL、API Key 和模型 ID 直接接收 TK Note 校验过的完整原片，再基于平台、字幕与原片时间证据完成终审。
- **ShotLoom 变成专业增强**：需要稳定镜头边界、关键帧索引和逐镜审计时再启用；即使启用，最终视觉模型仍会核对原片，避免关键帧漏检成为错误结论。
- **LibTV 改为显式故障回退**：标准流程不会调用 LibTV；只有用户选择“失败后回退 LibTV”或“仅 LibTV”时才需要官方 CLI 登录。
- **统一证据合同**：合并层输出 `viralx.evidence_bundle.v1`，记录目标产品、原片哈希、平台证据、TK Note 证据与可选 `viralx.shot_evidence.v1`。
- **目标产品锁**：关键词或用户填写的产品名固定为本次研究对象；模型必须把目标产品与胶条、支架、遥控器等配件分开，并输出唯一可见状态。
- **报告引用门禁**：原片事实必须引用 `[VIDEO:MM:SS-MM:SS]`，专业镜头可追加 `[SHOT:Sxxx]`；平台与字幕分别引用 `[META:*]`、`[TK:*]`。没有评论正文时不得声称“用户认为”。
- **搜索与下载身份核对**：搜索候选和 TK Note 下载结果的视频 ID 必须一致，避免搜索链接与实际原片错配。
- **声音证据单独取证**：声音、台词和字幕只能来自 TK Note 字幕或 ASR，不能从静态关键帧推断。
- **失败成为正式状态**：采集、镜头、合并或模型任一阶段失败都会明确阻断，不再把“任务结束”写成“可信分析完成”。
- **模型断连自动恢复**：原片、抽帧和文本终审共用同一请求层；遇到连接中断、限流或临时 5xx 时串行节流并有限退避重试，诊断只记录状态和尝试次数，不记录 URL 或 Key。
- **终审失败可从检查点续跑**：统一证据已生成但模型连接或引用门禁失败时，服务端保存 24 小时匿名任务检查点；网页复用已校验原片和证据，只重试模型终审。
- **复刻改为高保真结构迁移**：按原片时间轴保留段落顺序、时长比例、镜头功能、动作节奏、字幕 / 声音功能、视觉效果、转场和 CTA 位置；只替换目标产品与不可复用素材，禁止无证据新增卖点。
- **报告改为编辑部式证据文档**：固定输出一页结论、原片档案、证据覆盖、原片时间轴、爆款机制、受众、结构母版、逐镜复刻脚本与证据索引；阅读视图提供章节目录，源码视图可一键复制完整 Markdown 到飞书文档或 Obsidian。
- **Agent-native Skill**：`$viralx-agent` 使用 TK Note、FFmpeg 和当前 Codex 模型完成取证与分析，不要求用户额外购买模型 API。
- **网页改为集中式 Worker**：Edge 前端通过受限 HTTPS API 调用同一套证据链；访客不再连接自己的 `127.0.0.1`，离线时仍可浏览产品方法与界面内容。
- **长任务改为后台任务传输**：网页同源提交任务，再用短轮询持续取回 NDJSON 进度；搜索、下载和原片终审超过网关单次请求时限时，不再直接变成 HTTP 504。

原有能力继续保留：品类消歧、TK Note、共享 Whisper / Qwen3-ASR、ShotLoom、可选 LibTV、本地 Markdown / Obsidian 兼容、模型预设、自定义 API、Web API Skill 和 Agent-native Skill。

![ViralX 网页设置](docs/assets/viralx-settings.png)

## 工作逻辑

![ViralX 证据优先分析流程](docs/assets/viralx-workflow.svg)

流程图源码：[docs/assets/viralx-workflow.mmd](docs/assets/viralx-workflow.mmd)

默认模式下，第 03 阶段是**原片送审准备**，不是先调用一次模型完成拉片；第 04 阶段整理已有证据，第 05 阶段才把原片与证据一起交给视觉模型理解和终审。五个进度阶段不代表五次模型调用。ShotLoom / LibTV 仅属于显式启用的专业分支。

| 阶段 | 责任 | 成功条件 | 失败后的行为 |
| --- | --- | --- | --- |
| 01 · 发现视频 | 七个搜索源按质量顺序自动切换、合并和去重；直链跳过 | 可打开的真实帖子 URL 与平台指标 | 所有可用来源都无候选才停止 |
| 02 · TK Note 采集 | 缓存优先；搜索媒体提示、yt-dlp、隔离 Chrome 依次采集原片，再生成元数据、字幕 / ASR 与资产清单 | 原片非空、可解码；帖子 ID 一致 | 保留旧证据；无可用原片才阻断 |
| 03 · 原片送审准备 | 默认准备可读原片、哈希与目标产品；专业模式可生成 ShotLoom / LibTV 镜头索引 | 原片输入就绪；专业分支的镜头证据通过对应校验 | 缺少可用输入则阻断，不拿关键帧猜测冒充原片理解 |
| 04 · 整理证据包 | 合并平台、TK Note、原片引用与可选镜头索引；此时不声称已完成视觉理解 | 保存 `viralx.evidence_bundle.v1` | 明确缺失项，保留已获得证据；不能把缺失评论当作用户反馈 |
| 05 · 视觉理解与终审 | 视觉模型读取原片与证据，生成事实、推断和高保真复刻脚本；随后执行报告校验 | 原片事实引用 `[VIDEO:*]`、目标产品一致，复刻段落映射原片时间轴 | 临时断连有限退避重试；仍失败或报告被拦截时保留检查点，仅重试终审 |

最终交付为**证据报告 + 高保真复刻脚本**：保留原片段落顺序、时长比例、动作节奏、视觉效果与 CTA 位置，再替换为目标产品。报告支持阅读视图与 **Markdown 源码视图**，通过「一键复制」粘贴到飞书文档或 Obsidian，不再把 Obsidian 导出作为默认交付入口。

恢复路径分开处理：**采集失败先恢复采集**；**终审失败复用原片与证据**。仅在 24 小时检查点仍有效、原片完整时才能跳过前序步骤；失效后需要重新准备证据。模型输出被校验拦截时会展示原因，不作为可信报告展示。

几个角色不能混淆：

- 多个 RapidAPI 搜索源组成**关键词发现链**，不是原片下载器；ViralX 自动切换、补足和去重，页面不要求用户选择供应商。视频直链不需要 RapidAPI。
- TK Note 是**固定的原片和平台证据采集器**，每个候选都必须经过；它会复用已验证缓存，并在 yt-dlp 受阻时使用隔离浏览器兜底，后续分析始终读取同一份 `source.mp4`。
- 上方视觉模型是**原片视觉事实与最终证据综合的主引擎**；默认直接读取完整原片，不依赖 ShotLoom 才能判断画面。
- ShotLoom Core 是**可选的切镜与关键帧编排器**，用于专业剪辑点索引，不是另一套真相源。

## 使用方式与 API 边界

| 使用方式 | 必需项 | 可选项 |
| --- | --- | --- |
| 粘贴单条 TikTok / 抖音链接 | ViralX Worker、TK Note、可读视频的视觉模型 API | ShotLoom 专业镜头索引；RapidAPI 不需要 |
| 输入关键词搜索并分析 | 上述配置 + 已订阅搜索源共用的 `RAPIDAPI_KEY` | LibTV 备用 |
| `只采集` 模式 | ViralX Worker + TK Note | 不调用镜头模型和最终模型 |
| Codex 中使用 `$viralx-agent` | Codex 当前模型、Python、FFmpeg；直链再需要 TK Note | **不需要独立模型 API**；关键词发现服务另算 |

标准完整流程要求上方模型具备视频输入能力，推荐 Qwen3-VL Flash。DeepSeek 等纯文本模型不能完成默认原片分析。ShotLoom 与 LibTV 都属于显式选择的专业增强或回退，不是日常流程前置条件。

## 网页能力

| 能力 | 实际行为 |
| --- | --- |
| TikTok 多源无感搜索 | 七个可用搜索源自动切换、补足和去重，统一归一化帖子 ID、链接、互动数据与语义相关性；任一单点故障不会中断任务 |
| 品类消歧 | 区分 `picture light` 与 `light painting` 等相邻但不同的内容 |
| TK Note 采集 | 缓存优先，按搜索媒体提示 → yt-dlp → 隔离 Chrome 兜底；保存原片、元数据、字幕 / ASR、资产清单和警告 |
| 原片视觉模型 | 直接读取 TK Note 保存的完整视频，输出目标产品状态和可核验时间段 |
| ShotLoom Core | 可选的本地切镜与关键帧索引；用于专业剪辑点审计，不替代原片核验 |
| LibTV 备用 | 通过官方 CLI 登录，仅在显式回退或显式选择时生成拉片证据 |
| 上方视觉模型 | 默认复用一套自定义 Base URL、API Key 与模型 ID，直接理解完整原片并完成证据终审 |
| 流式进度 | NDJSON 返回发现、采集、原片送审、证据校验和最终分析五个真实阶段 |
| 审计文件 | 保存证据包、镜头证据和最终原始输出，便于追查结论 |
| Markdown 报告 | 编辑部式阅读视图与完整 MD 源码视图；一键复制后可直接粘贴到飞书文档或 Obsidian |

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
| `/api/jobs` | POST | 托管网页快速提交后台分析任务 |
| `/api/jobs/:id/events` | GET | 以短响应增量取回原 NDJSON 进度 |
| `/api/generate_variants` | POST | 基于已完成证据报告生成脚本变体 |

本地 Flask 另外提供设置、缓存、文件导出与可选 LibTV 管理接口；这些管理能力不属于公开 Worker。

关键结果字段：

```json
{
  "pipeline_status": "completed | blocked | error",
  "shot_provider": "direct-video | shotloom | libtv | none",
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
├── 流式进度、报告阅读与 Markdown 源码复制
└── 同源任务 API → owner-operated ViralX Worker
    ├── TikTok multi-source search（关键词发现、自动切换、合并与去重）
    ├── TK Note（缓存 / 搜索媒体提示 / yt-dlp / 隔离 Chrome）
    ├── source-video vision（默认完整原片理解）
    ├── ShotLoom Core（可选专业镜头索引）
    ├── official LibTV CLI（可选回退）
    ├── evidence merge + quality gates
    └── selected visual model（接收原片与统一证据）
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
