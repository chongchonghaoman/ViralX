# Agent-native report contract

Save the completed report as `report.md` beside `manifest.json`.

## Required sections

1. **Evidence coverage** — source, duration, frame count, maximum sampling gap, transcript status, comment status, and all limitations.
2. **Verified timeline** — chronological visual and spoken-word facts. Every bullet must cite metadata, transcript, comments, or one or more exact frames.
3. **Hook and structure** — separate directly observed mechanics from interpretation. Mark interpretation as “Inference”.
4. **Audience evidence** — use comments only when comments were actually collected. Otherwise state `评论证据未采集 [COMMENTS:unavailable]`.
5. **Reusable pattern** — identify patterns that are supported by cited evidence; do not claim causality from a single video.
6. **Remake proposal** — a practical script or shot list. Label it as a recommendation, not an observation.

## Citation rules

- Visual: `[FRAME:F001@00:00.100]` using an exact ID and timestamp from the manifest.
- Speech/subtitle: `[TK:transcript]`.
- Platform facts: `[META:title]`, `[META:metrics]`, `[META:creator]`, or `[META:source]`.
- Comment sample: `[COMMENTS:sample]` only when the manifest marks comments available.
- Missing comments: `[COMMENTS:unavailable]` plus a plain-language disclosure.

Do not attach one citation to a paragraph containing several unsupported claims. Put citations beside the exact sentence or bullet they support.

## Quality bar

- Distinguish `Fact`, `Inference`, and `Recommendation` in wording.
- Never infer audio from images.
- Never infer audience sentiment without comment text.
- Never convert likes/views into a causal explanation.
- Never imply continuous frame-by-frame viewing; disclose the sampling gap.
- If fewer than two usable frames were produced, describe visual analysis as limited.
