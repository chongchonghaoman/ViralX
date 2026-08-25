---
name: viralx
description: Call the ViralX web API from Codex to search TikTok topics, collect video evidence, run shot analysis, and return reports. Use when the user asks to invoke ViralX or analyze a TikTok/Douyin video with ViralX; do not use for generic frontend work.
---

# ViralX

Use ViralX as a remote web capability. The installed skill does not need the full ViralX repository and defaults to `https://viralx.metrolabs.mobi`.

## Route the request

- For a TikTok or Douyin URL, call `analyze` directly. API23 is not involved.
- For a search topic, call `analyze` with the topic. This requires `RAPIDAPI_KEY` for API23 discovery; the discovered video then continues to the active analysis provider.
- The default provider is LibTV and requires `LIBTV_ACCESS_KEY`. For model analysis, set `ANALYSIS_MODE=model`, choose `MODEL_PROVIDER` (`openai`, `anthropic`, `gemini`, `deepseek`, `openrouter`, or `custom`), and provide `MODEL_API_KEY` plus `MODEL_NAME`. Custom providers also use `MODEL_BASE_URL` and `MODEL_PROTOCOL`.
- Use `health` before analysis when credential or service readiness is unknown.
- Use `keywords` only when the user asks for existing or suggested topics.

## Run the bundled client

Resolve paths relative to this `SKILL.md`, then run the script with Python 3:

```bash
python scripts/viralx.py health
python scripts/viralx.py keywords
python scripts/viralx.py analyze "https://www.tiktok.com/@creator/video/123"
python scripts/viralx.py analyze "camping light" --min-likes 5000
```

The `analyze` command writes ViralX NDJSON events to stdout. Preserve the evidence fields and report content when summarizing the result. If ViralX returns an error, report that error and its recovery action; never invent an analysis.

Use `--output <path>` only when the user asks to save the NDJSON stream. Set `VIRALX_BASE_URL=http://127.0.0.1:5001` to call a local ViralX web server instead of production.

## Credentials and safety

- Read credentials from environment variables only. Never request that a user paste a key into chat when they can set it locally.
- Never pass secrets as CLI arguments, print request headers, or write credentials to output files.
- A direct URL skips API23, but the downstream analysis provider can still require its own key.
- A keyword request normally needs both `RAPIDAPI_KEY` and the active analysis provider's key.
- The production runtime is limited to one video per request and temporary edge storage. Do not claim persistent local caches, browser cookies, arbitrary proxies, or direct filesystem Obsidian writes.

Read [references/runtime.md](references/runtime.md) only for credential mapping, output contracts, installation, or troubleshooting.
