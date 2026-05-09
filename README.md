# ViralX

AI驱动的 TikTok 美区爆款视频分析工具

![ViralX](logo.png)

## 核心功能

### AI 多模态分析
- **OpenRouter (NVIDIA)** - 视频帧逐秒分析，免费使用
- **Gemini 2.5 Flash** - 视频帧多模态理解
- **MiniMax M2.7** - 纯文本深度分析

### 视频分析
- 爆款视频搜索（RapidAPI TikTok 数据，5000+ 点赞过滤）
- 视频一键下载（yt-dlp）
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

### 1. 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 2. 配置

编辑 `config.json`：

```json
{
  "rapidapi_key": "YOUR_RAPIDAPI_KEY",
  "minimax_api_key": "YOUR_MINIMAX_API_KEY",
  "openrouter_api_key": "YOUR_OPENROUTER_KEY",
  "search_keywords": ["outdoor lighting lamp"],
  "min_likes": 5000
}
```

API 获取地址：
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

- **AI**: MiniMax M2.7, Google Gemini 2.5 Flash, OpenRouter (NVIDIA)
- **后端**: Python Flask
- **前端**: HTML/CSS/JavaScript (Linear 风格深色主题)
- **桌面**: Electron
- **数据**: RapidAPI TikTok Scraper

## 项目结构

```
ViralX/
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

## License

MIT