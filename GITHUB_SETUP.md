# ViralX GitHub 维护说明

公开仓库：[chongchonghaoman/ViralX](https://github.com/chongchonghaoman/ViralX)

## 仓库定位

- 产品形态：Web。
- 生产网站：[viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。
- 默认分支：`master`。
- `master` 与 `main` 当前发布同一套网站、API 和 Codex Skill。
- CI 会在两个发布分支的 push 和 pull request 上运行。

## 克隆与开发

```bash
git clone https://github.com/chongchonghaoman/ViralX.git
cd ViralX
python -m pip install -r requirements.txt
python web_app.py
```

本地页面运行在 `http://localhost:5001`。前端、云函数构建和测试命令以 [README.md](README.md) 为准。

## 提交更新

从默认分支创建功能分支：

```bash
git switch master
git pull --ff-only
git switch -c feat/your-change
```

提交前运行：

```bash
python -m unittest discover -s tests -v
npm run build:edgeone
```

然后推送功能分支并创建 Pull Request。不要通过重新上传文件或重建仓库来发布更新。

## 凭据与隐私

不要提交以下内容：

- `config.json`；
- RapidAPI、LibTV、MiniMax、Gemini 或 OpenRouter Key；
- TikTok 浏览器 Cookie、代理凭据；
- EdgeOne 部署 Token；
- ViralX Connector 的一次性配对 fragment 或浏览器会话 token；
- 下载的视频、字幕、转写、缓存和本地 Obsidian 路径。

公开示例只允许使用占位值。仓库 `.gitignore` 已覆盖标准本地路径，但提交前仍应检查 `git diff --cached`。

## 发布检查

1. 确认 README 描述当前 Web 产品，而不是历史桌面端或旧分析器。
2. 确认直链、关键词和可选模型的凭据边界写准确。
3. 确认 `.agents/skills/viralx` 可从公开仓库安装。
4. 确认 GitHub Actions 的 Python 测试与 EdgeOne 构建均通过。
5. 确认生产域名与 README 中的链接一致。
