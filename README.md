# ViralX

AI驱动的TikTok美区爆款视频分析工具

## 核心功能

### AI 多模态分析
- **Gemini 2.5 Flash** - 视频帧多模态理解，提取视觉元素、场景、人物
- **MiniMax M2.7** - 纯文本深度分析，脚本拆解、爆款元素识别、文案结构

### 视频分析
- 视频链接一键下载（yt-dlp）
- 爆款视频搜索（RapidAPI TikTok数据）
- 评论抓取与情感分析

### 脚本生成
- 爆款脚本结构拆解
- 裂变变体脚本生成（多角度改编）

### 数据导出
- 导出至 Obsidian 知识库
- Markdown 格式保存分析结果

## 项目结构

```
ViralX/
├── ai_analyzer.py          # AI分析引擎（MiniMax + Gemini）
├── tiktok_viral_analyzer.py # TikTok数据获取
├── export_to_obsidian.py   # Obsidian导出
├── web_app.py              # Web界面
├── main.js                 # Electron桌面应用
├── requirements.txt        # Python依赖
└── package.json            # Node.js依赖
```

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
npm install
```

### 配置API密钥

在代码中配置以下环境变量：
- `MINIMAX_API_KEY` - MiniMax API
- `GEMINI_API_KEY` - Gemini API
- `RAPIDAPI_KEY` - RapidAPI TikTok Key（可选）

### 运行

**Web界面：**
```bash
python web_app.py
```

**桌面应用：**
```bash
npm start
```

**命令行分析：**
```bash
python ai_analyzer.py --url "视频链接"
```

## 技术栈

- **AI**: MiniMax M2.7, Google Gemini 2.5 Flash
- **后端**: Python Flask
- **前端**: HTML/CSS/JavaScript
- **桌面**: Electron
- **数据**: RapidAPI TikTok

## License

MIT
