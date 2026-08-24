#!/usr/bin/env python3
"""Compute note_budget.json from existing TK Note assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import compute_note_budget


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute TK Note note_budget.json.")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compute_note_budget(args.out_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
