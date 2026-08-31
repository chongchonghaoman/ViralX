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
关键词 ─→ TikTok Scraper7 ─┐
                           ├→ TK Note 下载真实原片与平台证据
视频直链 ──────────────────┘
                                  ↓ 同一份本地原片
                         ShotLoom Core 镜头取证
                                  ↓ 必要时回退 LibTV
                         统一证据包 + 质量门禁
                                  ↓ 仅证据文本
                            最终模型分析
```

面向人的产品界面是 Web；需要 Python、OpenCV、TK Note、本地缓存或 LibTV CLI 登录态的能力由本机 Connector 执行。仓库同时提供 Agent-native Skill，让 Codex 等 Agent 直接运行同一套证据方法，不需要第二套客户端界面。

## 本次重点更新：从“模型猜测”改为“证据流水线”

这次重构首先解决四个问题：找的是不是目标视频、下载的是不是同一条原片、模型实际看到了什么、证据失败后系统是否会停止。

- **ShotLoom Core 成为默认镜头引擎**：直接读取 TK Note 下载的 `source.mp4`，不重复下载或上传；保留真实快切并过滤检测噪声。
- **LibTV 改为可选备用**：支持 `自动 / 仅 ShotLoom / 仅 LibTV / 只采集`；自动模式只在本地镜头证据不可用或质量不合格时回退。
- **镜头模型与最终模型分工**：镜头模型只描述关键帧中直接可见的事实；最终模型只读取合并证据，负责区分事实、推断和建议。
- **统一证据合同**：镜头层输出 `viralx.shot_evidence.v1`，合并层输出 `viralx.evidence_bundle.v1`；每个镜头都有 ID、时间范围、关键帧、视觉事实、未知项、置信度和原片哈希。
- **质量门禁阻止猜测**：时间线覆盖不足、镜头 ID 冲突、原片哈希缺失或视觉事实为空时，最终模型不会运行。
- **报告引用门禁**：事实必须引用真实 `[SHOT:Sxxx]`、`[META:*]` 或 `[TK:*]`；没有评论正文时不得声称“用户认为”。
- **搜索与下载身份核对**：搜索候选和 TK Note 下载结果的视频 ID 必须一致，避免搜索链接与实际原片错配。
- **声音证据单独取证**：声音、台词和字幕只能来自 TK Note 字幕或 ASR，不能从静态关键帧推断。
- **失败成为正式状态**：采集、镜头、合并或模型任一阶段失败都会明确阻断，不再把“任务结束”写成“可信分析完成”。
- **Agent-native Skill**：`$viralx-agent` 使用 TK Note、FFmpeg 和当前 Codex 模型完成取证与分析，不要求用户额外购买模型 API。

原有能力继续保留：TikTok Scraper7 关键词发现、品类消歧、TK Note、共享 Whisper / Qwen3-ASR、ShotLoom、可选 LibTV、Obsidian 导出、模型预设、自定义 API、Web API Skill 和 Agent-native Skill。

![ViralX 网页设置](docs/assets/viralx-settings.png)

## 工作逻辑

![ViralX 证据优先分析流程](docs/assets/viralx-workflow.svg)

流程图源码：[docs/assets/viralx-workflow.mmd](docs/assets/viralx-workflow.mmd)

| 阶段 | 责任 | 成功条件 | 失败后的行为 |
| --- | --- | --- | --- |
| 01 · 发现视频 | 关键词通过 TikTok Scraper7 找候选；直链跳过 | 可打开的真实帖子 URL 与平台指标 | 没有候选就停止 |
| 02 · TK Note 采集 | 下载原片、元数据、字幕 / ASR、评论与资产清单 | 原片非空；可核验帖子 ID 一致 | 阻断镜头与模型 |
| 03 · 镜头取证 | ShotLoom Core 默认；LibTV 可回退 | 完整时间线、镜头 ID、视觉事实、原片哈希 | 回退仍失败则阻断 |
| 04 · 合并证据 | 合并平台、TK Note 与镜头证据 | `viralx.evidence_bundle.v1` | 保存部分证据并阻断最终模型 |
| 05 · 最终分析 | 只基于命名证据生成事实、推断与创意提案 | 每项事实引用对应证据 | 拦截不可信输出 |

三个角色不能混淆：

- TikTok Scraper7 是**关键词发现器**，不是原片下载器。视频直链不需要 RapidAPI。
- TK Note 是**原片和平台证据采集器**，后续镜头引擎分析的是它交出的同一份文件。
- 最终模型是**证据综合器**，不是失败后的兜底视频解析器。

## 使用方式与 API 边界

| 使用方式 | 必需项 | 可选项 |
| --- | --- | --- |
| 粘贴单条 TikTok / 抖音链接 | 本机 Connector、可用镜头引擎、最终模型 API | LibTV 备用；RapidAPI 不需要 |
| 输入关键词搜索并分析 | 上述配置 + TikTok Scraper7 `RAPIDAPI_KEY` | LibTV 备用 |
| `只采集` 模式 | 本机 Connector + TK Note | 不调用镜头模型和最终模型 |
| Codex 中使用 `$viralx-agent` | Codex 当前模型、Python、FFmpeg；直链再需要 TK Note | **不需要独立模型 API**；关键词发现服务另算 |

ShotLoom Core 的视觉事实抽取需要支持图片输入的模型。DeepSeek 等纯文本模型可以承担最终证据综合，但不能直接替代视觉镜头模型。LibTV 只在被明确选择或自动回退时需要官方 CLI 登录。

## 网页能力

| 能力 | 实际行为 |
| --- | --- |
| TikTok Scraper7 搜索 | 调用 `/feed/search`，归一化候选、帖子 ID、分享链接和互动数据，并进行语义筛选 |
| 品类消歧 | 区分 `picture light` 与 `light painting` 等相邻但不同的内容 |
| TK Note 采集 | 保存原片、元数据、字幕 / ASR、评论证据、资产清单和警告 |
| ShotLoom Core | 本地切镜、关键帧采样、视觉事实抽取和时间线质量检查 |
| LibTV 备用 | 通过官方 CLI 登录，在回退或显式选择时生成拉片证据 |
| 最终模型 | 支持常见模型服务和自定义兼容接口，只读取统一证据包 |
| 流式进度 | NDJSON 返回发现、采集、镜头、合并和最终分析五个真实阶段 |
| 审计文件 | 保存证据包、镜头证据和最终原始输出，便于追查结论 |
| Obsidian | 本地写入，或生成 URI / 下载 Markdown |

## 在 Codex 中直接调用 ViralX

仓库提供两个职责不同、可同时安装的 Skill：

| Skill | 模型在哪里运行 | 独立模型 API Key |
| --- | --- | --- |
| [`$viralx-agent`](.agents/skills/viralx-agent) | 当前 Codex 会话 | **不需要** |
| [`$viralx`](.agents/skills/viralx) | ViralX Web / Connector 配置的模型 | 完整分析需要 |

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

## 本地启动 Web 工作台

环境要求：Python 3.10–3.12。

```bash
python -m pip install -r requirements.txt
cp config.json.example config.json
python web_app.py
```

Windows PowerShell：

```powershell
python -m pip install -r requirements.txt
Copy-Item config.json.example config.json
python web_app.py
```

浏览器打开 `http://127.0.0.1:5001/settings` 完成配置。`config.json`、模型 Key、浏览器 Cookie、代理凭据、下载原片和本地缓存都不应提交到 Git。

最小配置示例：

```json
{
  "analysis_mode": "pipeline",
  "shot_engine": "auto",
  "shot_model_source": "inherit",
  "model_provider": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_name": "YOUR_MODEL_NAME",
  "rapidapi_key": "ONLY_FOR_KEYWORD_SEARCH"
}
```

## 配置合同

| 设置 / 环境变量 | 作用 | 必需性 |
| --- | --- | --- |
| `RAPIDAPI_KEY` | TikTok Scraper7 关键词搜索 | 仅关键词搜索 |
| `VIRALX_SHOT_ENGINE` | `auto`、`shotloom`、`libtv`、`skip` | 默认 `auto` |
| `SHOT_MODEL_SOURCE` | `inherit`、`qwen`、`custom` | ShotLoom 模式 |
| `SHOT_MODEL_API_KEY` | 独立镜头视觉模型 Key | Qwen / custom |
| `SHOT_MODEL_BASE_URL` | 独立镜头模型 API 根地址 | Qwen / custom |
| `SHOT_MODEL_NAME` | 独立镜头模型 ID | Qwen / custom |
| `MODEL_PROVIDER` | 最终模型服务商 | 完整分析 |
| `MODEL_API_KEY` | 最终模型 Key | 完整分析 |
| `MODEL_NAME` | 最终模型 ID | 完整分析 |
| `MODEL_BASE_URL` / `MODEL_PROTOCOL` | 自定义最终模型接口 | 自定义 provider |
| `LIBTV_CLI_BINARY` | 官方 LibTV CLI 路径 | 仅 LibTV 模式或回退 |
| `RIMAGINATION_NOTE_CACHE` | TK Note 下载与 ASR 共享缓存 | 可选 |
| `TK_NOTE_PROXY` | 覆盖系统代理的 TK Note 显式代理 | 可选 |
| `TK_NOTE_COOKIES_FROM_BROWSER` | yt-dlp 浏览器 Cookie 来源 | 仅登录墙阻断时 |
| `TK_NOTE_TIMEOUT` | 单条 TK Note 采集等待上限 | 默认 1800 秒 |

API Key、Cookie、代理地址和代理凭据不会出现在健康状态、Connector 状态、分析结果或日志中。

## Web API 与结果合同

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 无密钥的运行时与模型就绪状态 |
| `/api/keywords` | GET | 常用主题 |
| `/api/analyze` | POST | NDJSON 流式分析 |
| `/api/export-obsidian` | POST | 本地写入或浏览器导出 |
| `/api/libtv/auth/*` | GET / POST | 本地官方 CLI 授权；仅在选择 LibTV 时需要 |

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
├── 会话级 BYOK
├── 流式进度、报告与导出
└── 127.0.0.1 ViralX Connector
    ├── TikTok Scraper7（仅关键词发现）
    ├── TK Note / yt-dlp（原片与平台证据）
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
├── local_connector.py              loopback 安全边界
├── web_app.py                      本地 Flask Web API
├── tests/                          后端、前端、Connector 与证据合同测试
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
