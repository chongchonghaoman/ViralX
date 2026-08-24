#!/usr/bin/env python3
"""Create a resumable TK Note evidence plan before expensive collection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import utc_now, write_json


MODES = {
    "single-video-note": ("one TikTok video", ["page_metadata", "subtitle_or_asr", "visual_review_if_sparse"]),
    "comment-insight": ("one TikTok comment section", ["page_metadata", "bounded_comment_sample", "transcript_if_needed"]),
    "account-analysis": ("one TikTok account sampled across videos", ["sample_table", "selected_metadata", "selected_transcripts"]),
    "topic-research": ("one keyword, hashtag, or competitor set", ["query_log", "sample_table", "selected_deep_evidence"]),
    "script-mining": ("one or more TikTok scripts and visual examples", ["subtitle_or_asr", "libtv_or_keyframes", "comments_if_needed"]),
    "viral-analysis": ("one TikTok video prepared for ViralX", ["safe_video_asset", "subtitle_or_asr", "libtv_visual_analysis"]),
    "commerce-analysis": ("one TikTok commerce video", ["metadata", "subtitle_or_asr", "libtv_offer_evidence", "comments"]),
    "fact-check": ("claims inside TikTok videos", ["exact_transcript", "claim_table", "external_sources"]),
    "knowledge-archive": ("one or more TikTok videos", ["raw_assets", "metadata", "provenance"]),
}


def build_plan(mode: str, objective: str, sources: list[str], tier: str) -> dict:
    unit, evidence = MODES[mode]
    return {
        "schema": "tk-note-analysis-plan-v1",
        "mode": mode,
        "tier": tier,
        "objective": objective,
        "unit_of_analysis": unit,
        "sources": [{"id": f"S{i:02d}", "value": value} for i, value in enumerate(sources, 1)],
        "required_evidence": evidence,
        "evidence_ladder": [
            {"level": "E0", "name": "user_input"},
            {"level": "E1", "name": "safe_page_metadata"},
            {"level": "E2", "name": "subtitle_track"},
            {"level": "E3", "name": "local_asr"},
            {"level": "E4", "name": "visible_comments"},
            {"level": "E5", "name": "libtv_keyframes_or_ocr"},
            {"level": "E6", "name": "external_sources"},
        ],
        "analysis_rules": [
            "Separate observations, model output, external facts, and inference.",
            "Do not call caption metadata a transcript.",
            "Do not claim visual coverage from audio-only evidence.",
            "Record sample size, collection time, and inclusion criteria.",
            "Preserve completed assets when a later stage is blocked.",
        ],
        "synthesis_gate": {
            "may_synthesize_when": ["Raw assets and provenance exist", "Missing evidence is explicitly listed"],
            "must_not_claim": ["complete transcript from caption only", "all comments from a sample", "visual facts from ASR alone"],
        },
        "created_at": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create TK Note analysis_plan.json.")
    parser.add_argument("--mode", choices=sorted(MODES), default="single-video-note")
    parser.add_argument("--objective", default="Analyze TikTok material into a reliable evidence-backed note.")
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--tier", choices=["quick-pass", "evidence-pass", "research-pass"], default="evidence-pass")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    out_path = args.out or args.out_dir / "analysis_plan.json"
    if out_path.exists() and not args.force:
        existing = json.loads(out_path.read_text(encoding="utf-8-sig"))
        existing["reused_existing"] = True
        print(json.dumps(existing, ensure_ascii=False, indent=2))
        return 0
    plan = build_plan(args.mode, args.objective, args.source, args.tier)
    write_json(out_path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
