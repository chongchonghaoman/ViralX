# ViralX — AI 短视频爆款分析器

![ViralX Logo](logo.png)

> 使用 AI 深度拆解 TikTok/抖音爆款视频，提取流量密码、爆款元素和可复用的短视频创作公式。

[![GitHub stars](https://img.shields.io/github/stars/chongchonghaoman/tiktok_analyzer?style=flat-square)](https://github.com/chongchonghaoman/ViralX)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg?style=flat-square)](https://www.python.org/)

---

## 🎯 项目简介

**ViralX** 是一款面向短视频创作者、跨境电商运营者和内容策划者的 AI 分析工具。

通过输入关键词，自动抓取 TikTok/抖音平台上该关键词下的**高热度视频**，并借助大模型从**钩子设计、卖点提炼、视听语言、流量密码、翻拍脚本**等多个维度进行深度拆解，输出结构化的爆款内容分析报告。

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🔍 **爆款视频搜索** | 抓取指定关键词下高点赞（可配置门槛）视频数据 |
| 🤖 **AI 深度拆解** | 6 大维度专业拆解：Hook、卖点、视听语言、流量密码、翻拍脚本、风险提示 |
| 📄 **Markdown 导出** | 分析结果可一键复制为 Markdown 格式，存入 Obsidian 等笔记工具 |
| 💾 **智能缓存** | 已分析关键词自动缓存，支持秒级加载 + 强制刷新 |
| 🔀 **API 自动容灾** | RapidAPI 配额耗尽时自动切换备用数据源 |
| 🎨 **Linear 风格 UI** | 深色主题，极简交互，移动端友好 |

---

## 📸 效果预览

```
┌──────────────────────────────────────────────┐
│  🔍 ViralX 短视频爆款分析器              [刷新]│
├──────────────────────────────────────────────┤
│  关键词: [outdoor lighting lamp    ] [搜索]    │
│                                              │
│  📦 已缓存关键词                              │
│  ┌────────────────────────────────────────┐ │
│  │ 🏷️  outdoor lighting lamp   12个视频  │ │
│  │ 🏷️  camping light            8个视频  │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ▶ 点击任意视频标题 → AI 深度拆解             │
└──────────────────────────────────────────────┘
```

---

## 🚀 快速开始

### 环境要求

- **Python 3.8+**
- **Windows / macOS / Linux**

### 1. 克隆项目

```bash
git clone https://github.com/chongchonghaoman/ViralX.git
cd ViralX
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

复制配置文件模板：

```bash
cp config.json.example config.json
```

编辑 `config.json`，填入你的 API Key：

```json
{
  "rapidapi_key": "YOUR_RAPIDAPI_KEY",
  "minimax_api_key": "YOUR_MINIMAX_API_KEY",
  "search_keywords": ["outdoor lighting lamp", "camping light"],
  "min_likes": 5000,
  "output_dir": "./data"
}
```

**API Key 获取：**

| 服务 | 获取地址 | 说明 |
|------|---------|------|
| **RapidAPI** (TikTok Scraper) | [tiktok-scraper7](https://rapidapi.com/DataFanatic/api/tiktok-scraper7) | 主要数据来源，支持关键词搜索、视频详情 |
| **MiniMax** | [minimaxi.com](https://www.minimaxi.com/) | AI 分析引擎，支持 Claude 格式调用 |

> ⚠️ **MiniMax API Key 格式**：需要使用兼容 Anthropic API 的 Key（sk-cp- 开头），参考 [MiniMax API 文档](https://www.minimaxi.com/docs)。

### 4. 启动应用

```bash
python web_app.py
```

打开浏览器访问：**http://localhost:5000**

---

## 📖 使用指南

### 搜索并分析视频

1. 在搜索框输入关键词（如 `outdoor lighting lamp`）
2. 点击 **「搜索」** 按钮
3. 系统自动抓取爆款视频列表
4. 点击任意视频的 **「查看 AI 拆解」** 按钮
5. 在弹窗中查看完整的 6 维度分析报告
6. 点击 **「复制 Markdown」** 一键复制到剪贴板

### 关键词管理

- 搜索过的关键词自动保存到缓存
- 点击关键词标签可快速重新加载已有数据
- 点击 **「刷新」** 按钮强制拉取最新数据

### 导出到 Obsidian

运行 `export_to_obsidian.py`，将分析结果批量导入 Obsidian 笔记库：

```bash
python export_to_obsidian.py
```

---

## 🗂️ 项目结构

```
ViralX/
├── web_app.py                 # Flask Web 服务（主入口）
├── ai_analyzer.py             # MiniMax AI 分析器
├── tiktok_viral_analyzer.py   # TikTok 数据抓取器
├── export_to_obsidian.py      # Obsidian 批量导出脚本
├── full_analysis.py           # 命令行全量分析工具
├── report_generator.py        # 报告生成模块
├── config.json.example        # 配置模板
├── requirements.txt           # Python 依赖
├── logo.png                   # ViralX Logo
│
├── templates/
│   └── index.html             # 前端页面（Linear 风格深色 UI）
│
└── data/                      # 分析结果缓存目录
    └── {keyword}_viral.json   # 关键词缓存文件
```

---

## 🔌 API 接口

### 搜索视频

```
POST /api/analyze
Content-Type: application/json

{
  "keyword": "outdoor lighting lamp",
  "refresh": false          // true = 强制刷新，false = 优先读缓存
}
```

**响应：**

```json
{
  "status": "success",
  "total_videos": 10,
  "source": "cache",        // "cache" 或 "api"
  "videos": [
    {
      "id": "7234567890123456789",
      "title": "Amazing camping light 🔥",
      "author": "gear_review",
      "likes": 54200,
      "comments": 1203,
      "shares": 890,
      "views": 890000,
      "cover": "https://...",
      "url": "https://www.tiktok.com/@user/video/7234567890123456789"
    }
  ]
}
```

### 获取已缓存关键词

```
GET /api/keywords
```

---

## 🤖 AI 分析维度

每个视频的 AI 拆解包含以下 6 个维度：

| 维度 | 内容 |
|------|------|
| **🎬 黄金3秒 Hook** | 视频开头设计分析，包含视觉钩子 + 听觉钩子 |
| **💡 核心卖点** | 5 个主要卖点 + 对应视觉呈现方式 |
| **🎞️ 视听语言** | 节奏分析、运镜手法，光影运用 |
| **🔥 流量密码** | 互动钩子设计、评论区埋梗、转化锚点 |
| **📋 翻拍脚本** | 6 个标准镜头的完整分镜表（可照着拍） |
| **⚠️ 风险提示** | 合规建议，音乐版权注意点、复刻风险评估 |

---

## 🛠️ 扩展开发

### 添加新的数据源

编辑 `tiktok_viral_analyzer.py`，在 `_search_with_backup_api` 方法中添加新的 API 调用逻辑。

### 添加新的分析维度

编辑 `ai_analyzer.py` 中的 `analyze_video_script` 方法，修改 Prompt 模板即可新增分析维度。

### 部署到生产环境

```bash
# 使用 Gunicorn（推荐）
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 web_app:app
```

---

## ⚙️ 配置参考

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `rapidapi_key` | - | RapidAPI TikTok Scraper Key（必填） |
| `minimax_api_key` | - | MiniMax API Key（必填） |
| `search_keywords` | `[]` | 启动时预加载的关键词列表 |
| `min_likes` | `5000` | 最低点赞门槛（数值越高数据越爆） |
| `output_dir` | `./data` | 缓存文件存放目录 |
| `api_base_url` | 自动 | RapidAPI 请求地址（通常不需要改） |

---

## 🐛 故障排除

| 问题 | 解决方案 |
|------|---------|
| RapidAPI 返回 429 | 配额耗尽，等待或升级套餐；系统会自动尝试备用 API |
| MiniMax 返回 403/401 | 检查 API Key 是否正确，是否已激活 |
| 分析结果为空 | 检查网络连接，确认 API Key 有余额 |
| 视频数量为 0 | 关键词过于冷门，尝试更通用的词 |

---

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源，允许自由使用、修改和分发，但请勿用于任何违反 TikTok 服务条款的场景。

---

## 🙏 致谢

- [MiniMax](https://www.minimaxi.com/) — AI 分析能力支持
- [RapidAPI - TikTok Scraper](https://rapidapi.com/DataFanatic/api/tiktok-scraper7) — 数据爬取支持
- [Flask](https://flask.palletsprojects.com/) — Web 框架
- [Anthropic Claude](https://www.anthropic.com/) — LLM 接口兼容

---

*如果你觉得这个项目有帮助，欢迎 ⭐ Star！*
