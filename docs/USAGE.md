# ViralX 使用指南

文档中的命令均从仓库根目录运行。产品概览见 [README](../README.md)。

ViralX 是浏览器产品，不需要安装桌面客户端。生产网站、网页设置、本地 Flask 与 Codex Skill 使用同一套分析合同。

## 在线使用

1. 打开你使用的 ViralX 站点。
2. 首页会自动显示 ViralX 实时分析服务在线、配置中或离线；访客不需要安装任何 Connector。
3. 服务在线且配置完整时，粘贴 TikTok / 抖音视频链接，或输入一个 TikTok 搜索主题，然后启动固定串联分析。
4. 只有需要临时覆盖站点默认搜索或视觉模型配置时，才进入网页设置填写会话级配置。
5. 在网页查看报告与复刻脚本，切换到 Markdown 源码并一键复制。

公开网站不会把站点所有者的第三方 Key 写入前端。默认 Key 由 ViralX Worker 保存在服务器环境；会话级模型 / RapidAPI 搜索覆盖值只写入当前标签页的 `sessionStorage`，关闭标签页后清除。LibTV 网页授权只由 Worker 所有者在运行服务的电脑上管理。长分析由 Worker 在后台继续执行，网页通过同源短轮询读取进度，避免浏览器私网限制与单次网关超时把仍在运行的任务误报为失败。

## API 依赖边界

| 输入方式 | 调用链 | 必要凭据 |
| --- | --- | --- |
| 网页 TikTok / 抖音视频链接 | ViralX Worker → TK Note → 视觉模型读取完整原片 → 证据校验 → 同模型终审 | Worker + TK Note + 支持视频输入的视觉模型 API |
| 网页 TikTok 搜索主题 | 多源搜索自动切换、合并、去重 → ViralX Worker → TK Note → 视觉模型读取完整原片 → 证据校验 → 同模型终审 | 上述配置 + 一把共用的 `RAPIDAPI_KEY` |
| 只采集 | ViralX Worker → TK Note → 保存部分证据 | Worker；不需要镜头或最终模型 API |

RapidAPI 只承载 TikTok 关键词发现：ViralX 按质量顺序尝试已订阅的搜索源，自动换源、补足并按真实帖子 ID 去重；所有来源使用同一个 Key 配置位。它们不解析已知视频链接。TK Note 固定负责真实原片与平台证据；上方视觉模型直接读取完整原片并完成证据终审。ShotLoom 仅在专业模式中增加镜头边界与关键帧索引，LibTV 只在显式回退或显式选择时调用。

## 运行公开 ViralX Worker

在运行分析服务的电脑上安装依赖，复制本地配置，然后双击 `start-worker.cmd`：

```powershell
python -m pip install -r requirements.txt
Copy-Item config.json.example config.json
.\start-worker.cmd
```

Worker 默认只监听 `127.0.0.1:8000`，应通过受信任的 HTTPS 隧道对外提供服务，不能直接开放家庭路由器端口。前端构建时通过 `VIRALX_PUBLIC_API_BASE_URL` 写入公开 Worker 地址；该值只能是无账号信息的 HTTPS 根地址。

公开 Worker 只挂载健康检查、关键词、分析、后台任务进度、终审续跑和脚本变体所需的受限 API。它按 Origin 白名单限制访问，默认一次只运行一个分析任务、每个来源每小时最多六次，并在新任务启动时清理超过 24 小时的证据缓存。浏览器不能控制服务器 Cookie、代理、LibTV 账号、文件目录或镜头引擎。

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
  "shot_engine": "direct",
  "shot_model_source": "inherit",
  "model_provider": "qwen",
  "model_api_key": "YOUR_MODEL_API_KEY",
  "model_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "model_name": "qwen3-vl-flash",
  "rapidapi_key": "YOUR_SHARED_RAPIDAPI_KEY_FOR_SEARCH"
}
```

如果只分析视频直链，可以不配置 `rapidapi_key`。选择 `skip` 可以只保存 TK Note 证据，不会生成最终报告。LibTV token 由官方 CLI 保存，ViralX 不读取或写入凭据文件。

## 配置最终分析模型

ViralX 不再要求普通用户分别配置“镜头模型”和“最终模型”。设置页上方的一套 Base URL、API Key 与模型 ID 直接读取 TK Note 保存的完整原片，并基于平台、字幕与原片时间证据完成终审。推荐 Qwen3-VL Flash；其他服务也可以使用，但所选模型必须具备视频输入能力。只有需要稳定剪辑点索引的专家场景才开启 ShotLoom。

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

本地 Flask 可以连接 HTTP 和内网接口。公开 Worker 只接受解析到公网的标准 HTTPS 自定义模型地址，避免浏览器通过它访问服务器内网。选择的模型调用失败时会返回该服务商的明确错误，不会转去消费另一个服务商的 Key。

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

完整 Skill 合同见 [`.agents/skills/viralx/SKILL.md`](../.agents/skills/viralx/SKILL.md)；使用当前 Codex 模型的版本见 [`viralx-agent`](../.agents/skills/viralx-agent/SKILL.md)。

## API 端点

| 端点 | 方法 | 用途 |
| --- | --- | --- |
| `/api/health` | GET | 查看运行时与无密钥值的服务就绪状态 |
| `/api/keywords` | GET | 获取已有搜索主题 |
| `/api/analyze` | POST | NDJSON 流式分析关键词或视频链接 |
| `/api/export-obsidian` | POST | 生成 Obsidian URI 或 Markdown 下载 |
| `/api/generate_variants` | POST | 可选的旧版脚本变体扩展 |

本地 Flask 另外提供 `/api/settings`、`/api/cache/clear`、`/api/export-obsidian` 和 `/api/libtv/auth/*`；公开 Worker 不挂载这些本地管理接口。

## 测试与构建

```bash
python -m unittest discover -s tests -v
npm run build:edgeone
```

设计与动效约束见 [DESIGN.md](../DESIGN.md)。
