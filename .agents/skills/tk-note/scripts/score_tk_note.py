#!/usr/bin/env python3
"""Score a TK Note Markdown view against note_budget.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from _common import read_json, write_json


def visible_chars(markdown: str) -> int:
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[#>\-*|\s:]+", "", text, flags=re.M)
    return len(re.sub(r"\s+", "", text))


def main() -> int:
    parser = argparse.ArgumentParser(description="Score TK Note Markdown against note_budget.json.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--note-path", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    budget = read_json(args.out_dir / "note_budget.json", {}) or {}
    actual = visible_chars(args.note_path.read_text(encoding="utf-8", errors="replace"))
    low = int(budget.get("recommended_note_chars_min") or 0)
    high = int(budget.get("recommended_note_chars_max") or 0)
    status = "too_short" if actual < low else "too_long" if actual > high else "ok"
    result = {
        "note_path": str(args.note_path),
        "actual_note_chars": actual,
        "recommended_note_chars_min": low,
        "recommended_note_chars_max": high,
        "status": status,
        "visual_dependency": budget.get("visual_dependency"),
        "writing_guidance": budget.get("writing_guidance"),
    }
    if args.out:
        write_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
