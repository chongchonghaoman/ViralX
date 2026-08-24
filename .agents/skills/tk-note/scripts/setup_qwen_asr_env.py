#!/usr/bin/env python3
"""Create/update the shared Qwen3-ASR environment used by note skills."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SHARED_CACHE = Path(
    os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes")
).expanduser()
SHARED_VENV = SHARED_CACHE / "qwen3-asr-venv"
LEGACY_VENVS = (
    Path.home() / ".cache" / "dy-note" / "qwen3-asr-venv",
    Path.home() / ".cache" / "douyin-note" / "qwen3-asr-venv",
)


def default_venv() -> Path:
    if SHARED_VENV.exists():
        return SHARED_VENV
    return next((path for path in LEGACY_VENVS if path.exists()), SHARED_VENV)


def venv_python(venv: Path) -> Path:
    windows = venv / "Scripts" / "python.exe"
    return windows if windows.exists() or sys.platform == "win32" else venv / "bin" / "python"


def run(command: list[str], dry_run: bool) -> None:
    print(" ".join(str(part) for part in command))
    if not dry_run:
        subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up shared Qwen3-ASR for DyNote, Bili Note, and TK Note.")
    parser.add_argument("--venv", type=Path, default=default_venv())
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    args.venv.parent.mkdir(parents=True, exist_ok=True)
    if not venv_python(args.venv).exists():
        run([args.python, "-m", "venv", "--system-site-packages", str(args.venv)], args.dry_run)
    python = venv_python(args.venv)
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"], args.dry_run)
    run(
        [str(python), "-m", "pip", "install", "qwen-asr", "accelerate", "qwen-omni-utils", "pandas>=2.3"],
        args.dry_run,
    )
    if not args.dry_run:
        run([str(python), "-c", "import torch, qwen_asr; print(torch.__version__, torch.cuda.is_available())"], False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
