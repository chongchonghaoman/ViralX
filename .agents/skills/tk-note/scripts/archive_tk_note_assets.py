#!/usr/bin/env python3
"""Rebuild TK Note's reusable evidence manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import build_asset_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive TK Note raw evidence into assets/.")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_asset_manifest(args.out_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
