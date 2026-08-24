# ViralX

AI驱动的 TikTok 美区爆款视频分析工具

![ViralX](logo.png)

## 核心功能

### TK Note 稳定采集（国际 TikTok）
- 高强度继承 DyNote 的资产优先体验：稳定文件名、断点复用、`--force` 刷新、stderr JSON 进度与部分成功
- 使用本地 `yt-dlp` 下载原视频与安全元数据，字幕优先；没有字幕时再使用共享 Qwen3-ASR 或 Whisper
- 每条视频保存 `source.mp4`、元数据、转写、笔记预算和 `assets/asset_manifest.json`
- 评论采集是可选路线；即使被 TikTok 风控拦截，也不会阻断视频继续交给 LibTV

### LibTV 一键拉片（默认）
- 使用官方 [`libtv-skill`](https://github.com/libtv-labs/libtv-skills) 上传 TK Note 准备好的同一份原视频
- 自动创建会话、增量轮询拉片结果，并返回 LibTV 项目画布
- 8 秒轮询、3 分钟超时、连续查询失败保护均可配置
- Gemini / OpenRouter 保留为兼容分析模式，MiniMax 继续用于复刻脚本

### 视频分析
- 爆款视频搜索（RapidAPI TikTok 数据，5000+ 点赞过滤）
- 支持直接粘贴抖音 / TikTok 单条视频链接
- 国际 TikTok 使用 TK Note；抖音等兼容链接保留通用 yt-dlp 路线
- 评论抓取与情感分析

### 流式分析
- 边分析边返回结果，实时进度展示
- 并发处理多个视频
- 分析结果自动缓存

### 脚本生成
- 爆款脚本结构拆解
- 裂变变体脚本生成（4 种不同角度改编）

### 数据导出
- 导出至 Obsidian 知识库
- Markdown 格式保存

## 界面预览

受 Butter 产品叙事启发的亮色网站界面，将短视频证据链、真实分析入口和设置页统一到同一套设计系统；支持桌面端、移动端、键盘操作与减弱动效偏好。

## 快速开始

环境要求：Python 3.10+、Node.js 18+（桌面版和 EdgeOne 网站构建需要 Node.js）。

### 1. 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 2. 配置

复制示例并编辑 `config.json`：

```bash
cp config.json.example config.json
```

```json
{
  "rapidapi_key": "YOUR_RAPIDAPI_KEY",
  "analysis_mode": "libtv",
  "libtv_access_key": "YOUR_LIBTV_ACCESS_KEY",
  "libtv_im_base": "https://im.liblib.tv",
  "libtv_poll_interval": 8,
  "libtv_timeout": 180,
  "libtv_concurrency": 2,
  "tk_note_asr_backend": "auto",
  "tk_note_language": "auto",
  "tk_note_cookies_from_browser": "",
  "tk_note_proxy": "",
  "tk_note_timeout": 1800,
  "video_cache_dir": "./video_cache",
  "minimax_api_key": "YOUR_MINIMAX_API_KEY",
  "search_keywords": ["outdoor lighting lamp"],
  "min_likes": 5000
}
```

也可以不把 LibTV Key 写入文件，而是设置环境变量：

```bash
export LIBTV_ACCESS_KEY="your-access-key"
```

Windows PowerShell：

```powershell
$env:LIBTV_ACCESS_KEY = "your-access-key"
```

API 获取地址：
- LibTV: https://www.liblib.tv/
- RapidAPI: https://rapidapi.com/DataFanatic/api/tiktok-scraper7
- MiniMax: https://www.minimaxi.com/
- OpenRouter: https://openrouter.ai/

TK Note 的视频、字幕和本地 ASR 主链不需要付费抓取 API。若确实需要评论：

```bash
pip install -r requirements-tk-comments.txt
playwright install chromium
```

评论依赖 TikTok 私有 Web 接口，可能还需要用户自己的 `TIKTOK_MS_TOKEN`、浏览器会话或代理；失败会明确标记为可选阶段受阻。

### 3. 运行

**Web 界面：**
```bash
python web_app.py
```

访问 http://localhost:5001

**桌面应用：**
```bash
npm start
```

**EdgeOne 云函数网站版：**

```bash
npm run build:edgeone
npm run preview:edgeone
npm run deploy:edgeone
```

公开站点：[https://viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。`deploy:edgeone` 默认更新绑定该域名的海外生产项目。

EdgeOne 版本通过 Python Cloud Functions 提供同源分析 API，并复用 TK Note / yt-dlp、LibTV 和现有 NDJSON 前端合同。网页设置页位于 `/settings.html`：API Key 只保存在当前标签页的 `sessionStorage`，经 HTTPS 随同源请求临时发送，关闭标签页后自动清除；不会写进静态文件或公开接口。云端函数最多处理 1 条视频，使用临时 `/tmp` 资产，并受 120 秒与 6MB 响应限制；本地 Flask 仍负责持久化设置、持久缓存、长任务和 Obsidian 文件系统直写。部署记录和当前配置状态见 `DEPLOYMENT.md`。

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主界面 |
| `/settings` | GET | 本地 Flask 持久化设置页面 |
| `/settings.html` | GET | EdgeOne 当前标签页临时设置页面 |
| `/api/health` | GET | 返回不含密钥的运行状态 |
| `/api/analyze` | POST | 流式分析视频 |
| `/api/keywords` | GET | 获取已缓存关键词 |
| `/api/export-obsidian` | POST | 导出到 Obsidian |
| `/api/generate_variants` | POST | 生成裂变变体 |
| `/api/cache/clear` | POST | 清除分析缓存 |

EdgeOne 只公开 `health`、`keywords`、`analyze`、`generate_variants` 与浏览器版 `export-obsidian`。`/settings.html` 是纯前端会话配置界面，不提供可读取密钥的设置 API；`/api/settings` 和 `/api/cache/clear` 仅保留在本地 Flask。

## 技术栈

- **AI**: LibTV Agent-IM, MiniMax M2.7, Google Gemini 2.5 Flash, OpenRouter (NVIDIA)
- **后端**: Python Flask
- **前端**: Flask templates、共享 CSS token、原生 JavaScript 与 GSAP / ScrollTrigger
- **云端网站**: EdgeOne Pages + Python Cloud Functions
- **桌面**: Electron
- **数据**: RapidAPI TikTok Scraper

## 项目结构

```
ViralX/
├── .agents/skills/
│   ├── libtv-skill/          # 官方 LibTV Skill
│   └── tk-note/              # 国际 TikTok 采集与证据 Skill
├── libtv_analyzer.py        # LibTV 上传/会话/轮询适配器
├── video_ingest.py         # TK Note / 通用 yt-dlp 采集路由
├── ai_analyzer.py          # 统一分析编排；只消费本地视频资产
├── tiktok_viral_analyzer.py # TikTok 数据获取
├── web_app.py              # Web 服务 + API
├── export_to_obsidian.py   # Obsidian 导出
├── main.js                 # Electron 入口
├── templates/
│   ├── index.html          # 主界面
│   └── settings.html       # 设置页面
├── static/                 # 共享 token、页面样式、交互与主视觉
├── cloud-functions/
│   ├── api/[[default]].py  # EdgeOne 公网安全 API
│   └── requirements.txt    # 云函数依赖
├── scripts/
│   └── build-edgeone.mjs   # 构建 EdgeOne 网站与云函数上传包
├── DESIGN.md               # 设计系统与交互边界
├── DEPLOYMENT.md           # EdgeOne 部署状态与运行时边界
├── edgeone.json            # EdgeOne 构建配置
├── package.json
└── requirements.txt
```

## 验证

```bash
python -m unittest discover -s tests -v
```

单元测试使用模拟的 TK Note 与 LibTV 响应，不需要真实 Access Key。真实联调需配置
`LIBTV_ACCESS_KEY`，并确保输入视频不超过 200MB。普通“开始拉片”会复用已有采集资产；界面的“刷新数据”才会强制重新下载/转写。

## License

MIT
