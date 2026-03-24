# 使用指南

## 启动应用

```bash
cd E:/tiktok_analyzer
python web_app.py
```

然后在浏览器打开: http://localhost:5000

## 功能说明

### 首页
- 显示搜索框和已缓存的关键词
- 点击关键词快速加载分析结果

### 分析结果
- 显示视频卡片（标题、作者、互动数据）
- 显示 AI 深度拆解结果
- 数据源标签（缓存/实时）

## 数据来源

### 缓存数据
已有 3 个关键词的分析结果:
- outdoor lighting lamp (5 个视频)
- camping light (5 个视频)  
- portable LED light (5 个视频)

位置: `E:/tiktok_analyzer/data/`

### 实时分析
输入新关键词时，系统会:
1. 从 TikTok 搜索视频
2. 使用 MiniMax M2.7 进行 AI 分析
3. 返回结果

## API 端点

### GET /
返回 HTML 前端

### GET /api/keywords
获取已缓存的关键词列表

### POST /api/analyze
分析指定关键词
```json
{"keyword": "outdoor lighting lamp"}
```

## 导出到 Obsidian

运行:
```bash
python export_to_obsidian.py
```

结果保存到: `E:/我的知识库/07-对话记录/`

## 完整分析流程

运行:
```bash
python full_analysis.py
```

会自动:
1. 搜索所有配置的关键词
2. 执行 AI 分析
3. 导出 Markdown
