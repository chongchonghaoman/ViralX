---
name: viralx
description: Call the ViralX web API from Codex to search TikTok topics, collect video evidence, run shot analysis, and return reports. Use when the user asks to invoke ViralX or analyze a TikTok/Douyin video with ViralX; do not use for generic frontend work.
---

# ViralX

Use ViralX through its web API contract. The installed skill can probe the public site, but a complete analysis needs a local ViralX runtime because TK Note, source files, and the official LibTV CLI login live on the user's computer.

## Route the request

- For a TikTok or Douyin URL, call `analyze` directly. API23 is not involved.
- For a search topic, call `analyze` with the topic. This requires `RAPIDAPI_KEY` for API23 discovery.
- Every analysis follows one contract: API23 discovery when needed, TK Note collection, LibTV shot analysis, evidence merge, then the selected model API. There is no LibTV/model switch and no silent fallback.
- Before `analyze`, run ViralX locally, connect LibTV from `http://127.0.0.1:5001/settings`, set `VIRALX_BASE_URL=http://127.0.0.1:5001`, choose `MODEL_PROVIDER`, and provide `MODEL_API_KEY` plus `MODEL_NAME`. Custom providers also use `MODEL_BASE_URL` and `MODEL_PROTOCOL`.
- The hosted website's Connector is a browser-only session bridge and is not an Agent credential. Never send a LibTV token or Connector session to EdgeOne.
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
- A direct URL skips API23 but still needs TK Note, a completed LibTV CLI browser login, and the selected model API key.
- A keyword request needs those same dependencies plus `RAPIDAPI_KEY`.
- The EdgeOne endpoint deliberately refuses full analysis because it cannot access local evidence or CLI state. Do not claim the public interface alone completed an analysis.

Read [references/runtime.md](references/runtime.md) only for credential mapping, output contracts, installation, or troubleshooting.
