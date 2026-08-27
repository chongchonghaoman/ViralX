#!/usr/bin/env python3
"""Validate evidence citations in a ViralX Agent report."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


FRAME_CITATION = re.compile(r"\[FRAME:(F\d{3})@([0-9:.]+)\]")
META_CITATION = re.compile(r"\[META:[A-Za-z0-9_-]+\]")


def validate_report(manifest: dict[str, Any], report: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if manifest.get("schema") != "viralx.agent-evidence.v1":
        errors.append("Manifest schema is not viralx.agent-evidence.v1")

    frame_map = {
        str(frame.get("id")): str(frame.get("timestamp"))
        for frame in manifest.get("frames", [])
        if isinstance(frame, dict) and frame.get("id") and frame.get("timestamp")
    }
    cited_ids: set[str] = set()
    for frame_id, timestamp in FRAME_CITATION.findall(report):
        if frame_id not in frame_map:
            errors.append(f"Unknown frame citation: {frame_id}")
            continue
        if frame_map[frame_id] != timestamp:
            errors.append(f"Timestamp mismatch for {frame_id}: expected {frame_map[frame_id]}, got {timestamp}")
            continue
        cited_ids.add(frame_id)

    minimum_frames = min(2, len(frame_map))
    if len(cited_ids) < minimum_frames:
        errors.append(f"Report cites {len(cited_ids)} valid frame(s); at least {minimum_frames} required")

    evidence = manifest.get("evidence", {}) if isinstance(manifest.get("evidence"), dict) else {}
    if evidence.get("metadata_path") and not META_CITATION.search(report):
        errors.append("Metadata exists but the report has no [META:*] citation")
    if evidence.get("transcript_available") and "[TK:transcript]" not in report:
        errors.append("Transcript exists but the report has no [TK:transcript] citation")

    comments_available = bool(evidence.get("comments_available"))
    if comments_available:
        if "[COMMENTS:unavailable]" in report:
            errors.append("Report marks comments unavailable even though the manifest says they are available")
    else:
        if "[COMMENTS:sample]" in report:
            errors.append("Report cites a comment sample that was not collected")
        if "[COMMENTS:unavailable]" not in report:
            errors.append("Missing-comments disclosure must include [COMMENTS:unavailable]")
        disclosure = re.search(
            r"评论(?:证据)?(?:未采集|未收集|不可用|缺失)|comments?\s+(?:were\s+)?(?:not collected|unavailable|missing)",
            report,
            flags=re.IGNORECASE,
        )
        if not disclosure:
            errors.append("Report must explicitly state that comment evidence was not collected")

    if manifest.get("coverage", {}).get("coverage_limited"):
        coverage_words = ("coverage", "采样", "覆盖", "间隔", "limited")
        if not any(word in report.lower() for word in coverage_words):
            warnings.append("Frame coverage is limited but the report may not disclose the limitation")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "valid_frame_citations": sorted(cited_ids),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = args.report.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        result = {"valid": False, "errors": [f"Could not read validation input: {exc}"], "warnings": []}
        print(json.dumps(result, ensure_ascii=False))
        return 2
    result = validate_report(manifest, report)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
