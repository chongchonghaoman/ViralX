# ViralX Agent runtime

## What this mode pays for

ViralX Agent does not make a billable model API call. Its visual reasoning and final synthesis run in the model already active in Codex. The active Codex session and local machine do the work; no separate OpenAI API account or balance is required by this skill. Normal Codex plan availability and usage limits still apply.

This does not make TikTok acquisition magically offline. A TikTok URL still requires normal network access, and TikTok may require browser cookies or a proxy. A local MP4 can be analyzed without TikTok network access.

## Install from GitHub

Install the agent skill and its TK Note acquisition dependency together:

```powershell
python "$env:USERPROFILE\.codex\skills\.system\skill-installer\scripts\install-skill-from-github.py" `
  --repo chongchonghaoman/ViralX `
  --path .agents/skills/viralx-agent .agents/skills/tk-note
```

Restart Codex after installation so `$viralx-agent` is discovered.

## Local requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on `PATH`
- TK Note dependencies for TikTok URLs: `yt-dlp` and `curl-cffi`
- Optional local ASR: the TK Note Qwen3-ASR or Whisper environment
- Optional browser cookies/proxy when TikTok blocks anonymous retrieval

The preparation CLI locates TK Note in this order:

1. `VIRALX_TK_NOTE_SCRIPT`
2. the sibling repo skill `.agents/skills/tk-note`
3. `$CODEX_HOME/skills/tk-note`
4. `%USERPROFILE%/.codex/skills/tk-note`

## Capability boundary

| Input | Separate model API | Discovery provider | Local acquisition |
| --- | --- | --- | --- |
| Local MP4 | No | No | File already present |
| Direct TikTok URL | No | No | TK Note / yt-dlp |
| Topic keyword | No for analysis | Usually yes, unless the agent can find public candidates another way | TK Note after candidate selection |

The existing `$viralx` skill remains the Web API client. Use `$viralx-agent` when the current Codex model should perform the analysis directly.

## Troubleshooting

- `TK Note extractor not found`: install both skill paths or set `VIRALX_TK_NOTE_SCRIPT` to `extract_tiktok_text.py`.
- `ffmpeg/ffprobe was not found`: install FFmpeg and open a new terminal/Codex task.
- TikTok login wall: retry with `--cookies-from-browser chrome` (or the browser the user actually uses).
- Empty transcript: retry with local ASR enabled, or continue with a visibly scoped report that makes no audio claims.
- Too many frames: lower `--max-frames`; the manifest will mark reduced coverage.
