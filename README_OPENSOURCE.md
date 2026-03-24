# TikTok 爆款视频分析工具

一个用于分析 TikTok 爆款视频的 Web 应用，支持深度电商拆解、AI 分析和 Markdown 导出。

## 功能特性

- 🔍 **TikTok 视频搜索** - 搜索指定关键词的爆款视频（5000+ 点赞）
- 🤖 **AI 深度拆解** - 使用 MiniMax M2.7 进行专业电商分析
- 📊 **详细分析报告** - 包含 Hook、卖点、视听语言、流量密码、翻拍脚本等
- 🎨 **Linear 风格 UI** - 现代深色主题，极简交互设计
- 📱 **Modal 弹窗展示** - 完整 Markdown 格式的分析内容
- 💾 **缓存管理** - 快速加载已分析数据，支持强制刷新
- 🔄 **API 自动切换** - RapidAPI 配额用完自动切换备用 API

## 快速开始

### 环境要求
- Python 3.8+
- Flask
- Anthropic SDK
- requests

### 安装

```bash
git clone https://github.com/yourusername/tiktok-analyzer.git
cd tiktok-analyzer
pip install -r requirements.txt
```

### 配置

编辑 `config.json`：

```json
{
  "rapidapi_key": "YOUR_RAPIDAPI_KEY",
  "minimax_api_key": "YOUR_MINIMAX_API_KEY",
  "search_keywords": ["outdoor lighting lamp", "camping light"],
  "min_likes": 5000,
  "output_dir": "E:/tiktok_analyzer/data"
}
```

### 启动应用

```bash
python web_app.py
```

访问 http://localhost:5000

## 使用方式

1. **搜索视频** - 在侧边栏输入关键词或点击缓存关键词
2. **点击分析** - 使用缓存数据（快速）或点击刷新获取最新视频
3. **查看分析** - 点击"查看 AI 深度拆解"打开 Modal 查看完整分析
4. **打开原视频** - 点击视频标题跳转到 TikTok

## 项目结构

```
tiktok_analyzer/
├── web_app.py                 # Flask 应用主文件
├── ai_analyzer.py             # MiniMax M2.7 分析器
├── tiktok_viral_analyzer.py   # TikTok 搜索器
├── config.json                # 配置文件
├── templates/
│   └── index.html             # 前端 UI
├── data/                       # 分析结果缓存
└── README.md                  # 本文件
```

## API 端点

### GET /
返回 HTML 前端界面

### GET /api/keywords
获取已缓存的关键词列表

```json
{
  "keywords": [
    {"keyword": "outdoor lighting lamp", "cached": true}
  ]
}
```

### POST /api/analyze
分析指定关键词的视频

**请求：**
```json
{
  "keyword": "outdoor lighting lamp",
  "refresh": false
}
```

**响应：**
```json
{
  "status": "success",
  "total_videos": 10,
  "videos": [...],
  "source": "cache"
}
```

## 分析内容

每个视频的分析包含：

- **黄金3秒Hook** - 视觉和听觉拆解
- **核心卖点** - 5个主要卖点 + 视觉呈现
- **视听语言** - 节奏分析 + 光影运镜
- **流量密码** - 互动钩子 + 转化锚点
- **翻拍脚本** - 6个镜头的完整脚本表
- **风险提示** - 合规建议和复刻要点

## 配置说明

### RapidAPI
1. 访问 https://rapidapi.com/DataFanatic/api/tiktok-scraper7
2. 获取 API Key
3. 填入 `config.json` 的 `rapidapi_key`

### MiniMax
1. 访问 https://www.minimaxi.com/
2. 获取 API Key
3. 填入 `config.json` 的 `minimax_api_key`

## 故障排除

### 问题：无法连接 TikTok API
**解决**：检查 RapidAPI 配额是否充足，或等待系统自动切换备用 API

### 问题：MiniMax API 返回 429 错误
**解决**：配额已用完，请等待或升级套餐

### 问题：分析结果为空
**解决**：使用缓存数据或检查网络连接

## 开源协议

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 联系方式

- GitHub Issues: [项目地址]/issues
- Email: your-email@example.com

## 免责声明

本工具仅供学习和研究使用，不得用于商业目的或违反 TikTok 服务条款的行为。
