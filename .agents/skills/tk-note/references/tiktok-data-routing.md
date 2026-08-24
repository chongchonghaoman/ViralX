# TikTok data routing

Read this reference only when changing or debugging TikTok acquisition.

## Free local stack

- `yt-dlp`: primary public-video download, metadata, and available subtitle tracks. Its TikTok extractor currently normalizes title/description, author, duration, view/like/share/comment counts, thumbnails, and subtitles when TikTok exposes them.
- `ffmpeg`: audio extraction and media normalization.
- `Qwen3-ASR` or Whisper: optional local transcript when no usable subtitle exists. Reuse `%USERPROFILE%\.cache\rimagination-notes`; do not create a second model cache.
- `TikTokApi`: optional comments and replies. It is unofficial, uses Playwright and TikTok web endpoints, may need `TIKTOK_MS_TOKEN` or a proxy, and may fail when TikTok detects automation.

None of these requires a paid scraping API. A paid proxy may still be needed in some networks; that is an optional operating cost, not a TK Note dependency.

## Why adapters are separate

The media path and comments path fail differently. A comment/API failure must not discard a successfully downloaded video. Keep these stages independent:

```text
media:     URL -> yt-dlp -> source.mp4 + safe metadata + subtitle files
text:      subtitle -> transcript, otherwise local ASR -> transcript
comments:  TikTokApi -> bounded JSON/CSV sample (optional)
visual:    source.mp4 -> LibTV/keyframes/OCR (downstream)
```

## Credentials and redaction

- Prefer `--cookies-from-browser` over exported cookie files.
- Read `TIKTOK_MS_TOKEN` only from the environment.
- Never serialize raw yt-dlp `url`, `manifest_url`, request headers, cookies, proxy credentials, or TikTok signed media addresses.
- `page_metadata.json` may retain broad extractor data only after recursive redaction. `metadata.json` is the stable, safe contract for downstream code.

## Expected external failures

- Deleted/private/age-restricted/region-restricted video.
- Fresh-cookie or browser-impersonation requirement.
- Bot challenge or empty response.
- Subtitle track absent because text is burned into the image.
- TikTok page or private web endpoint changes.

Return a domain error and next action. Do not rotate arbitrary scraping services, copy browser secrets, or silently substitute a paid API.
