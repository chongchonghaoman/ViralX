# ViralX 使用指南

ViralX 是浏览器产品，不需要安装桌面客户端。生产网站、网页设置、本地 Flask 与 Codex Skill 使用同一套分析合同。

## 在线使用

1. 打开 [viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。
2. 在[网页设置](https://viralx.metrolabs.mobi/settings.html)中配置本次会话需要的凭据。
3. 选择并配置一个模型 API；关键词搜索时再填写 API23 Key。
4. 粘贴 TikTok / 抖音视频链接，或输入一个 TikTok 搜索主题，然后开始分析。
5. 在网页查看结果、整理复刻脚本，或导出 Markdown / Obsidian URI。

公开网站不会内置第三方 Key。会话级模型 / API23 Key 只写入当前标签页的 `sessionStorage`，关闭标签页后清除。LibTV 网页授权可由本地 Flask 直接使用，也可由 EdgeOne 页面通过 loopback-only ViralX Connector 使用。

## API 依赖边界

| 输入方式 | 调用链 | 必要凭据 |
| --- | --- | --- |
| 网页 TikTok / 抖音视频链接 | 本机 Connector → TK Note → 官方 LibTV CLI → 画布 | Connector + 本机 LibTV 网页登录 |
| 网页 TikTok 搜索主题 | API23 → 本机 Connector → TK Note → LibTV CLI | `RAPIDAPI_KEY` + Connector + 本机 LibTV 网页登录 |
| 视频链接 + 模型 API | TK Note → 已选模型服务商 | `MODEL_API_KEY` |

RapidAPI 只承载 API23 关键词发现，不解析已知视频链接。LibTV 不再使用 Access Key；EdgeOne 云函数不能读取电脑上的 CLI 登录态，但生产网页可以在用户授权后直连 `127.0.0.1` Connector。MiniMax 不属于默认链路。

## 从生产网页连接本机 LibTV

在仓库目录安装依赖后，双击 `start-connector.cmd` 或执行：

```bash
python connector.py
```

Connector 会打开 `https://viralx.metrolabs.mobi/settings.html` 并用 URL fragment 完成一次性配对。浏览器询问本地网络权限时选择允许，然后在设置页点击“连接 LibTV”。Connector 只开放受限的 `/connector/v1/*` 能力，不开放设置读取、清缓存或本地文件导出。

## 本地 Web 运行

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

浏览器打开 `http://localhost:5001`。使用 LibTV 前先安装[官方 CLI](https://www.liblib.tv/cli)，再进入 `/settings` 点击“连接 LibTV”。ViralX 会启动 `libtv login web`，并等待你在官方网页完成授权。

最小配置：

```json
{
  "analysis_mode": "libtv",
  "rapidapi_key": "YOUR_API23_RAPIDAPI_KEY"
}
```

如果只分析视频直链，可以不配置 `rapidapi_key`。LibTV token 由官方 CLI 保存，ViralX 不读取或写入凭据文件。

## 使用常用模型或自定义 API

在设置页把“默认分析模式”切换为“模型 API 分析”，再从以下服务商中选择一个：OpenAI、Claude、Gemini、DeepSeek、OpenRouter 或自定义 API。常用服务商会自动带入官方 Base URL 和建议模型名；模型名始终可以修改。

本地配置示例：

```json
{
  "analysis_mode": "model",
  "model_provider": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_name": "gpt-4.1-mini"
}
```

自定义 OpenAI-compatible 服务：

```json
{
  "analysis_mode": "model",
  "model_provider": "custom",
  "model_protocol": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_base_url": "http://127.0.0.1:11434/v1",
  "model_name": "your-model-id"
}
```

本地 Flask 可以连接 HTTP 和内网接口。EdgeOne 网页端只接受解析到公网地址的 HTTPS 自定义接口，以防云函数被用来访问内网资源。选择的模型调用失败时会返回该服务商的明确错误，不会转去消费另一个服务商的 Key。

## 在 Codex 中调用

把仓库链接发给另一台电脑上的 Codex，并要求安装 `.agents/skills/viralx`：

```text
请从这个 GitHub 仓库安装 .agents/skills/viralx，然后使用 $viralx 分析视频：
https://github.com/chongchonghaoman/ViralX
```

安装后可直接说：

```text
$viralx 分析这个 TikTok 视频：https://www.tiktok.com/@creator/video/123
$viralx 搜索 camping light，并分析点赞数高于 5000 的候选视频
```

完整 Skill 合同见 [`.agents/skills/viralx/SKILL.md`](.agents/skills/viralx/SKILL.md)。

## API 端点

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/health` | GET | 查看运行时与无密钥值的服务就绪状态 |
| `/api/keywords` | GET | 获取已有搜索主题 |
| `/api/analyze` | POST | NDJSON 流式分析关键词或视频链接 |
| `/api/export-obsidian` | POST | 生成 Obsidian URI 或 Markdown 下载 |
| `/api/generate_variants` | POST | 可选的旧版脚本变体扩展 |

本地 Flask 另外提供 `/api/settings`、`/api/cache/clear` 和 `/api/libtv/auth/*`；生产 EdgeOne 不公开这些本地管理接口。生产网页访问的是独立 loopback Connector 路由，不是把这些本地 API 代理到公网。

## 测试与构建

```bash
python -m unittest discover -s tests -v
npm run build:edgeone
```

部署边界见 [DEPLOYMENT.md](DEPLOYMENT.md)，设计与动效约束见 [DESIGN.md](DESIGN.md)。
