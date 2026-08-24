# ViralX

AI驱动的 TikTok 美区爆款视频分析工具

![ViralX](logo.png)

## 核心功能

### LibTV 一键拉片（默认）
- 使用官方 [`libtv-skill`](https://github.com/libtv-labs/libtv-skills) 上传原视频
- 自动创建会话、增量轮询拉片结果，并返回 LibTV 项目画布
- 8 秒轮询、3 分钟超时、连续查询失败保护均可配置
- Gemini / OpenRouter 保留为兼容分析模式，MiniMax 继续用于复刻脚本

### 视频分析
- 爆款视频搜索（RapidAPI TikTok 数据，5000+ 点赞过滤）
- 支持直接粘贴抖音 / TikTok 单条视频链接
- 视频一键下载（yt-dlp）并交给 LibTV 拉片
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

Linear 风格的深色主题 UI，支持设置页面配置 API 密钥。

## 快速开始

环境要求：Python 3.10+、Node.js 18+（仅桌面版需要 Node.js）。

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

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主界面 |
| `/settings` | GET | 设置页面 |
| `/api/analyze` | POST | 流式分析视频 |
| `/api/keywords` | GET | 获取已缓存关键词 |
| `/api/export-obsidian` | POST | 导出到 Obsidian |
| `/api/generate_variants` | POST | 生成裂变变体 |
| `/api/cache/clear` | POST | 清除分析缓存 |

## 技术栈

- **AI**: LibTV Agent-IM, MiniMax M2.7, Google Gemini 2.5 Flash, OpenRouter (NVIDIA)
- **后端**: Python Flask
- **前端**: HTML/CSS/JavaScript (Linear 风格深色主题)
- **桌面**: Electron
- **数据**: RapidAPI TikTok Scraper

## 项目结构

```
ViralX/
├── .agents/skills/libtv-skill/ # 官方 LibTV Skill
├── libtv_analyzer.py        # LibTV 上传/会话/轮询适配器
├── ai_analyzer.py          # AI 分析引擎
├── tiktok_viral_analyzer.py # TikTok 数据获取
├── web_app.py              # Web 服务 + API
├── export_to_obsidian.py   # Obsidian 导出
├── main.js                 # Electron 入口
├── templates/
│   ├── index.html          # 主界面
│   └── settings.html       # 设置页面
├── package.json
└── requirements.txt
```

## 验证

```bash
python -m unittest discover -s tests -v
```

单元测试使用模拟的 LibTV 响应，不需要真实 Access Key。真实联调需配置
`LIBTV_ACCESS_KEY`，并确保输入视频不超过 200MB。

## License

MIT
