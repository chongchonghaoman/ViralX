# TikTok 爆款视频分析工具

## 快速开始

启动 Web 应用:
```bash
cd E:/tiktok_analyzer
python web_app.py
```

访问 http://localhost:5000

## 功能

- 搜索 TikTok 爆款视频（5000+ 点赞）
- AI 深度拆解（MiniMax M2.7）
- Web 可视化界面
- 导出到 Obsidian

## 配置

编辑 config.json:
- rapidapi_key: TikTok API 密钥
- minimax_api_key: MiniMax M2.7 密钥
- search_keywords: 搜索关键词
- output_dir: 数据输出目录

## 文件

- web_app.py: Flask 应用
- templates/index.html: 前端界面
- ai_analyzer.py: MiniMax 分析器
- tiktok_viral_analyzer.py: TikTok 搜索器
- full_analysis.py: 完整分析流程
- export_to_obsidian.py: Obsidian 导出
