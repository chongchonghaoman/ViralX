# ViralX EdgeOne deployment

## Public production deployment

- Date: 2026-08-27
- Account: `metro` (`100046117544`)
- Area: Overseas (China mainland excluded)
- Environment: Production
- Project: `viralx-overseas`
- Project ID: `makers-9ujwycmolg3g`
- Production deployment ID: `dpwfx3vlw9si`
- Public URL: `https://viralx.metrolabs.mobi`
- Project host: `viralx-overseas-ikryg1n5.edgeone.dev` (preview protection may apply)
- Production console: `https://console.cloud.tencent.com/edgeone/pages/project/makers-9ujwycmolg3g/deployment/dpwfx3vlw9si`

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
- `GET /static/connector.js` -> `200`, fixed loopback origin and `targetAddressSpace: "loopback"` present
- `GET /api/health` -> `200 application/json`
- `GET /api/health` -> `keyword_search_provider: scraper7`
- `GET /api/health` -> `release: 2026-08-26-shot-evidence-v1`
- `/` and `/settings.html` include the production CSP (including the fixed loopback Connector origin), pinned CDN assets with SRI, and the `edgeone` deployment marker
- The unconfigured home CTA routes to `/settings.html` instead of implying analysis is ready
- Responsive WebP hero assets return `200 image/webp` with immutable caching
- Direct `POST /api/analyze` on EdgeOne -> actionable Connector recovery message; the browser does not pretend the cloud function can access local TK Note, OpenCV, ShotLoom Core or LibTV
- TikTok Scraper7 keyword discovery uses `GET /feed/search` with `keywords`, `region`, `count`, `cursor`, `publish_time` and `sort_type`; `min_likes=0` is preserved instead of reverting to `5000`
- The adapter reads the documented `data.videos` envelope, keeps compatible list wrappers for safe migration, and separately reports empty candidates, an unknown response shape, business errors and likes-threshold filtering
- RapidAPI credentials are supplied through session-only BYOK or local environment/config; no live credential is committed or used by the public health check
- `/api/health` continues to report the Cloud Function's own LibTV state as `local_only`; the browser separately probes the local Connector
- Browser pipeline mode routes `/api/analyze` to authenticated `http://127.0.0.1:57231/connector/v1/analyze`
- Direct cloud `/api/analyze` returns the explicit local Connector recovery message and never claims TK Note, shot evidence, or final-model work ran at the edge
- Production HTTPS page completed a real one-use pairing against the local Connector; the URL fragment was removed before the page reached its steady state
- Production readiness now evaluates the selected shot strategy: ShotLoom dependencies and visual model, LibTV login, either provider in Auto, or explicit collection-only.
- Connector returned `403` for an untrusted Origin and `204` for the trusted CORS/private-network preflight
- Connector `1.2.0` repeated-launch test passed: the existing verified ViralX instance exited cleanly, one replacement process acquired `127.0.0.1:57231`, and the new pairing page completed successfully
- `GET http://viralx.metrolabs.mobi/` -> `302 https://viralx.metrolabs.mobi/`
- TLS hostname validation succeeds for `viralx.metrolabs.mobi`

The home page and settings page are checked from the live HTTPS domain in desktop and mobile Chromium after each deployment. Full-pipeline readiness is the conjunction of browser loopback permission, a paired Connector session, a ready selected shot strategy, and a configured final model. LibTV login is required only when selected or used as an Auto fallback; the Cloud Function's own `local_only` state is not shown as the final browser state.

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

The online runtime intentionally does not expose local settings, cache-clear, or LibTV authentication APIs. `/settings.html` provides a browser-only BYOK configuration surface: OpenAI, Claude, Gemini, DeepSeek, OpenRouter and custom API choices live in the current tab's `sessionStorage` and disappear when the tab closes. Analysis credentials are sent only to the authenticated loopback Connector, not to EdgeOne. The cloud function remains a constrained public-safe surface for health, keywords, export, and an explicit recovery response when `/api/analyze` is called directly.

The public page calls the separately installed ViralX Connector at `http://127.0.0.1:57231` for the complete pipeline. This is not an EdgeOne proxy: the browser connects directly to loopback after its Local Network Access permission flow. Connector uses an exact Origin allowlist, CORS/PNA validation, a one-use fragment bootstrap, in-memory sessions, and bounded analysis. It exposes only status, pairing, optional LibTV login/status/logout, and analysis. It does not expose local settings, cache clearing, arbitrary filesystem export, or CLI tokens. Shot-model and final-model credentials are accepted only on the authenticated analysis request and are forwarded directly to their selected providers without being persisted or echoed.

The deployed environment has no project-level RapidAPI, shot-model, or final-model credential configured. Keyword discovery uses TikTok Scraper7, while a directly pasted TikTok URL bypasses search. Every task then runs TK Note collection, ShotLoom Core or the configured LibTV fallback, evidence merge, quality gates, and the selected final model. The edge function cannot access the visitor's local source file or OpenCV runtime. Common final-model providers use fixed endpoints; custom providers expose protocol, Base URL, key and model fields.

The local Flask version remains the full-control runtime for:

- Python and the Flask API routes;
- TK Note / `yt-dlp` ingestion;
- ShotLoom Core scene detection, keyframe sampling, visual facts and evidence quality gates;
- optional official LibTV CLI browser login, canvas creation, source-video upload, and multimodal shot-analysis node;
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

`public/` is generated and ignored by Git. The source of truth is the Flask template, shared static assets, `cloud-functions/`, and `scripts/build-edgeone.mjs`. The build stages only the public-safe cloud entrypoint, backend modules (including the lazy-import ShotLoom adapter), and vendored TK Note scripts; it does not bundle OpenCV wheels, the local LibTV CLI, source videos, caches, or `config.json`.

Reference: [EdgeOne custom domain documentation](https://pages.edgeone.ai/document/custom-domain) and [HTTPS configuration overview](https://pages.edgeone.ai/document/https-configuration-overview).
