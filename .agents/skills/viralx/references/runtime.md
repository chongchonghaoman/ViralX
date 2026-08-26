# ViralX Skill Runtime

## Installation from GitHub

Codex's built-in `skill-installer` can install this directory directly:

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo chongchonghaoman/ViralX \
  --path .agents/skills/viralx
```

On Windows PowerShell, the default installer path is:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo chongchonghaoman/ViralX `
  --path .agents/skills/viralx
```

The skill becomes available to Codex on the next turn as `$viralx`.

## Environment variables

The client converts these environment variables to session-only `X-ViralX-*` request headers:

| Environment variable | Purpose |
| --- | --- |
| `VIRALX_BASE_URL` | Override the default `https://viralx.metrolabs.mobi` server |
| `RAPIDAPI_KEY` | TikTok Scraper7 keyword discovery; not used for direct URLs |
| `ANALYSIS_MODE` | Fixed value `pipeline`; legacy mode values are migrated |
| `MODEL_PROVIDER` | `openai`, `anthropic`, `gemini`, `deepseek`, `openrouter`, or `custom` |
| `MODEL_API_KEY`, `MODEL_NAME` | Key and model ID for the selected provider |
| `MODEL_BASE_URL`, `MODEL_PROTOCOL` | Custom endpoint root and `openai` / `anthropic` protocol |
| `GEMINI_*`, `OPENROUTER_*`, `MINIMAX_*` | Legacy compatibility; MiniMax remains available to script generation |
| `MIN_LIKES` | Default TikTok Scraper7 popularity threshold |
| `TK_NOTE_ASR_BACKEND`, `TK_NOTE_LANGUAGE`, `TK_NOTE_TIMEOUT` | TK Note collection controls |

The client never prints these values.

## Commands and contracts

### `health`

Calls `GET /api/health` and prints formatted JSON. `configured` values are booleans and never contain key values.

### `keywords`

Calls `GET /api/keywords` and prints formatted JSON.

### `analyze SOURCE`

Calls `POST /api/analyze` with:

```json
{
  "keyword": "SOURCE",
  "refresh": false,
  "product_name": "",
  "product_info": ""
}
```

The response is NDJSON. Each parsed event is emitted as one JSON line. Exit codes:

- `0`: the stream completed without an application error.
- `1`: network, HTTP, or invalid-response failure.
- `2`: ViralX returned an application-level error event.

The production EdgeOne runtime intentionally refuses full analysis because it cannot access a user's local source files or LibTV CLI credentials. Point `VIRALX_BASE_URL` at local Flask after the user connects LibTV from `/settings`; the local runtime then executes TK Note, LibTV shot analysis, evidence merge, and the selected model API.
