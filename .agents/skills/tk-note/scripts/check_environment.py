#!/usr/bin/env python3
"""Check TK Note's free local acquisition and evidence routes."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

from _common import find_shared_qwen_python, find_shared_whisper_python


def main() -> int:
    try:
        import yt_dlp

        yt_dlp_version = getattr(getattr(yt_dlp, "version", None), "__version__", "installed")
    except Exception:
        yt_dlp_version = None
    yt_dlp_cli = shutil.which("yt-dlp")
    media_ready = bool(yt_dlp_version or yt_dlp_cli)
    media_status = "OK" if yt_dlp_version else "AVAILABLE_CLI_FALLBACK" if yt_dlp_cli else "BLOCKED"
    qwen_python = find_shared_qwen_python()
    whisper_python = find_shared_whisper_python()
    ms_token_present = bool(os.environ.get("TIKTOK_MS_TOKEN"))
    payload = {
        "skill": "tk-note",
        "python": sys.executable,
        "routes": {
            "tiktok_media": media_status,
            "subtitle_tracks": media_status,
            "ffmpeg_audio": "OK" if shutil.which("ffmpeg") else "BLOCKED",
            "qwen3_asr": "OK" if qwen_python else "UNAVAILABLE",
            "whisper_asr": "OK" if whisper_python else "UNAVAILABLE",
            "tiktok_comments": "OK" if importlib.util.find_spec("TikTokApi") else "OPTIONAL_DEPENDENCY_MISSING",
        },
        "details": {
            "yt_dlp_version": yt_dlp_version,
            "yt_dlp_cli": yt_dlp_cli,
            "ffmpeg": shutil.which("ffmpeg"),
            "shared_qwen_python": str(qwen_python) if qwen_python else None,
            "shared_whisper_python": str(whisper_python) if whisper_python else None,
            "shared_cache": str(Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes"))),
            "tiktok_ms_token_present": ms_token_present,
        },
        "guidance": [
            "媒体下载只要求 yt-dlp；ffmpeg/ASR/评论失败不应阻止视频继续交给 LibTV。",
            "优先在当前 Python 安装 yt-dlp；CLI fallback 可用，但不同 Python 的网络证书环境可能不同。",
            "TikTokApi 评论路线是可选的，可能需要 TIKTOK_MS_TOKEN、Playwright 或代理。",
            "任何凭据只报告是否存在，不输出具体值。",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if media_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
