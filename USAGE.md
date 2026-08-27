# ViralX 使用指南

ViralX 是浏览器产品，不需要安装桌面客户端。生产网站、网页设置、本地 Flask 与 Codex Skill 使用同一套分析合同。

## 在线使用

1. 打开 [viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。
2. 在[网页设置](https://viralx.metrolabs.mobi/settings.html)中配置本次会话需要的凭据。
3. 启动本机 Connector，选择镜头证据策略并配置最终模型；默认优先使用 ShotLoom Core，只有需要备用时才连接 LibTV。关键词搜索再填写 TikTok Scraper7 Key。
4. 粘贴 TikTok / 抖音视频链接，或输入一个 TikTok 搜索主题，然后启动固定串联分析。
5. 在网页查看结果、整理复刻脚本，或导出 Markdown / Obsidian URI。

公开网站不会内置第三方 Key。会话级模型 / TikTok Scraper7 Key 只写入当前标签页的 `sessionStorage`，关闭标签页后清除。LibTV 网页授权可由本地 Flask 直接使用，也可由 EdgeOne 页面通过 loopback-only ViralX Connector 使用。

## API 依赖边界

| 输入方式 | 调用链 | 必要凭据 |
| --- | --- | --- |
| 网页 TikTok / 抖音视频链接 | Connector → TK Note → ShotLoom / LibTV → 证据合并 → 最终模型 | Connector + 镜头引擎 + `MODEL_API_KEY` |
| 网页 TikTok 搜索主题 | TikTok Scraper7 → Connector → TK Note → ShotLoom / LibTV → 证据合并 → 最终模型 | 上述配置 + `RAPIDAPI_KEY` |
| 只采集 | Connector → TK Note → 保存部分证据 | Connector；不需要镜头或最终模型 API |

RapidAPI 只承载 TikTok Scraper7 关键词发现，不解析已知视频链接。TK Note 负责真实原片与平台证据，ShotLoom Core 默认负责带镜头 ID 的视觉事实，LibTV 是自动回退或显式选择项。最终模型只在证据质量检查通过后运行，并且不会收到原视频文件。LibTV 不使用 Access Key；EdgeOne 云函数不能读取电脑上的文件或 CLI 登录态，但生产网页可以在用户授权后直连 `127.0.0.1` Connector。

## 从生产网页连接本机分析运行时

在仓库目录安装依赖后，双击 `start-connector.cmd` 或执行：

```bash
python connector.py
```

Connector 会打开 `https://viralx.metrolabs.mobi/settings.html` 并用 URL fragment 完成一次性配对。浏览器询问本地网络权限时选择允许，然后保留默认自动策略或选择其他镜头引擎。只有自动回退或 LibTV 模式需要点击“连接 LibTV”。Connector 只开放受限的 `/connector/v1/*` 能力，不开放设置读取、清缓存或本地文件导出。模型 Key 只从当前标签页发送到已配对的 Connector，再直连所选服务商，不经过 EdgeOne。

Connector `1.2.0+` 支持单实例自动接管：再次执行 `python connector.py` 或双击 `start-connector.cmd`，新进程会确认旧进程是 ViralX Connector，请求它优雅退出，等待 `127.0.0.1:57231` 释放后再启动并打开新的配对页。其他程序占用端口时不会被结束。

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

浏览器打开 `http://localhost:5001`。`requirements.txt` 已包含 ShotLoom Core 所需的 PySceneDetect 与 OpenCV。使用 LibTV 备用时再安装[官方 CLI](https://www.liblib.tv/cli)，进入 `/settings` 完成网页授权。

最小配置：

```json
{
  "analysis_mode": "pipeline",
  "shot_engine": "auto",
  "shot_model_source": "inherit",
  "model_provider": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_name": "gpt-4.1-mini",
  "rapidapi_key": "YOUR_SCRAPER7_RAPIDAPI_KEY_FOR_SEARCH"
}
```

如果只分析视频直链，可以不配置 `rapidapi_key`。选择 `skip` 可以只保存 TK Note 证据，不会生成最终报告。LibTV token 由官方 CLI 保存，ViralX 不读取或写入凭据文件。

## 配置最终分析模型

ViralX 不再提供“模型模式”。最终模型是固定流水线的最后一步：它只接收平台、TK Note 与镜头证据的合并文本。设置页可选择 OpenAI、Claude、Gemini、DeepSeek、OpenRouter 或自定义 API；镜头视觉模型单独配置，可复用兼容的最终视觉模型，也可使用 Qwen VL 或自定义 OpenAI-compatible 接口。

本地配置示例：

```json
{
  "analysis_mode": "pipeline",
  "model_provider": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_name": "gpt-4.1-mini"
}
```

自定义 OpenAI-compatible 服务：

```json
{
  "analysis_mode": "pipeline",
  "model_provider": "custom",
  "model_protocol": "openai",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_base_url": "http://127.0.0.1:11434/v1",
  "model_name": "your-model-id"
}
```

本地 Flask 可以连接 HTTP 和内网接口。生产网页通过本机 Connector 执行完整链路；自定义模型地址仍由 Connector 按本地运行边界访问。选择的模型调用失败时会返回该服务商的明确错误，不会转去消费另一个服务商的 Key。

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
