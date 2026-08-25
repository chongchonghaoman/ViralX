# ViralX EdgeOne deployment

## Public production deployment

- Date: 2026-08-25
- Account: `metro` (`100046117544`)
- Area: Overseas (China mainland excluded)
- Environment: Production
- Project: `viralx-overseas`
- Project ID: `makers-9ujwycmolg3g`
- Production deployment ID: `dpctpv0yzdj1`
- Public URL: `https://viralx.metrolabs.mobi`
- Project host: `viralx-overseas-ikryg1n5.edgeone.dev` (preview protection may apply)
- Production console: `https://console.cloud.tencent.com/edgeone/pages/project/makers-9ujwycmolg3g/deployment/dpctpv0yzdj1`

The custom domain is active and serves the production deployment without a preview token. The project uses the overseas area because `metrolabs.mobi` does not have the ICP filing required for a China-mainland Pages custom domain.

### DNS and HTTPS

- DNS zone: `metrolabs.mobi` (Tencent Cloud DNSPod)
- Record: `viralx` / `CNAME` / default line / TTL `600`
- Target: `viralx.metrolabs.mobi.pages.dnsoe4.com`
- Edge HTTPS certificate: free EdgeOne certificate, RSA 2048, automatic renewal enabled
- Current certificate expiry: 2026-11-22 07:59:59
- Force HTTPS: enabled with an HTTP `302` redirect

Verified on the public custom domain:

- `GET /` -> `200 text/html`
- `GET /settings.html` -> `200 text/html`
- `GET /api/health` -> `200 application/json`
- `GET /api/health` -> `keyword_search_provider: api23`
- `POST /api/analyze` with a keyword and no key -> actionable API23 configuration error
- `GET http://viralx.metrolabs.mobi/` -> `302 https://viralx.metrolabs.mobi/`
- TLS hostname validation succeeds for `viralx.metrolabs.mobi`

The home page and settings page were visually checked from the live HTTPS domain. The same production build had already passed desktop and 390px mobile Chromium review before the custom-domain binding.

## Original protected deployment

The earlier global-area project is retained as deployment history:

- Project: `viralx`
- Project ID: `makers-frd9jhx0avrj`
- Production deployment ID: `dparge5yigjw`
- Preview deployment ID: `dp0nthl3djt2`
- Protected host: `https://viralx-zocsxxpd.edgeone.cool`

The generated host requires EdgeOne preview access protection and is not the public production URL. Access tokens are intentionally not committed.

## Runtime boundary

The deployed site now includes an EdgeOne Python Cloud Function. The browser calls these same-origin routes:

- `GET /api/health`
- `GET /api/keywords`
- `POST /api/analyze` (NDJSON)
- `POST /api/generate_variants`
- `POST /api/export-obsidian` (Obsidian URI or Markdown download)

The online runtime intentionally does not expose the local settings or cache-clear APIs. `/settings.html` provides a browser-only BYOK configuration surface: OpenAI, Claude, Gemini, DeepSeek, OpenRouter and custom API choices live in the current tab's `sessionStorage`, are attached to same-origin API requests over HTTPS, and disappear when the tab closes. The cloud function also supports the unified `MODEL_*` EdgeOne environment variables. It never returns credential values, writes temporary assets under `/tmp`, limits a request to one video, and stays within EdgeOne's 120-second / 6MB function boundary.

The deployed environment currently has no project-level LibTV, RapidAPI API23, or model credential configured. Keyword discovery uses API23, while a directly pasted TikTok URL bypasses API23 and continues through TK Note. Visitors can keep LibTV as the default analysis chain or select one model provider in `/settings.html`. Common providers use fixed official endpoints; custom providers expose protocol, Base URL, key and model fields. EdgeOne accepts only public HTTPS custom endpoints and rejects private, loopback and link-local targets, while local Flask may connect to a user's own HTTP or intranet service. Readiness indicators never imply that an external provider request was successfully billed or completed.

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

To deploy explicitly to the public overseas project:

```bash
npm run build:edgeone
npx edgeone makers deploy public -n viralx-overseas -e production -a overseas --json
```

`public/` is generated and ignored by Git. The source of truth is the Flask template, shared static assets, `cloud-functions/`, and `scripts/build-edgeone.mjs`. The build stages only the public-safe cloud entrypoint, backend modules, and vendored TK Note / LibTV helper scripts; it never copies `config.json`.

Reference: [EdgeOne custom domain documentation](https://pages.edgeone.ai/document/custom-domain) and [HTTPS configuration overview](https://pages.edgeone.ai/document/https-configuration-overview).
