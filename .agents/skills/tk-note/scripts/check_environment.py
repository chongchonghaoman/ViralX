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
    browser_candidates = [
        os.environ.get("VIRALX_TK_BROWSER_EXECUTABLE", ""),
        shutil.which("chrome") or "",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
    ]
    browser = next((str(path) for path in browser_candidates if path and Path(path).is_file()), None)
    browser_transport = bool(browser and importlib.util.find_spec("websockets") and importlib.util.find_spec("requests"))
    if browser_transport and not media_ready:
        media_ready = True
        media_status = "AVAILABLE_BROWSER_FALLBACK"
    payload = {
        "skill": "tk-note",
        "python": sys.executable,
        "routes": {
            "tiktok_media": media_status,
            "tiktok_browser_fallback": "OK" if browser_transport else "OPTIONAL_DEPENDENCY_MISSING",
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
            "browser_executable": browser,
            "browser_profile": str(
                Path(os.environ.get("VIRALX_TK_BROWSER_PROFILE", ""))
                if os.environ.get("VIRALX_TK_BROWSER_PROFILE")
                else Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes")) / "tiktok-browser-profile"
            ),
        },
        "guidance": [
            "媒体采集可使用搜索服务临时媒体地址、yt-dlp 或隔离 Chrome 兜底；ffmpeg/ASR/评论失败不应丢弃已验证原片。",
            "优先在当前 Python 安装 yt-dlp、requests 与 websockets；浏览器兜底还需要本机 Chrome 或 Edge。",
            "TikTokApi 评论路线是可选的，可能需要 TIKTOK_MS_TOKEN、Playwright 或代理。",
            "任何凭据只报告是否存在，不输出具体值。",
            "yt-dlp 被网页挑战拦截时，TK Note 会用隔离 Chrome 配置读取播放器媒体流；不会导出 Cookie 或保存签名地址。",
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if media_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
