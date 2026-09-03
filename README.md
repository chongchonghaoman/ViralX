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

ViralX 面向希望把成功短视频案例应用到自己产品上的内容创作者与电商运营。输入产品关键词，发现相关高互动视频，采集真实原片，再生成带时间引用的拆解报告与高保真复刻脚本。

它提供 **Web 工作台**和 **Agent-native Skill** 两种入口：Web 由视觉模型 API 分析原片；Skill 由当前 Codex 模型检查本地时间戳帧与文本证据。两者采用证据优先的方法，但输入方式和覆盖能力不同。

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

## 近期重点更新

围绕四个问题持续改进：找的是不是目标视频、下载的是不是同一条原片、模型实际看到了什么，以及失败后能否保留成果继续。

- **七路无感搜索链**：关键词按 `API6 → ScrapTik → Scraper7 → Download5 Search → TokApi → Download1 Search → API15` 自动发现候选；任一路服务异常、配额受限、空结果或候选不足时，同一次任务无感换源。
- **跨源合并与媒体补全**：先统一帖子字段，按真实数字帖子 ID 去重并做相关性和互动筛选。候选数量足够但媒体信息不足时，仍会继续向后续来源补全；不是找到几条链接就结束。
- **一把搜索 Key**：已订阅的关键词搜索源共用一个 `RAPIDAPI_KEY` 配置位。API23 保留兼容代码，但因实测持续返回空候选，不进入默认生产链。
- **TK Note 是固定采集阶段**：进入分析的 TikTok 候选先采集对应 `source.mp4`、元数据及可获取的字幕 / ASR、评论。没有可用原片就阻断；字幕或评论缺失时明确标记，不当作已经取得。
- **采集不再单押 yt-dlp**：搜索响应若含真实媒体地址只在内存中交给 TK Note；网页挑战出现时自动使用隔离的本机 Chrome / Edge 播放器兜底，不导出 Cookie，也不保存签名地址。
- **刷新不会破坏有效原片**：网页上的“刷新证据”保留已校验 `source.mp4`，只重建字幕、ASR 与派生证据；显式重下也必须先校验临时文件，再原子替换旧原片。
- **原片输入优先**：推荐 Qwen3-VL Flash，支持自填 Base URL、API Key 与模型名称。兼容请求层优先提交视频；文件过大或服务商拒绝视频格式时，按已实现的条件降级为时间戳抽帧，并在证据包记录实际传输方式，不能把抽帧说成完整观看。
- **ShotLoom 变成专业增强**：需要镜头边界、关键帧索引和逐镜审计时再启用；最终模型仍优先接收原片，不把镜头索引当作唯一视觉证据。
- **LibTV 改为显式故障回退**：标准流程不会调用 LibTV；只有用户选择“失败后回退 LibTV”或“仅 LibTV”时才需要官方 CLI 登录。
- **证据与目标产品校验**：证据包记录目标产品、原片哈希与来源；报告区分目标产品和配件，并检查时间引用及目标产品一致性。兼容可识别的时间引用写法后仍未通过校验的输出，会显示失败原因，不作为可信报告展示。
- **搜索与下载身份核对**：搜索候选和 TK Note 下载结果的视频 ID 必须一致，避免搜索链接与实际原片错配。
- **声音证据单独取证**：声音、台词和字幕只能来自 TK Note 字幕或 ASR，不能从静态关键帧推断。
- **失败成为正式状态**：采集、镜头、合并或模型任一阶段失败都会明确阻断，不再把“任务结束”写成“可信分析完成”。
- **模型断连自动恢复**：原片、抽帧和文本终审共用同一请求层；遇到连接中断、限流或临时 5xx 时串行节流并有限退避重试，诊断只记录状态和尝试次数，不记录 URL 或 Key。
- **终审恢复先复核、再调用**：默认保存 24 小时任务检查点与任务级证据快照。重试先核对原片哈希并重新校验已保存报告；若报告已满足当前规则，直接恢复结果，无需再次调用模型。否则复用证据重新终审，不重复下载。
- **复刻改为高保真结构迁移**：按原片时间轴保留段落顺序、时长比例、镜头功能、动作节奏、字幕 / 声音功能、视觉效果、转场和 CTA 位置；只替换目标产品与不可复用素材，禁止无证据新增卖点。
- **报告改为编辑部式证据文档**：固定输出一页结论、原片档案、证据覆盖、原片时间轴、爆款机制、受众、结构母版、逐镜复刻脚本与证据索引；阅读视图提供章节目录，源码视图可一键复制完整 Markdown 到飞书文档或 Obsidian。
- **Agent-native Skill**：`$viralx-agent` 使用 TK Note、FFmpeg 和当前 Codex 模型完成取证与分析，不要求用户额外购买模型 API。
- **网页改为集中式 Worker**：Edge 前端通过受限 HTTPS API 调用同一套证据链；访客不再连接自己的 `127.0.0.1`，离线时仍可浏览产品方法与界面内容。
- **后台任务与增量进度**：网页提交后台任务，用短轮询取回 NDJSON 进度，减少长请求被网关截断的问题；Worker 离线、网络中断或上游超时仍会影响任务，不能承诺永不出现 504。
- **测试隔离修复**：流式响应在模拟 API 环境内读取完成，并断言测试不访问真实搜索服务；GitHub Actions 检查 Python 3.10、3.11、3.12 与网页构建。

原有能力继续保留：品类消歧、TK Note、共享 Whisper / Qwen3-ASR、ShotLoom、可选 LibTV、本地 Markdown / Obsidian 兼容、模型预设、自定义 API、Web API Skill 和 Agent-native Skill。

![ViralX 网页设置](docs/assets/viralx-settings.png)

## 工作逻辑

![ViralX 证据优先分析流程](docs/assets/viralx-workflow.svg)

流程图源码：[docs/assets/viralx-workflow.mmd](docs/assets/viralx-workflow.mmd)

默认模式下，第 03 阶段是**原片送审准备**，不是先调用一次模型完成拉片；第 04 阶段整理已有证据，第 05 阶段才把原片与证据一起交给视觉模型理解和终审。五个进度阶段不代表五次模型调用。ShotLoom / LibTV 仅属于显式启用的专业分支。

| 阶段 | 责任 | 成功条件 | 失败后的行为 |
| --- | --- | --- | --- |
| 01 · 发现视频 | 按默认顺序换源、合并、去重与媒体补全；直链跳过 | 获得通过身份和筛选规则的候选；搜索命中不等于已下载成功 | 区分未订阅、配额、服务异常和无合格候选；可提供订阅入口 |
| 02 · TK Note 采集 | 缓存优先；搜索媒体提示、yt-dlp、隔离 Chrome 依次采集原片，再生成元数据、字幕 / ASR 与资产清单 | 原片非空、可解码；帖子 ID 一致 | 保留旧证据；无可用原片才阻断 |
| 03 · 原片送审准备 | 默认准备可读原片、哈希与目标产品；专业模式可生成 ShotLoom / LibTV 镜头索引 | 原片输入就绪；专业分支的镜头证据通过对应校验 | 原片不可用则阻断；后续如降级抽帧，记录实际输入方式 |
| 04 · 整理证据包 | 合并平台、TK Note、原片引用与可选镜头索引；此时不声称已完成视觉理解 | 保存 `viralx.evidence_bundle.v1` | 明确缺失项，保留已获得证据；不能把缺失评论当作用户反馈 |
| 05 · 视觉理解与终审 | 视觉模型读取原片与证据，生成事实、推断和高保真复刻脚本；随后执行报告校验 | 原片事实引用 `[VIDEO:*]`、目标产品一致，复刻段落映射原片时间轴 | 临时断连有限退避重试；仍失败或报告被拦截时保留检查点，仅重试终审 |

最终交付为**证据报告 + 高保真复刻脚本**：保留原片段落顺序、时长比例、动作节奏、视觉效果与 CTA 位置，再替换为目标产品。报告支持阅读视图与 **Markdown 源码视图**，通过「一键复制」粘贴到飞书文档或 Obsidian，不再把 Obsidian 导出作为默认交付入口。

恢复路径分开处理：**采集失败先恢复采集**；**终审失败先复核保存的报告，再按需重新调用模型**。默认 24 小时检查点仍有效且原片哈希一致时，才能复用原片与证据；检查点失效或原片缺失后需重新准备。模型输出被校验拦截时会展示原因，不作为可信报告展示。

几个角色不能混淆：

- 多个 RapidAPI 搜索源组成**关键词发现链**，不是原片下载器；ViralX 自动切换、补足和去重，页面不要求用户选择供应商。视频直链不需要 RapidAPI。
- TK Note 是**固定的原片和平台证据采集器**，每个候选都必须经过；它会复用已验证缓存，并在 yt-dlp 受阻时使用隔离浏览器兜底，后续分析始终读取同一份 `source.mp4`。
- 所配置的视觉模型是**原片视觉理解与最终证据综合的主引擎**；优先接收原片，兼容降级时检查时间戳帧，不依赖 ShotLoom 才能判断画面。
- ShotLoom Core 是**可选的切镜与关键帧编排器**，用于专业剪辑点索引，不是另一套真相源。

## 使用方式与 API 边界

| 使用方式 | 必需项 | 可选项 |
| --- | --- | --- |
| 粘贴单条 TikTok / 抖音链接 | ViralX Worker、TK Note、可读视频的视觉模型 API | ShotLoom 专业镜头索引；RapidAPI 不需要 |
| 输入关键词搜索并分析 | 上述配置 + 已订阅搜索源共用的 `RAPIDAPI_KEY` | LibTV 备用 |
| `只采集` 模式 | ViralX Worker + TK Note | 不调用镜头模型和最终模型 |
| Codex 中使用 `$viralx-agent` | Codex 当前模型、Python、FFmpeg；直链再需要 TK Note | **不需要独立模型 API**；关键词发现服务另算 |

标准原片流程推荐配置 Qwen3-VL Flash，或其他能够接收视频的视觉模型。纯文本模型不能替代视觉取证。ShotLoom 与 LibTV 属于显式选择的专业增强或回退，不是日常流程前置条件。

### 开始一次关键词分析

1. 确认分析服务在线，搜索 Key 和视觉模型已配置；服务提供了默认配置时可直接使用。
2. 输入产品关键词，例如 `picture lights`；关键词发现需要已订阅相应搜索源的 RapidAPI Key。共用一把 Key 不等于自动订阅所有来源。
3. 需要用于自己的产品时，补充产品名称与真实卖点，再开始分析。
4. 查看每条视频的阶段状态；成功后打开报告，切换到 Markdown 源码并一键复制。部分视频失败不代表全部任务失败。

需要替换模型时，设置页填写 **Base URL、API Key、模型名称**。第三方接口不仅要能聊天，还需兼容项目发送的视频或图像消息格式；填入视觉模型名称不代表中转服务一定支持该输入。仅图像输入的兼容降级不等同于标准视频能力。

## 网页能力

| 能力 | 实际行为 |
| --- | --- |
| TikTok 多源无感搜索 | 已接入七个关键词搜索源，按订阅权限与响应结果换源、补足和去重；不能保证每个来源持续可用或每个关键词都有合格候选 |
| 品类消歧 | 区分 `picture light` 与 `light painting` 等相邻但不同的内容 |
| TK Note 采集 | 缓存优先，按搜索媒体提示 → yt-dlp → 隔离 Chrome 兜底；保存原片、元数据、字幕 / ASR、资产清单和警告 |
| 原片视觉模型 | 优先接收 TK Note 保存的原片；兼容降级时使用时间戳帧，记录传输方式与取证边界 |
| ShotLoom Core | 可选的本地切镜与关键帧索引；用于专业剪辑点审计，不替代原片核验 |
| LibTV 备用 | 通过官方 CLI 登录，仅在显式回退或显式选择时生成拉片证据 |
| 自定义模型 | 同一套 Base URL、API Key 与模型名称用于视觉理解和证据终审；不需要为默认流程再配置第二套镜头模型 |
| 任务进度 | NDJSON 返回发现、采集、原片送审准备、证据整理和最终分析五个阶段；托管网页通过后台任务短轮询接收 |
| 审计文件 | 保存证据包、镜头证据和最终原始输出，便于追查结论 |
| Markdown 报告 | 编辑部式阅读视图与完整 MD 源码视图；一键复制后可直接粘贴到飞书文档或 Obsidian |

## 在 Codex 中直接调用 ViralX

仓库提供两个职责不同、可同时安装的 Skill：

| Skill | 模型在哪里运行 | 独立模型 API Key |
| --- | --- | --- |
| [`$viralx-agent`](.agents/skills/viralx-agent) | 当前 Codex 会话 | **不需要** |
| [`$viralx`](.agents/skills/viralx) | ViralX Web / Worker 配置的模型 | 依赖服务端模型配置，不使用当前 Codex 模型替代 |

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

仅给关键词时，需要先由搜索能力取得明确候选链接，再交给 `$viralx-agent` 完成采集、逐帧检查、报告生成与校验。**搜索结束不是分析完成**。这个 Skill 不调用外部模型 API，但仍受 Codex 使用额度、当地网络与采集依赖影响。

## 证据与效果边界

- **提交原片不等于逐帧穷尽。** 当前兼容请求层优先使用 `video_url` 与 `fps=2`；原片超过 96 MiB，或服务返回特定格式 / 大小错误时，转为时间戳抽帧。实际输入记录在证据包的 `video_input` 中。
- **没有看到，不自动等于没有出现。** 抽样可能漏掉短暂画面，模型也可能识别错误；重要产品出现时刻与精确剪辑点应回看原片核验。ShotLoom 可以补充镜头索引，但不是绝对准确的裁判。
- **缺失证据必须保留缺失状态。** 有评论数量不等于取得评论正文；字幕 / ASR 不足时，不推断具体台词、音乐或音效。
- **校验通过不等于事实全对。** 引用和目标产品规则用于发现部分问题，不能证明每条结论准确，也不能证明某种剪辑方式导致视频走红。
- **复刻迁移结构，不承诺流量。** 尽量贴近原片节奏、效果和转化位置，替换为用户产品及可合法使用的素材；不得编造卖点或保证复刻后同样爆款。

## 运行边界

公开网页只负责输入、状态、结果和可选会话级 BYOK；ViralX Worker 集中运行搜索、采集、镜头取证和模型调用。公开 Worker 不挂载设置写入、缓存清理、文件系统导出或 LibTV 账号控制端点，浏览器也不能指定服务器 Cookie、代理、目录或 LibTV 运行方式。API Key、Cookie、代理地址和代理凭据不会出现在健康状态、分析结果或日志中。

本地开发、Worker 配置和故障排查见 [使用指南](docs/USAGE.md)，其他文档见 [文档索引](docs/README.md)。README 只描述产品能力，不包含站点部署步骤或个人环境信息。

## Web API 与结果合同

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 无密钥的运行时与模型就绪状态 |
| `/api/keywords` | GET | 常用主题 |
| `/api/analyze` | POST | NDJSON 流式分析 |
| `/api/jobs` | POST | 托管网页快速提交后台分析任务 |
| `/api/jobs/:id/events` | GET | 以短响应增量取回原 NDJSON 进度 |
| `/api/tasks/:id` | GET | 获取有效检查点的状态与可恢复结果 |
| `/api/tasks/:id/resume` | POST | 从检查点复核报告或重新终审 |
| `/api/jobs/tasks/:id/resume` | POST | 托管网页以后台任务方式恢复终审 |
| `/api/generate_variants` | POST | 基于已完成证据报告生成脚本变体 |

本地 Flask 另外提供设置、缓存、文件导出与可选 LibTV 管理接口；这些管理能力不属于公开 Worker。

关键结果字段按阶段返回，不把省略字段理解为成功：

| 字段 | 阅读方式 |
| --- | --- |
| `pipeline_status` / `pipeline_stage` | 整体结果与发生成功、阻断或错误的阶段 |
| `model_status` / `model_grounding_error` | 区分模型调用失败与报告校验未通过 |
| `evidence_bundle.video_input` | 视频输入状态、原片哈希、实际传输方式；如 `video-base64` 或 `timeline-frames` |
| `shot_provider` / `shot_status` | 视觉路径与对应状态；默认原片模式不代表额外运行过 ShotLoom |
| `shot_evidence_quality` | 专业镜头路径的覆盖信息，可能为空；不能据此默认原片已被完整理解 |
| `fallback_used` / `fallback_chain` | 专业镜头引擎的回退记录，不代替视频输入的传输方式记录 |
| `task_id` / `retry_scope` / `expires_at` | 有效检查点提供的续跑信息；不是每条结果都有可用检查点 |

## 架构

```text
Browser
├── 首页与设置页
├── 可选会话级 BYOK
├── 流式进度、报告阅读与 Markdown 源码复制
└── 同源任务 API → owner-operated ViralX Worker
    ├── TikTok multi-source search（关键词发现、自动切换、合并与去重）
    ├── TK Note（缓存 / 搜索媒体提示 / yt-dlp / 隔离 Chrome）
    ├── source-video preparation（原片输入、哈希与目标产品）
    ├── ShotLoom Core（可选专业镜头索引）
    ├── official LibTV CLI（可选回退）
    ├── evidence merge + quality gates
    └── selected visual model（优先接收原片，记录兼容降级）
```

## 项目结构

```text
ViralX/
├── .agents/skills/viralx-agent/    Codex 原生分析 Skill
├── .agents/skills/viralx/          ViralX Web API Skill
├── .agents/skills/tk-note/         原片、字幕与平台证据采集 Skill
├── .github/                        CI 与贡献指南
├── docs/                           使用指南、第三方许可与流程图
├── scripts/                        构建、启动管理与资产生成工具
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

GitHub Actions 检查 Python 3.10、3.11、3.12 与网页构建。测试覆盖搜索归一化、流式响应、证据校验、检查点恢复及接口边界；状态以页首动态 CI 徽章为准。

```bash
python -m unittest discover -s tests -p "test_*.py"
```

自动化测试通过不等于真实 TikTok 下载、第三方搜索和模型 API 始终可用，也不代表视觉识别准确率或复刻效果已被验证。

## 设计与动效

- 中性画布、双悬浮导航与深色证据工作台。
- Hanken Grotesk + Noto Sans SC，主标题使用项目字体资产。
- GSAP + ScrollTrigger，并为 `prefers-reduced-motion` 完整降级。
- 桌面与移动端保持同一任务顺序；运行状态只来自真实后端事件。

完整约束见 [DESIGN.md](DESIGN.md)。

## License

[MIT](LICENSE)。ShotLoom 适配来源与第三方许可见 [第三方许可说明](docs/THIRD_PARTY_NOTICES.md)。
