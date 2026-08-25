# ViralX 使用指南

ViralX 是浏览器产品，不需要安装桌面客户端。生产网站、网页设置、本地 Flask 与 Codex Skill 使用同一套分析合同。

## 在线使用

1. 打开 [viralx.metrolabs.mobi](https://viralx.metrolabs.mobi)。
2. 在[网页设置](https://viralx.metrolabs.mobi/settings.html)中配置本次会话需要的凭据。
3. 粘贴 TikTok / 抖音视频链接，或输入一个 TikTok 搜索主题。
4. 点击“开始拉片”，等待 TK Note 采集证据并由 LibTV 返回报告。
5. 在网页查看结果、整理复刻脚本，或导出 Markdown / Obsidian URI。

公开网站不会内置第三方 Key。会话级 Key 只写入当前标签页的 `sessionStorage`，关闭标签页后清除。

## API 依赖边界

| 输入方式 | 调用链 | 必要凭据 |
| --- | --- | --- |
| TikTok / 抖音视频链接 | TK Note → LibTV | `LIBTV_ACCESS_KEY` |
| TikTok 搜索主题 | API23 → TK Note → LibTV | `RAPIDAPI_KEY` + `LIBTV_ACCESS_KEY` |

RapidAPI 只承载 API23 关键词发现，不解析已知视频链接。MiniMax 不属于默认链路，仅在显式调用旧版 `/api/generate_variants` 扩展时可选使用。

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

浏览器打开 `http://localhost:5001`。默认分析模式是 `libtv`。

最小配置：

```json
{
  "analysis_mode": "libtv",
  "libtv_access_key": "YOUR_LIBTV_ACCESS_KEY",
  "rapidapi_key": "YOUR_API23_RAPIDAPI_KEY"
}
```

如果只分析视频直链，可以不配置 `rapidapi_key`。

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

本地 Flask 另外提供 `/api/settings` 和 `/api/cache/clear`；生产 EdgeOne 不公开这两个本地管理接口。

## 测试与构建

```bash
python -m unittest discover -s tests -v
npm run build:edgeone
```

部署边界见 [DEPLOYMENT.md](DEPLOYMENT.md)，设计与动效约束见 [DESIGN.md](DESIGN.md)。
