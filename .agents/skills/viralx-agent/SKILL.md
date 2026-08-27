---
name: viralx-agent
description: Analyze a TikTok URL or local short video inside Codex with TK Note evidence, timestamped local frames, and the active agent model. Use when the user wants ViralX analysis without buying or configuring a separate model API. Do not use for ViralX website/API configuration, keyword-only discovery, or generic video editing.
---

# ViralX Agent

Run ViralX as an agent-native evidence workflow. Local scripts acquire and prepare evidence; the model already active in Codex inspects the prepared images and writes the final analysis. Do not call OpenAI, Qwen, Gemini, DeepSeek, OpenRouter, LibTV, or another model API from this skill.

## Non-negotiable boundary

- The active Codex model is the reasoning layer. There is no `OPENAI_API_KEY`, `MODEL_API_KEY`, or `SHOT_MODEL_API_KEY` requirement.
- TK Note is the acquisition layer: original video, safe metadata, subtitles or local ASR, and optional comments.
- The preparation script uses local `ffmpeg`/`ffprobe` only. It never sends frames to a remote model endpoint.
- A model with image understanding is required because Codex must inspect timestamped JPEG frames. Do not claim that the script or model natively watched a video stream.
- A direct TikTok URL or local MP4 needs no discovery API. Keyword discovery is a separate capability and may still require web search or a configured TikTok discovery provider.

## Workflow

1. Resolve the installed skill directory. Keep all generated evidence in a user-visible output directory, never inside the skill directory.
2. Prepare evidence:

   ```powershell
   python scripts/prepare_agent_evidence.py "TIKTOK_URL_OR_LOCAL_MP4" --out-dir "OUTPUT_DIR"
   ```

   Add `--cookies-from-browser chrome` or `--proxy URL` only when TK Note is blocked. Use `--asr-backend none` only when the user accepts analysis without spoken-word evidence.
3. Parse the single JSON object printed to stdout. Open `brief`, `manifest`, `metadata`, `transcript`, `segments`, and `asset_manifest` when present.
4. Inspect **every file** listed in `manifest.frames` in chronological order with the agent's local image-viewing capability. Do not infer unseen actions between sampled frames.
5. Write `report.md` beside the manifest. Follow [references/report-contract.md](references/report-contract.md) and cite every factual claim with the evidence labels below.
6. Validate the report, correct all errors, and rerun until `valid` is `true`:

   ```powershell
   python scripts/validate_agent_report.py --manifest "PATH_TO_MANIFEST" --report "PATH_TO_REPORT"
   ```

7. Return the report plus a concise evidence-coverage note. State any acquisition, transcript, comments, or frame-coverage limitation.

## Evidence labels

- Metadata: `[META:title]`, `[META:metrics]`, `[META:creator]`, `[META:source]`
- Spoken words/subtitles: `[TK:transcript]`
- Visual fact: use the exact label from the manifest, for example `[FRAME:F007@00:12.400]`
- Collected comments: `[COMMENTS:sample]`
- Missing comments: `[COMMENTS:unavailable]` and explicitly say that comment evidence was not collected

Never cite a frame that was not inspected. Never use a visual frame to prove music, speech, sound effects, sentiment, metrics, or comments. Label interpretation, causal explanation, and recommendations as inference rather than fact.

## Failure behavior

- If TK Note cannot download a URL, stop and report the exact safe error. Do not substitute another post.
- If a local file is unreadable or `ffmpeg`/`ffprobe` is missing, stop before analysis.
- If transcript collection is partial, analyze visible structure only and disclose that audio claims are unavailable.
- If the report validator fails, do not present the report as completed.
- If the user supplied only a keyword, first obtain explicit, openable candidate URLs. Never invent a TikTok URL or analyze a semantically adjacent video as if it matched.

Read [references/runtime.md](references/runtime.md) only for installation, portability, or troubleshooting details.
