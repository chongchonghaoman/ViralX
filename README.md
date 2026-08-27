<p align="center">
  <img src="static/assets/viralx-signal-orbit-1024.webp" width="420" alt="ViralX 短视频证据工作台主视觉">
</p>

<h1 align="center">ViralX</h1>

<p align="center">
  <strong>把爆款拆到每一秒，也把每个结论还给证据。</strong><br>
  浏览器里的短视频发现、取证、逐镜分析与复刻工作台。
</p>

<p align="center">
  <a href="https://viralx.metrolabs.mobi"><img alt="Live website" src="https://img.shields.io/badge/Live-viralx.metrolabs.mobi-4DC5E5?style=flat-square"></a>
  <a href="https://github.com/chongchonghaoman/ViralX/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/chongchonghaoman/ViralX/ci.yml?branch=main&style=flat-square&label=tests"></a>
  <a href=".agents/skills/viralx"><img alt="Codex Skill" src="https://img.shields.io/badge/Codex-Skill-4DC5E5?style=flat-square"></a>
  <img alt="Web product" src="https://img.shields.io/badge/Product-Web-111111?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10--3.12-3776AB?style=flat-square">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-111111?style=flat-square"></a>
</p>

<p align="center">
  <a href="https://viralx.metrolabs.mobi">打开 ViralX</a> ·
  <a href="https://viralx.metrolabs.mobi/settings.html">网页设置</a> ·
  <a href="DESIGN.md">设计合同</a> ·
  <a href="DEPLOYMENT.md">部署说明</a>
</p>

<p align="center"><sub>2026-08-27 · Shot evidence pipeline</sub></p>

![ViralX 网页首页](docs/assets/viralx-homepage.png)

## ViralX 是什么

ViralX 是一个证据优先的短视频拆解 Web 应用。它不是把视频链接直接丢给大模型，而是先确认来源、下载真实原片、生成可核验的逐镜事实，再让最终模型做综合判断。

```text
关键词 ─→ TikTok Scraper7 ─┐
                           ├→ TK Note 下载真实原片与平台证据
视频直链 ──────────────────┘
                                  ↓ 同一份本地原片
                         ShotLoom Core 镜头取证
                                  ↓ 失败时可回退 LibTV
                         统一证据包 + 质量门禁
                                  ↓ 仅证据文本
                            最终模型 API
```

产品只有一种交付形态：**Web**。生产界面部署在 EdgeOne；需要 Python、OpenCV、TK Note、本地缓存或 LibTV CLI 登录态的工作由本机 Connector 执行。Connector 是最小安全桥，不是另一套桌面客户端。

## 本次重点更新：第一原理重构

这次优化先回答四个最基础的问题：找的是不是目标视频、下载的是不是同一条原片、模型看到了什么证据、证据失败后系统是否会停。

- **ShotLoom Core 成为默认镜头引擎**：直接读取 TK Note 已下载的 `source.mp4`，不重复下载、不重复上传。ViralX 适配了 ShotLoom 的 PySceneDetect 双检测思路，并修正了上游丢弃全部 `< 0.5s` 片段的问题；现在只合并 `< 80ms` 的检测噪声，真实快切会被保留。
- **LibTV 从强制前置改为可选备用**：设置支持 `自动 / 仅 ShotLoom / 仅 LibTV / 只采集`。自动模式优先 ShotLoom Core；只有本地依赖、视觉模型或证据质量不合格时才回退 LibTV，并把原因写入 `fallback_chain`。
- **镜头模型与最终模型拆开**：镜头模型只回答关键帧中直接可见的事实，禁止输出钩子、受众、留存、转化和优化建议；最终模型只读取合并证据，不再接收原视频路径。
- **统一证据合同**：镜头层输出 `viralx.shot_evidence.v1`，合并层输出 `viralx.evidence_bundle.v1`。每条镜头带 `S001` 形式的 ID、开始/结束时间、关键帧时间、视觉事实、未知项、置信度和原片 SHA-256。
- **质量门禁阻止猜测**：镜头时间线覆盖率低于 98%、已分析覆盖率低于 90%、镜头 ID 重复、原片哈希缺失或任一镜头没有视觉事实，都会阻断最终模型。
- **报告引用门禁**：最终报告必须引用真实存在的 `[SHOT:Sxxx]`，以及相应 `[META:*]`、`[TK:*]` 来源。没有评论正文时不得声称“用户认为”，没有标签时不得生成具体标签。
- **搜索与下载身份核对**：搜索候选包含可核验数字 TikTok 帖子 ID 时，TK Note 下载结果必须与它一致；不一致就停在采集阶段，避免“链接是假的但模型仍然分析”。
- **声音证据只有一个来源**：关键帧不能证明声音、配音或台词。音频文字只能来自 TK Note 字幕 / ASR，并明确记录转写来源与警告。
- **失败成为产品状态**：`blocked`、`fallback_used`、`shot_block_reason`、`fallback_chain`、`shot_evidence_quality` 都会进入流式结果和前端，不再把“云端在线”或“任务跑完”误写成“可信分析完成”。
- **设置页按职责重构**：先选镜头引擎，再单独配置镜头视觉模型，最后配置最终模型。DeepSeek 等纯文本模型可以做最终综合，但不能被误用为 ShotLoom 视觉模型。
- **EdgeOne 边界保持诚实**：线上页面负责界面、会话设置与结果呈现；本机 Connector 才能读取原片和运行 OpenCV。API Key 只存当前标签页并发送到 `127.0.0.1`，不经过 EdgeOne。
- **Connector 自动接管旧实例**：从 `1.2.0` 起，再次启动 Connector 会先让 57231 上已经确认的 ViralX 实例优雅退出，等待端口释放后启动当前版本并重新打开配对页；不会结束占用该端口的非 ViralX 程序。

原有能力全部保留：TikTok Scraper7 搜索、`picture light` 与 `light painting` 品类消歧、TK Note、共享 Whisper / Qwen3-ASR、LibTV 官方网页登录、Obsidian 导出、本地 Flask、EdgeOne 页面、模型预设、自定义 API 和 Codex Skill。

![ViralX 网页设置](docs/assets/viralx-settings.png)

## 工作逻辑

![ViralX 证据优先分析流程](docs/assets/viralx-workflow.svg)

流程图源码：[docs/assets/viralx-workflow.mmd](docs/assets/viralx-workflow.mmd)

| 阶段 | 责任 | 成功条件 | 失败后的行为 |
| --- | --- | --- | --- |
| 01 · 发现视频 | 关键词通过 TikTok Scraper7 找候选；直链跳过 | 可打开的真实帖子 URL 与平台指标 | 没有候选就停止 |
| 02 · TK Note 采集 | 下载原片、元数据、字幕 / ASR、评论与资产清单 | 原片非空；可核验帖子 ID 一致 | 阻断镜头与模型 |
| 03 · 镜头取证 | ShotLoom Core 默认；LibTV 可回退 | 完整时间线、镜头 ID、视觉事实、原片哈希 | 自动模式回退；仍失败则阻断 |
| 04 · 合并证据 | 合并平台、TK Note 与镜头证据 | `viralx.evidence_bundle.v1` | 保存部分证据并阻断最终模型 |
| 05 · 最终分析 | 只基于命名证据生成事实、推断与创意提案 | 具体事实引用对应来源和镜头 ID | 拦截不可信原始输出 |

三个不能混淆的角色：

- TikTok Scraper7 是**关键词发现器**，不是原片下载器。视频直链不需要 RapidAPI。
- TK Note 是**原片和平台证据采集器**，ShotLoom / LibTV 都只能分析它交出的同一份文件。
- 最终模型是**证据综合器**，不是兜底视频解析器。镜头证据失败时它不会被调用。

## 现在需要哪些 API

| 使用方式 | 必需项 | 可选项 |
| --- | --- | --- |
| 粘贴单条 TikTok / 抖音链接 | 本机 Connector、可用镜头引擎、最终模型 API | LibTV 备用、RapidAPI 不需要 |
| 输入关键词搜索并分析 | 上述配置 + TikTok Scraper7 `RAPIDAPI_KEY` | LibTV 备用 |
| `只采集` 模式 | 本机 Connector + TK Note | 镜头模型和最终模型都不调用 |

ShotLoom Core 需要一个支持 OpenAI Chat Completions 图片输入的视觉模型。可以：

1. 复用最终模型，但它必须是 OpenAI-compatible 且支持视觉；
2. 使用 Qwen VL；
3. 使用自定义 OpenAI-compatible 视觉接口。

DeepSeek 当前预设是纯文本最终模型，不能直接承担关键帧识别。LibTV 只在 `auto` 回退或显式选择 `libtv` 时需要官方 CLI 网页登录。

## 网页能力

| 能力 | 实际行为 |
| --- | --- |
| TikTok Scraper7 搜索 | 固定调用 `/feed/search`，归一化 `data.videos`、数字帖子 ID、分享链接和互动数据，按语义相关性优先排序 |
| `picture light` 消歧 | 把照画灯 / 壁画灯识别为安装在画作上方的灯具，剔除 `light painting / glowing painting` 等“画本身发光”结果 |
| TK Note 采集 | 保存原片、元数据、字幕 / ASR、评论证据、资产清单和警告；复用本机共享 ASR 环境 |
| ShotLoom Core | 本地双检测切镜、关键帧采样、视觉事实抽取、时间线质量检查；不输出营销判断 |
| LibTV 备用 | 通过官方 CLI 网页登录，在自动回退或显式选择时生成画布与拉片证据 |
| 最终模型 | OpenAI、Claude、Gemini、DeepSeek、OpenRouter 或自定义 API；只读取统一证据包 |
| 流式进度 | NDJSON 返回发现、采集、镜头取证、证据合并、最终分析五个真实阶段 |
| 审计文件 | 保存证据包、镜头证据和最终模型原始输出，便于追查每个结论 |
| Obsidian | 本地写入，或在线生成 URI / 下载 Markdown |

## 在 Codex 中直接调用 ViralX

仓库继续提供可安装的 Codex Skill。把下面的 GitHub 地址发给另一台电脑上的 Codex：

```text
https://github.com/chongchonghaoman/ViralX/tree/main/.agents/skills/viralx
```

对 Codex 说：

```text
请安装这个仓库的 .agents/skills/viralx，然后用 $viralx 分析：
https://www.tiktok.com/@creator/video/1234567890123456789
```

或使用内置安装脚本：

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo chongchonghaoman/ViralX `
  --path .agents/skills/viralx
```

Skill 调用 ViralX 的 Web API 合同。全功能分析仍需要目标电脑运行本地 Flask，或让网页通过 Connector 连接这台电脑；EdgeOne 不会伪装拥有目标电脑的原片、OpenCV 或 LibTV 登录态。凭据应写入目标电脑环境变量或本地设置，不要发送到聊天。

## 在线使用

1. 安装依赖并启动 Connector：

   ```bash
   python -m pip install -r requirements.txt
   python connector.py
   ```

2. Connector 只监听 `127.0.0.1:57231`，会打开 [ViralX 设置页](https://viralx.metrolabs.mobi/settings.html)并完成一次性配对。
   再次运行同一个启动命令即可替换旧实例，不需要先查端口或手动结束 Python 进程。
3. 选择镜头引擎。默认 `自动`：ShotLoom Core 优先，LibTV 备用。
4. 配置镜头视觉模型和最终模型；关键词搜索再填写 TikTok Scraper7 Key。
5. 返回 [ViralX 首页](https://viralx.metrolabs.mobi)，粘贴视频或输入主题。

Connector 精确允许 `https://viralx.metrolabs.mobi`，拒绝其他 Origin；配对密钥只存在 URL fragment、本机内存和当前标签页。模型 Key 不经过 EdgeOne，也不会写入日志。

## 本地运行

环境要求：Python 3.10–3.12。构建 EdgeOne 页面时需要 Node.js 18+。

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

打开 `http://127.0.0.1:5001/settings` 完成配置。

最小配置示例：

```json
{
  "analysis_mode": "pipeline",
  "shot_engine": "auto",
  "shot_model_source": "inherit",
  "model_provider": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_name": "gpt-4.1-mini",
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
| `SHOT_SCENE_THRESHOLD` | 切镜阈值，默认 27 | 可选 |
| `MODEL_PROVIDER` | `openai`、`anthropic`、`gemini`、`deepseek`、`openrouter`、`custom` | 完整分析 |
| `MODEL_API_KEY` | 最终模型 Key | 完整分析 |
| `MODEL_NAME` | 最终模型 ID | 完整分析 |
| `MODEL_BASE_URL` / `MODEL_PROTOCOL` | 自定义最终模型接口 | 自定义 provider |
| `LIBTV_CLI_BINARY` | 官方 LibTV CLI 路径 | 仅 LibTV 模式或回退 |
| `RIMAGINATION_NOTE_CACHE` | TK Note 下载与 ASR 共享缓存 | 可选 |

API Key 不会出现在 `/api/health`、Connector 状态、分析结果或日志中。

## Web API 与结果合同

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 无密钥的运行时、镜头引擎和最终模型就绪状态 |
| `/api/keywords` | GET | 常用主题 |
| `/api/analyze` | POST | NDJSON 流式分析 |
| `/api/export-obsidian` | POST | 本地写入或浏览器导出 |
| `/api/libtv/auth/*` | GET / POST | 本地官方 CLI 网页授权；只在 LibTV 被选择时需要 |

关键结果字段：

```json
{
  "pipeline_status": "completed | blocked | error",
  "shot_provider": "shotloom | libtv | none",
  "shot_model": "model-id",
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

## Web 架构

```text
Browser / EdgeOne
├── 首页与设置页
├── 会话级 BYOK
├── 流式进度、报告与导出
└── http://127.0.0.1:57231
    └── ViralX Connector
        ├── TikTok Scraper7（仅关键词发现）
        ├── TK Note / yt-dlp（原片与平台证据）
        ├── ShotLoom Core（默认镜头证据）
        ├── official LibTV CLI（可选回退）
        ├── evidence merge + quality gates
        └── selected final model API（只接收证据）
```

## 项目结构

```text
ViralX/
├── .agents/skills/viralx/          Codex 可安装 Skill
├── templates/                      首页与设置页
├── static/                         设计 token、GSAP 动效与交互
├── cloud-functions/                EdgeOne 公开安全 API
├── tiktok_viral_analyzer.py        Scraper7 搜索与语义筛选
├── video_ingest.py                 TK Note / yt-dlp 原片采集
├── shot_analyzers.py               ShotLoom Core、LibTV adapter、质量门禁
├── libtv_analyzer.py               官方 CLI 登录与拉片实现
├── ai_analyzer.py                  证据流水线与最终报告门禁
├── local_connector.py              loopback 安全边界
├── web_app.py                      本地 Flask Web API
├── tests/                          后端、前端、Connector 与证据合同测试
├── DESIGN.md                       视觉、交互与状态合同
└── DEPLOYMENT.md                   EdgeOne 与本地运行边界
```

## 测试与部署

```bash
python -m unittest discover -s tests -p "test_*.py"
npm run build:edgeone
npm run deploy:edgeone
```

生产域名：[viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。构建产物写入已忽略的 `public/`，不复制本机 `config.json` 或任何密钥。详见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 设计与动效

- Butter 式中性画布、双悬浮导航与深色证据工作台；不复制 Butter 的品牌资产或文案。
- Hanken Grotesk + Noto Sans SC，主标题使用用户提供字体生成的轮廓 SVG。
- GSAP 3.13 + ScrollTrigger；`prefers-reduced-motion` 下完整降级。
- 同一套桌面与移动任务顺序；运行状态来自真实后端事件。

详见 [DESIGN.md](DESIGN.md)。

## License

[MIT](LICENSE)。ShotLoom 适配来源与第三方许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
