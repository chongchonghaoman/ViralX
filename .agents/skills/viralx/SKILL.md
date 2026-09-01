---
name: viralx
description: Call the ViralX web API from Codex to search TikTok topics, collect video evidence, run shot analysis, and return reports. Use when the user asks to invoke ViralX or analyze a TikTok/Douyin video with ViralX; do not use for generic frontend work.
---

# ViralX

Use ViralX through its web API contract. The installed skill can probe the public site, but a complete analysis needs a local ViralX runtime because TK Note, source files, ShotLoom Core and any optional LibTV CLI login live on the user's computer.

## Route the request

- For a TikTok or Douyin URL, call `analyze` directly. RapidAPI discovery is not involved.
- For a search topic, call `analyze` with the topic. This requires one `RAPIDAPI_KEY`: ViralX automatically switches across subscribed search sources, merges results and deduplicates verified post IDs until the requested target is met.
- Every analysis follows one contract: provider-neutral multi-source discovery, TK Note collection, provider-neutral shot evidence, evidence merge, then the selected final model API. The recommended shot strategy is `shotloom`; LibTV is only an auditable fallback when explicitly enabled.
- Before `analyze`, run ViralX locally, set `VIRALX_BASE_URL=http://127.0.0.1:5001`, choose `VIRALX_SHOT_ENGINE`, configure a compatible shot vision model, then provide `MODEL_PROVIDER`, `MODEL_API_KEY`, and `MODEL_NAME`. Connect LibTV from `/settings` only when `libtv` is selected or wanted as an `auto` fallback.
- The hosted website may call an owner-operated ViralX Worker, but an Agent should use the configured Web API or run ViralX locally. Never send a LibTV token or local-management credential to a hosted endpoint.
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

The `analyze` command writes ViralX NDJSON events to stdout. Preserve `shot_provider`, `shot_status`, `shot_evidence_quality`, `shot_block_reason`, `fallback_chain`, evidence fields, and report content when summarizing. Treat `blocked` as a failed analysis even when TK Note collection succeeded; never invent a report.

Use `--output <path>` only when the user asks to save the NDJSON stream. Set `VIRALX_BASE_URL=http://127.0.0.1:5001` to call a local ViralX web server instead of production.

## Credentials and safety

- Read credentials from environment variables only. Never request that a user paste a key into chat when they can set it locally.
- Never pass secrets as CLI arguments, print request headers, or write credentials to output files.
- A direct URL skips RapidAPI discovery but still needs TK Note, a ready shot-evidence strategy, and the selected final model API key. LibTV login is not mandatory when ShotLoom Core is ready.
- A keyword request needs those same dependencies plus `RAPIDAPI_KEY`.
- The EdgeOne endpoint deliberately refuses full analysis because it cannot access local evidence or CLI state. Do not claim the public interface alone completed an analysis.

Read [references/runtime.md](references/runtime.md) only for credential mapping, output contracts, installation, or troubleshooting.
