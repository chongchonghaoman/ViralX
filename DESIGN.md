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
- Settings macrostructure: Long Form + Sticky Category Index.
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
- Story sections: one-time reveals when entering the viewport.
- Evidence map: frames and waveform reveal in the order a viewer reads them.
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
- Local settings preserve secrets and local directories in the Flask runtime. EdgeOne settings
  expose only cloud-safe fields and keep credentials in the current browser session.
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

- The Flask build is the full local product. It owns /api/analyze, /api/settings,
  /api/keywords, /api/export-obsidian, TK Note, LibTV, local video/cache files, and
  Obsidian export.
- The EdgeOne build combines the static website with a constrained Python Cloud Function. It
  may run one-video analysis with temporary `/tmp` assets, but must never claim persistent
  local files, browser cookies, arbitrary proxies, caches, or direct Obsidian writes exist at
  the edge.
- `/settings.html` is a session-first BYOK surface. API keys stay in `sessionStorage`, travel
  only with same-origin HTTPS requests, are never echoed by health responses, and disappear
  when the tab closes. Project-level EdgeOne environment variables remain supported.
- Public readiness labels distinguish interface availability, credential presence, and a
  completed external provider analysis; one must never be presented as proof of another.

## Shared assets

- static/tokens.css: canonical design tokens.
- static/viralx.css: shared website and result/report components.
- static/settings.css: settings-only layout.
- static/viralx.js: full Flask interaction and GSAP.
- static/settings.js: settings interaction and route entrance motion.
- static/assets/viralx-title-shuei-wide.svg: exact one-line outlined homepage claim.
- static/assets/viralx-title-shuei-stacked.svg: exact two-line outlined mobile claim.
