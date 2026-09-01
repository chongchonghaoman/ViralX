# Design — ViralX

ViralX is an evidence-led web application for short-video researchers, creative operators,
and product teams. It uses cloud and local web runtimes behind the same browser interface.
This document is the visual contract for every browser surface.

## Design position

The interface should make analysis feel creative without turning evidence into decoration.
Its core promise is:

> ViralX turns a real short video into verifiable evidence, an explainable structure, and
> an executable remake script.

The 2026 website direction directly maps the public component anatomy and product pacing of
https://www.butter.video/: two detached floating navigation capsules, a centred tactile
object above one monumental first-screen claim, a dark editor surface, four sequential
workflow columns, generous breathing room, and an index footer. ViralX uses Butter's
observed colour system and type roles, while retaining original content and functional UI.
It does not copy Butter's wordmark, keychain object, copy, imagery, or licensed font files.

## Genre and macrostructure

- Genre: refined product editorial, grounded by technical evidence.
- Primary macrostructure: Centered Marquee + Embedded Studio.
- Settings macrostructure: Quick Setup + Advanced Accordion, with a compact sticky index.
- Report macrostructure: focused document dialog.
- The embedded studio is a real entry point, not a fake marketing mockup.

## Palette

The canonical values live in static/tokens.css.

- `#EDEDED` is the page canvas; `#FAFAFA` is the floating navigation and control surface.
- `#0F0F0F` is the primary ink and `#1E1E1E` is the analysis surface.
- `#4DC5E5` is the primary action, progress, and evidence signal.
- `#F9ABFF` and `#E9D352` are limited punctuation colours used only in the evidence demo.
- These values were observed in Butter's current public stylesheet on 2026-08-24.
- Accent colours never become full-page gradients or generic AI glow.

## Typography

- Butter currently uses the commercial Die Grotesk for display and ABC Diatype for text.
- ViralX does not copy or hotlink those licensed font binaries.
- Display and Latin UI: Hanken Grotesk (SIL OFL), weights 400–700, roman.
- Chinese fallback and body: Noto Sans SC, weights 400–700.
- The homepage claim alone uses exact path outlines generated from the user-supplied
  `DNPShueiMinPr6N B` face. The repository and public build contain only the two finished SVG
  artworks; they do not contain, embed, convert, or redistribute the source font program.
  A semantic, visually hidden H1 preserves the title for assistive technology and search.
  The Shuei face never appears in navigation, body copy, forms, settings, reports, or evidence
  labels.
- Text-based section display scale tops out around 6.75rem on wide screens; the outlined hero
  claim is controlled by artwork width (21rem stacked, 58rem wide), while product controls stay
  at normal reading size.
- Chinese display tracking is tuned more conservatively than English display tracking.
- Text-based display headings use overflow-wrap: anywhere. The hero claim switches from its
  exact stacked artwork to its exact wide artwork at 40rem. Both remain complete compositions
  at 320px, 375px, 414px, 768px, and 1280x800.

## Spacing and shape

- Four-point named spacing scale; no ad hoc spacing values.
- Controls share a 52px base height.
- Desktop navigation uses two detached 20px-radius floating capsules: product navigation on
  the left and account/action controls on the right. Mobile recombines them into one shell.
- The hero reserves `--hero-nav-clearance` before the product visual. Navigation and the
  signal-orbit may never occupy the same vertical lane at desktop widths.
- Product panels and secondary controls use restrained 6–20px radii; pills are reserved for
  navigation and primary actions.
- Evidence and workflow sections rely on rules, contrast, and sequence rather than nested
  card grids.

## Product visual

static/assets/viralx-signal-orbit.png is an original ViralX hero asset. It depicts video
frames, signal waveforms, timeline rails, and a play lens. The website masks it into a centred
floating signal object and blends its dark field into the neutral page. It replaces Butter's
signature hanging object rather than imitating or copying it. The accessible alternative text
explains its role in the product story.

The two `viralx-title-shuei-*.svg` files are title artwork, not webfonts. They are generated
locally with `scripts/generate-outlined-title.py`; the source TTF remains outside the project.
Install the pinned build-only dependency from `requirements-dev.txt` before regeneration.

## Motion

- Library: GSAP 3.13 with ScrollTrigger.
- First screen: one ordered sequence for navigation, product object, claim, and studio.
- Story sections stay immediately visible instead of repeating the same fade-up on every chapter.
- Evidence map: frames and waveform provide the single below-fold reveal, in reading order.
- Live analysis progress remains bound to scaleX and actual streamed state.
- Result cards and reports reveal only when real content arrives.
- No infinite floating, bounce loops, or celebratory effects.
- With prefers-reduced-motion: reduce, spatial transforms are removed and content remains
  immediately visible.

## Interaction and content

- Primary CTA is the real 开始拉片 action.
- Visible success is silent; failures explain the recovery action.
- Every interactive element has hover, focus-visible, active, and disabled treatment where
  applicable.
- Local settings preserve secrets and local directories in the Flask runtime. The hosted page calls
  one owner-operated ViralX Worker over HTTPS; visitors never pair a loopback process. The server may
  provide default credentials, while optional browser overrides remain session-only. There is one fixed
  evidence pipeline. TK Note is mandatory collection; owner-only network recovery stays off the public UI.
- ShotLoom Core is the default scene splitter and frame sampler. It reuses the exact file already
  downloaded by TK Note, then sends keyframes to the visual model configured above. It is not a
  second model. LibTV remains an explicit failure fallback, never a silent default dependency.
- The default contract is `shot_engine=shotloom` plus `shot_model_source=inherit`: one visual-model
  connection performs frame-fact recognition and final evidence synthesis. A separate shot model,
  `auto` fallback, LibTV-only, and collection-only remain expert troubleshooting choices.
- The first settings viewport asks for an outcome and two credentials: one shared RapidAPI Key for
  API23-first keyword discovery with automatic Scraper7 fallback, then a complete final-model
  connection with Base URL, API Key and model ID.
  Qwen3-VL Flash is the recommended default and the capability note requires a video-capable model.
  Direct-video ingestion remains a compatibility path, not the product's primary information architecture.
  OpenAI, Claude, Gemini, DeepSeek, OpenRouter, Custom, separate
  shot-model credentials, network controls and LibTV remain available only inside advanced
  disclosures. The quick path always exposes Base URL; only Custom reveals the protocol selector.
- Each provider keeps an in-memory draft while the page is open, so changing providers never
  places one service's key into another service's field. The provider is always the final stage
  after TK Note and shot evidence merge; failed final-model calls never consume a fallback
  provider. A failed shot stage may use LibTV only when the user explicitly enables Auto fallback.
- Do not invent customer logos, performance metrics, case studies, or model results.

## Responsive order

Mobile keeps the actual task order:

1. brand and settings access;
2. product visual and claim;
3. source input and start action;
4. progress;
5. evidence explanation;
6. results and report.

Desktop may expand the navigation and split the evidence/workflow chapters, but it must not
change this sequence.

## Runtime and deployment boundary

- The Flask build is the full local product. It owns `/api/analyze`, `/api/settings`, TK Note,
  ShotLoom Core, local video/cache files, Obsidian export and optional `/api/libtv/auth/*`.
  ViralX asks the official LibTV CLI for connection state but never reads its tokens.
- The EdgeOne build is a static product surface plus browser-safe export helpers. It does not run
  TK Note, OpenCV, persistent caches, browser-cookie access or CLI login itself.
- The production page calls an owner-operated ViralX Worker through a credential-free HTTPS base
  URL. The Worker runs TK Note, ShotLoom Core (or owner-configured LibTV fallback), evidence merge,
  then the selected visual model API. The model receives sampled frames during shot evidence and
  the merged named evidence during final synthesis; it never receives an unbounded source-file upload.
- The public Worker binds locally behind an outbound tunnel, allows exact trusted Origins, validates
  CORS preflights, limits concurrency and request frequency, and applies evidence-cache retention.
  It never mounts settings writes, cache clearing, arbitrary file export, local Cookie/proxy controls,
  LibTV account actions or CLI tokens.
- `/settings.html` is an optional session-level BYOK surface. Server defaults can make the product
  ready without visitor configuration. Overrides stay in `sessionStorage`, are never echoed by health
  responses, and disappear when the tab closes.
- Hosted settings require HTTPS for custom model endpoints, and the public Worker rejects private,
  loopback and non-standard-port destinations. Local Flask may deliberately use HTTP and private
  endpoints for self-hosted models.
- Public readiness labels distinguish interface availability, credential presence, and a
  completed external provider analysis; one must never be presented as proof of another.

## Shared assets

- static/tokens.css: canonical design tokens.
- static/viralx.css: shared website and result/report components.
- static/settings.css: settings-only layout.
- static/viralx.js: full Flask interaction and GSAP.
- static/settings.js: settings interaction and route entrance motion.
- static/runtime-config.js: same-origin development defaults and hosted Worker routing contract.
- static/cloud-config.js: session-only overrides plus endpoint routing to the public Worker.
- static/assets/viralx-title-shuei-wide.svg: exact one-line outlined homepage claim.
- static/assets/viralx-title-shuei-stacked.svg: exact two-line outlined mobile claim.
- static/assets/viralx-signal-orbit-640.webp: mobile and compact-display hero source.
- static/assets/viralx-signal-orbit-1024.webp: desktop and high-density hero source.

## Production UX and security contract

- Public availability is not analysis readiness. The homepage health check keeps the user at the
  analysis studio and distinguishes Worker online, owner configuration incomplete, and Worker offline.
  An offline primary action explains that static cases remain available; it never sends visitors to
  Connector setup. Search readiness and analysis readiness are reported separately: keyword input needs
  the API23-first / Scraper7-fallback chain plus the fixed TK Note + ShotLoom + visual-model path, while a direct HTTP(S) video URL only
  needs the analysis path. A missing search Key must never block a valid direct-video analysis.
- The dual search chain is explained at the source field: video URLs bypass it, while keyword discovery
  needs one RapidAPI Key. Both local Flask and a paired hosted page may use the browser-connected LibTV CLI.
- The settings page presents the fixed contract `TikTok API23 -> Scraper7 fallback -> TK Note -> ShotLoom cut/frame ->
  configured visual model -> evidence merge -> same model final synthesis`. TK Note is marked required,
  ShotLoom + inherit is the default, LibTV is an explicit fallback, and collection-only states plainly
  that it will not generate a final report.
- Hosted LibTV state is owner-managed and read-only. Local Flask still exposes `disconnected`,
  `starting`, `awaiting_browser`, `connected`, `error`, `unavailable`, and compatibility `local_only`.
  Starting/awaiting states prevent duplicate actions; errors always expose a recovery action, and
  reduced motion removes the status pulse.
- Settings validation is field-local. API key, model name and custom Base URL errors set
  `aria-invalid`, expose `aria-errormessage`, reveal the correct disclosure and move focus to
  the relevant control without forcing the user back to the page-level status region.
- Markdown is untrusted, even when it comes from an analysis provider. Marked output must pass
  through the local allowlist sanitizer before reaching `innerHTML`; scripts, embedded content,
  forms, SVG/MathML, event attributes, style attributes and unsafe URL schemes are dropped.
- CDN scripts are exact-version resources protected by SRI, and page-level CSP limits scripts,
  styles, fonts, images and connections to the smallest required origins. GSAP enhancement remains optional;
  the page is fully visible and operable when it is blocked or reduced motion is requested.

## Hallmark review record — 2026-08-26

- Removed the false provider choice and made the five-stage dependency chain visible in settings
  and live progress.
- Kept one dominant accent, restrained motion, native controls, field-local errors, and explicit
  recovery states; no decorative metrics, fake testimonials, floating loops, or generated proof.
- Desktop and mobile preserve the same information order. The five-stage progress grid expands
  only when space allows and falls back to a readable linear list on narrow screens.
- Readiness copy names the missing dependency instead of using a generic online/offline state.
- Replaced the LibTV-mandatory UI with a provider-neutral shot-evidence stage without changing the
  established palette, typography, spacing, navigation, hero, or motion language. The added
  controls reuse the existing native radio, select, disclosure, field-error, and status patterns.
- Added explicit blocked and fallback states. The UI never renders partial evidence as a completed
  report and never calls collection-only mode a full analysis.

## Settings simplification record — 2026-08-31

- Replaced the five equally prominent technical sections with one quick-setup surface and one
  advanced accordion. The primary path asks for the desired outcome, one RapidAPI search Key, then the final
  model Base URL, API Key and model ID.
- Made Qwen3-VL Flash the recommended new-user model while keeping all three connection fields
  visible. Editing the Base URL away from a provider preset automatically promotes the configuration
  to a custom endpoint without losing the typed Key or model ID. The UI states that full analysis
  requires a video-capable model.
- Promoted keyword discovery to the primary configuration path because ViralX begins from a
  keyword and discovers relevant high-performing videos. Direct URLs remain compatible, but they
  do not make the RapidAPI search credential optional in product setup. TK Note network controls,
  shot-engine selection, LibTV, protocol selection, storage paths and saved topics remain advanced.
- Verified the quick and evidence-only modes at desktop and mobile widths. Reduced-motion,
  keyboard labels, field-local validation and runtime security boundaries remain unchanged.

## Fixed evidence chain record — 2026-08-31

- Reclassified TK Note from an apparent optional module to the mandatory collection stage after every
  search candidate. Advanced TK Note controls now describe recovery only; collection failure blocks all
  downstream work.
- Reclassified ShotLoom Core as scene-cut and frame-sampling infrastructure rather than a second model.
  The default visual path reuses the Base URL, API Key and model ID configured in quick setup.
- Changed the runtime default from implicit `auto` to `shotloom + inherit`. Legacy implicit-auto settings
  migrate once through workflow version 2; explicit LibTV fallback, LibTV-only and collection-only remain.
- Updated the public workflow diagram and copy so visual fact recognition and final evidence synthesis are
  visibly two jobs performed by the configured visual model, with quality gates between them.

## Owner-operated Worker record — 2026-08-31

- Replaced visitor-side loopback pairing with one HTTPS Worker operated by the site owner. The public
  webpage no longer loads Connector code, requests local-network permission or links an unready action
  to settings.
- Added explicit online, owner-configuration-incomplete and offline states. Offline keeps the portfolio
  and static cases readable while live analysis is unavailable.
- Restricted the public API to health, keywords, analysis and variant generation. CORS allowlisting,
  one-task concurrency, per-source rate limiting, input limits, public-only custom endpoints and cache
  retention protect a small personal server without exposing local management surfaces.
- Hosted settings now treat the shared RapidAPI search credential and model credentials as optional session overrides when the Worker
  already owns defaults. Local Cookie, proxy, directories, shot-engine and LibTV controls remain owner-only.

## Source-aware readiness record — 2026-08-31

- Split public readiness into two capabilities instead of one misleading master switch. Keyword discovery
  requires the API23 / Scraper7 search chain and the complete evidence pipeline; direct HTTP(S) video input bypasses only discovery.

## Search fallback record — 2026-09-01

- Added API23 as the primary keyword-discovery provider without adding a second credential field.
- Business errors, HTTP failures, empty responses, invalid post identities, semantic mismatches and
  threshold-empty results automatically continue through Scraper7 inside the same analysis action.
- Both adapters normalize into one video contract before TK Note, so collection, shot evidence and final
  analysis do not branch by search provider. The interface reports the selected source only as concise
  progress text; it asks for recovery only when both providers fail.
- Added a short health-check timeout so an unreachable home Worker resolves to an honest offline state
  instead of leaving the interface stuck on “正在连接服务”. Long-running analysis streams remain unbounded by
  that probe timeout.
- Removed hosted-page anchors to owner-only advanced controls, preventing navigation into sections that are
  intentionally absent from the public BYOK surface.
- Removed repeated section fade-ups. GSAP now concentrates motion in the first-screen sequence and the
  evidence timeline, so scrolling feels deliberate rather than continuously animated.
