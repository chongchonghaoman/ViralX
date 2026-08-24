# ViralX EdgeOne deployment

## Production deployment

- Date: 2026-08-25
- Account: `metro` (`100046117544`)
- Area: Global
- Environment: Production
- Project: `viralx`
- Project ID: `makers-frd9jhx0avrj`
- Production deployment ID: `dparge5yigjw`
- Preview deployment ID: `dp0nthl3djt2`
- Preview host: `https://viralx-zocsxxpd.edgeone.cool`
- Protected production host: `https://viralx-zocsxxpd.edgeone.cool` (access token intentionally not committed)
- Production console: `https://console.cloud.tencent.com/edgeone/pages/project/makers-frd9jhx0avrj/deployment/dparge5yigjw`
- Preview console: `https://console.cloud.tencent.com/edgeone/pages/project/makers-frd9jhx0avrj/deployment/dp0nthl3djt2`

The production deployment completed successfully. Its page, full `/static/viralx.js`, `/settings.html`, `/api/health`, session-BYOK readiness contract, and private-route boundary were verified from the public EdgeOne host; the page was also visually checked in desktop and 390px mobile Chromium before deployment. `/api/settings` and `/api/cache/clear` return 404 by design. The generated `edgeone.cool` host still uses EdgeOne preview access protection, so a valid preview token or authenticated console session is required; preview tokens are short-lived and the un-tokened host returns 401. EdgeOne signs the provided token for the root entry: open the protected production URL first, then use the in-page `设置` link to reach `/settings.html` with the established access cookie.

## Runtime boundary

The deployed site now includes an EdgeOne Python Cloud Function. The browser calls these same-origin routes:

- `GET /api/health`
- `GET /api/keywords`
- `POST /api/analyze` (NDJSON)
- `POST /api/generate_variants`
- `POST /api/export-obsidian` (Obsidian URI or Markdown download)

The online runtime intentionally does not expose the local settings or cache-clear APIs. `/settings.html` provides a browser-only BYOK configuration surface: supported credentials and model choices live in the current tab's `sessionStorage`, are attached to same-origin API requests over HTTPS, and disappear when the tab closes. The cloud function also supports EdgeOne environment variables. It never returns credential values, writes temporary assets under `/tmp`, limits a request to one video, and stays within EdgeOne's 120-second / 6MB function boundary.

The deployed environment currently has no project-level LibTV, RapidAPI, Gemini, OpenRouter, or MiniMax credential configured. The UI therefore reports `云端接口在线 · 待配置 LibTV` until the visitor supplies a session credential in `/settings.html` or the required EdgeOne environment variables are added. This is a real online API; readiness indicators never imply that an external provider request was successfully billed or completed.

The local Flask version remains the full-control runtime for:

- Python and the Flask API routes;
- TK Note / `yt-dlp` ingestion;
- LibTV uploads and polling;
- local video and analysis caches;
- direct Obsidian filesystem export;
- editable settings and destructive cache management;
- jobs that may exceed the cloud function time or response limits.

## Build and deploy

```bash
npm run build:edgeone
npm run preview:edgeone
npm run deploy:edgeone
```

`public/` is generated and ignored by Git. The source of truth is the Flask template, shared static assets, `cloud-functions/`, and `scripts/build-edgeone.mjs`. The build stages only the public-safe cloud entrypoint, backend modules, and vendored TK Note / LibTV helper scripts; it never copies `config.json`.

## Custom `.mobi` domain

Binding is intentionally not guessed. The exact `.mobi` hostname was not present in the repository, environment, or prior task context. Once the hostname is supplied, bind it to project `makers-frd9jhx0avrj` in EdgeOne Pages and complete the DNS / HTTPS verification shown by the console.

Reference: [EdgeOne custom domain documentation](https://pages.edgeone.ai/document/custom-domain) and [HTTPS configuration overview](https://pages.edgeone.ai/document/https-configuration-overview).
