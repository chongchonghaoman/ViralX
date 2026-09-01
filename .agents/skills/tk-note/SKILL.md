---
name: tk-note
description: "TK Note: extract TikTok videos and raw evidence into reusable local assets before analysis. Use when the user provides tiktok.com, vt.tiktok.com, vm.tiktok.com, or TikTok share links and asks to download video, preserve metadata/subtitles, run local ASR, collect a bounded comment sample, analyze an account/topic/script/commerce video, archive evidence, or feed a local video into ViralX/LibTV. This skill is for international TikTok, not Douyin; use dy-note for douyin.com."
---

# TK Note

TK Note is the international-TikTok counterpart to DyNote. Preserve DyNote's reliable experience: raw assets first, notes later; inspect existing work before rerunning; use stable output names; make expensive steps resumable; and label partial evidence instead of inventing missing content.

TK Note reuses `%USERPROFILE%\.cache\rimagination-notes` for local ASR. OpenAI Whisper may share the existing `qwen3-asr-venv`; scripts discover it automatically even when TK Note is launched by another Python. Set `RIMAGINATION_WHISPER_PYTHON` only when an explicit interpreter override is needed.

The default single-video contract is:

```text
TikTok URL
  -> search-provider media hint (when available) / yt-dlp / isolated Chrome fallback
  -> video + safe metadata + available subtitle tracks
  -> local ASR only when no usable subtitle exists
  -> note budget + reusable assets/asset_manifest.json
  -> optional TikTokApi comment sample
  -> downstream analysis or ViralX/LibTV
```

## Platform boundary

- Accept international TikTok hosts: `tiktok.com`, `www.tiktok.com`, `m.tiktok.com`, `vt.tiktok.com`, and `vm.tiktok.com`.
- Do not route `douyin.com` or `v.douyin.com` here; use `dy-note`.
- Public video download first uses an in-memory media hint when keyword discovery supplied one, otherwise local `yt-dlp`; if TikTok serves a webpage challenge, TK Note opens an isolated local Chrome/Edge profile and reads the real player stream. A paid scraping API is not required for direct links.
- Browser fallback does not export Cookie or persist signed media URLs. The profile stays under the shared local cache and the browser debugging port binds to loopback for that process only.
- Comments use the optional MIT-licensed `TikTokApi` package. It may need an `ms_token`, Playwright, or a proxy, and TikTok can still block it. Comment failure must never block the downloaded video from continuing to LibTV.
- Never print, save, or return cookies, `ms_token`, proxy credentials, signed media URLs, or raw request headers.

## Reliability invariants inherited from DyNote

1. Inspect the output directory first. Reuse `source.mp4`, `metadata.json`, `transcript.txt`, `segments.json`, `note_budget.json`, comments, and `assets/asset_manifest.json` when valid.
2. Only `--force` may replace reusable extraction results.
3. Keep stable files: `source.mp4`, `page_metadata.json`, `metadata.json`, `transcript.cleaned.md`, `transcript.txt`, `segments.json`, `note_budget.json`, and `assets/asset_manifest.json`.
4. Send progress as JSON lines on stderr and one machine-readable result object on stdout.
5. Treat subtitles or ASR as the spoken-content factual spine. Post caption, hashtags, and metadata are not a transcript.
6. If transcript density is low, set `visual_dependency.needs_visual_review=true`. Do not claim complete understanding until LibTV, keyframes, OCR, or manual review supplies visual evidence.
7. Comment collection is bounded by default. Report visible row count, requested count, main/reply split, and whether the result is only a sample.
8. Save raw evidence before synthesis. A generated note is a view over assets, not the asset package itself.
9. Do not retry the same blocked browser/API action indefinitely. Preserve completed assets and return `partial` with the exact blocked stage.

## Mode routing

- `single-video-note`: one URL to video, metadata, transcript, budget, and evidence manifest.
- `comment-insight`: add a bounded comment sample; use `--full` only when the user explicitly needs more visible comments.
- `account-analysis`: sample videos by recency, engagement, and format diversity before deep extraction.
- `topic-research`: collect a bounded title/hashtag/account sample first; deep-process selected videos only.
- `script-mining`: use transcript for wording and LibTV/keyframes for shots, hooks, pacing, and on-screen text.
- `commerce-analysis`: preserve offer, price, proof, CTA, objections, and comment demand as separately sourced evidence.
- `fact-check`: extract exact claims before external verification; high-stakes claims require authoritative sources.
- `knowledge-archive`: preserve provenance, timestamps, safe metadata, transcript, comments, and manifest.

## Default workflow

1. Check the environment:

```powershell
$skill = "$env:USERPROFILE\.codex\skills\tk-note"
python "$skill\scripts\check_environment.py"
```

2. When an output directory already exists, inspect it before doing work:

```powershell
python "$skill\scripts\inspect_workflow_state.py" `
  --out-dir ".\tk_note_output" `
  --mode "single-video-note"
```

3. Extract a TikTok video. The command reuses valid artifacts by default:

```powershell
python "$skill\scripts\extract_tiktok_text.py" `
  "https://www.tiktok.com/@creator/video/1234567890" `
  --out-dir ".\tk_note_output" `
  --asr-backend auto `
  --language auto
```

Useful options:

- `--cookies-from-browser chrome`: use the user's authorized browser cookies without exporting them into TK Note outputs.
- `--proxy URL`: route yt-dlp through a user-provided proxy; credentials are redacted from errors.
- `--asr-backend none`: download and preserve subtitles/metadata without local ASR. ViralX may use this when the immediate next step is LibTV.
- `--force`: rerun extraction because source, output, or evidence requirements genuinely changed.
- `--refresh-derived`: keep the verified `source.mp4` and rebuild transcript/evidence outputs. ViralX's “refresh evidence” action uses this safer mode.

4. For comment insight, collect a bounded sample after the video assets exist:

```powershell
python "$skill\scripts\fetch_tiktok_comments.py" `
  "https://www.tiktok.com/@creator/video/1234567890" `
  --out-dir ".\tk_note_output" `
  --main-count 100
```

Use `--full` only when explicitly requested. TK Note reads `TIKTOK_MS_TOKEN` from the environment when present but never logs it.

5. Rebuild the evidence package after adding comments or other material:

```powershell
python "$skill\scripts\archive_tk_note_assets.py" --out-dir ".\tk_note_output"
```

6. Before writing a note, read `assets/asset_manifest.json` and `note_budget.json`. Separate:

- E0 user input and source URL;
- E1 safe page metadata;
- E2 independent subtitle track;
- E3 local ASR transcript;
- E4 visible comment sample;
- E5 LibTV canvas/keyframes/OCR visual evidence;
- E6 external sources.

## ViralX / LibTV handoff

ViralX should consume TK Note's result JSON, not scrape stdout text. The handoff file is `source.mp4`; the evidence sidecar is `assets/asset_manifest.json`.

```text
extract_tiktok_text.py
  -> result.video_file
  -> official `libtv` CLI (already connected through `libtv login web`)
  -> `libtv project create`
  -> `libtv upload --resource result.video_file --type video --project <uuid>`
  -> return the LibTV canvas URL for continued shot analysis
```

Do not read or copy the CLI credential file. ViralX only checks `libtv account info`, creates a canvas, and uploads the source video; the user continues shot analysis in the official LibTV web canvas.

## Output contract

Successful extraction prints one JSON object containing:

- `status`: `success`, `partial`, or `reused`;
- `video_file` and `video_size_bytes`;
- `metadata`, `transcript`, `segments`, `note_budget`, and `asset_manifest` paths;
- `subtitle_source` and `transcript_source`;
- `warnings` and `blocked_stages`;
- `reused_artifacts`.

`partial` is usable when the video exists but subtitles, ASR, or comments are blocked. ViralX may still upload that video to LibTV and must surface the missing evidence instead of calling the whole task a failure.

A forced redownload is transactional: the new candidate must pass video-stream validation before it replaces `source.mp4`. If TikTok blocks the refresh and an identity-matched source file already exists, TK Note keeps the previous evidence and records a stale-reuse warning.

## Evidence language

- Say “downloaded video” only when `source.mp4` exists and is non-empty.
- Say “subtitle” only for a real subtitle track; say “ASR transcript” for local speech recognition.
- Do not call a post caption a transcript.
- Do not claim all comments when the output is sampled or TikTok reports more comments than were collected.
- Do not claim visual/on-screen-text coverage from audio transcription. Use LibTV, keyframes, OCR, or manual review.
- TikTok anti-bot failures are an external-state limitation. Preserve completed local assets and return the blocked stage with a next action.

For current extractor limits and the free dependency audit, read [references/tiktok-data-routing.md](references/tiktok-data-routing.md) only when debugging or changing acquisition behavior.
