#!/usr/bin/env python3
"""Extract a TikTok video into DyNote-compatible local evidence assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests

from _common import (
    TKNoteError,
    build_asset_manifest,
    command_exists,
    compute_note_budget,
    emit_progress,
    find_shared_qwen_python,
    find_shared_whisper_python,
    media_files,
    normalize_metadata,
    parse_subtitle,
    read_json,
    redact_text,
    render_transcript_markdown,
    safe_page_metadata,
    subtitle_files,
    transcript_from_segments,
    validate_tiktok_url,
    write_json,
)


CORE_FILES = ("source.mp4", "metadata.json", "transcript.txt", "segments.json", "note_budget.json")
MEDIA_HOST_SUFFIXES = (
    "tiktok.com", "tiktokcdn.com", "tiktokv.com", "byteoversea.com",
    "ibytedtos.com", "musical.ly", "tikwm.com",
)
DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


def browser_impersonation_available() -> bool:
    try:
        import curl_cffi  # noqa: F401
    except Exception:
        return False
    return True


def browser_impersonation_target():
    from yt_dlp.networking.impersonate import ImpersonateTarget

    return ImpersonateTarget.from_str("chrome")


def safe_media_transport_url(value: str) -> str:
    """Accept only known TikTok transport hosts and never return credentials."""
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username
        or parsed.password
        or not any(host == suffix or host.endswith(f".{suffix}") for suffix in MEDIA_HOST_SUFFIXES)
    ):
        return ""
    return parsed.geturl()


def validate_video_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 4096:
        raise TKNoteError("下载结果为空或过小，不是可用原片")
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 or "video" not in completed.stdout.lower():
            raise TKNoteError("下载结果无法通过视频流校验")
        return
    with path.open("rb") as handle:
        header = handle.read(64)
    if b"ftyp" not in header and not header.startswith(b"\x1aE\xdf\xa3"):
        raise TKNoteError("下载结果缺少可识别的视频文件头")


def finalize_download(candidate: Path, out_dir: Path) -> Path:
    """Atomically replace source.mp4 only after a complete candidate validates."""
    validate_video_file(candidate)
    final_path = out_dir / "source.mp4"
    os.replace(candidate, final_path)
    return final_path


def fallback_info(source_url: str, page: dict[str, Any] | None = None, extractor: str = "browser") -> dict[str, Any]:
    page = page or {}
    video_id_match = re.search(r"/video/(\d+)", source_url)
    author_match = re.search(r"tiktok\.com/@([^/?#]+)", source_url, flags=re.I)
    return {
        "id": video_id_match.group(1) if video_id_match else "",
        "title": page.get("title") or page.get("description") or "TikTok video",
        "description": page.get("description") or "",
        "uploader": author_match.group(1) if author_match else "",
        "duration": page.get("duration") or 0,
        "webpage_url": source_url,
        "extractor": extractor,
        "extractor_key": "TikTok",
        "ext": "mp4",
    }


def download_media_transport(
    media_url: str,
    source_url: str,
    out_dir: Path,
    args: argparse.Namespace,
    *,
    user_agent: str = DEFAULT_BROWSER_UA,
    label: str = "临时媒体地址",
) -> Path:
    """Download a short-lived media URL without persisting or logging it."""
    safe_url = safe_media_transport_url(media_url)
    if not safe_url:
        raise TKNoteError(f"{label}不属于受信任的 TikTok 媒体域名")
    partial = out_dir / "download.transport.mp4.part"
    candidate = out_dir / "download.transport.mp4"
    partial.unlink(missing_ok=True)
    candidate.unlink(missing_ok=True)
    proxies = {"http": args.proxy, "https": args.proxy} if args.proxy else None
    try:
        with requests.get(
            safe_url,
            headers={"User-Agent": user_agent or DEFAULT_BROWSER_UA, "Referer": source_url},
            proxies=proxies,
            timeout=(30, 180),
            stream=True,
            allow_redirects=True,
        ) as response:
            response.raise_for_status()
            if not safe_media_transport_url(response.url):
                raise TKNoteError(f"{label}重定向到了不受信任的域名")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        os.replace(partial, candidate)
        validate_video_file(candidate)
        return candidate
    except TKNoteError:
        raise
    except Exception as exc:
        raise TKNoteError(f"{label}下载失败（{type(exc).__name__}）") from exc
    finally:
        partial.unlink(missing_ok=True)


def find_chrome_executable() -> str:
    configured = str(os.environ.get("VIRALX_TK_BROWSER_EXECUTABLE") or "").strip()
    candidates = [
        configured,
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
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def browser_profile_dir() -> Path:
    configured = str(os.environ.get("VIRALX_TK_BROWSER_PROFILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    shared = Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes"))
    return shared / "tiktok-browser-profile"


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def browser_media_page(source_url: str, args: argparse.Namespace) -> dict[str, Any]:
    """Load TikTok in an isolated real Chromium profile and inspect its player."""
    chrome = find_chrome_executable()
    if not chrome:
        raise TKNoteError("未找到 Chrome 或 Edge，无法启用真实浏览器兜底")
    try:
        from websockets.sync.client import connect
    except Exception as exc:
        raise TKNoteError("缺少 websockets，无法启用真实浏览器兜底") from exc

    profile = browser_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    port = free_loopback_port()
    launch = [
        chrome,
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-blink-features=AutomationControlled",
        f"--user-data-dir={profile}",
        "about:blank",
    ]
    visible = str(os.environ.get("VIRALX_TK_BROWSER_VISIBLE") or "").lower() in {"1", "true", "yes"}
    if not visible:
        launch.insert(1, "--headless=new")
    if args.proxy:
        launch.insert(-1, f"--proxy-server={args.proxy}")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if not visible else 0
    process = subprocess.Popen(
        launch,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        local = requests.Session()
        local.trust_env = False
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                if local.get(f"{base}/json/version", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.25)
        else:
            raise TKNoteError("真实浏览器启动超时")

        target = local.put(f"{base}/json/new?{quote(source_url, safe='')}", timeout=10).json()
        websocket_url = str(target.get("webSocketDebuggerUrl") or "")
        if not websocket_url:
            raise TKNoteError("真实浏览器没有返回可检查的页面")

        with connect(websocket_url, max_size=20_000_000, open_timeout=10) as sock:
            sequence = 0

            def call(method: str, params: dict[str, Any] | None = None, timeout: float = 20) -> dict[str, Any]:
                nonlocal sequence
                sequence += 1
                request_id = sequence
                sock.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
                deadline = time.time() + timeout
                while time.time() < deadline:
                    message = json.loads(sock.recv(timeout=max(1, deadline - time.time())))
                    if message.get("id") == request_id:
                        return message
                raise TKNoteError(f"真实浏览器调用超时：{method}")

            call("Page.enable")
            call("Runtime.enable")
            expression = r"""
(() => {
  const video = document.querySelector('video');
  const text = (selector) => {
    const node = document.querySelector(selector);
    return node ? (node.content || node.textContent || '').trim() : '';
  };
  const resources = performance.getEntriesByType('resource')
    .map(entry => entry.name)
    .filter(value => /\/video\/|\/play\/|\.mp4(?:\?|$)|\.m3u8(?:\?|$)/i.test(value));
  return {
    href: location.href,
    title: text('meta[property="og:title"]') || document.title || '',
    description: text('meta[property="og:description"]') || text('meta[name="description"]') || '',
    media: video ? (video.currentSrc || video.src || '') : '',
    duration: video && Number.isFinite(video.duration) ? video.duration : 0,
    readyState: video ? video.readyState : 0,
    resources: resources.slice(-40),
    userAgent: navigator.userAgent || ''
  };
})()
"""
            page: dict[str, Any] = {}
            for _ in range(30):
                response = call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                page = (((response.get("result") or {}).get("result") or {}).get("value") or {})
                candidates = [page.get("media"), *(page.get("resources") or [])]
                media = next((safe_media_transport_url(value) for value in candidates if safe_media_transport_url(value)), "")
                if media and int(page.get("readyState") or 0) >= 2:
                    page["media"] = media
                    return page
                time.sleep(0.75)
        raise TKNoteError("真实浏览器已打开页面，但播放器没有返回可下载原片")
    except TKNoteError:
        raise
    except Exception as exc:
        raise TKNoteError(f"真实浏览器采集失败（{type(exc).__name__}）") from exc
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


class QuietLogger:
    def debug(self, message: str) -> None:
        return

    def warning(self, message: str) -> None:
        emit_progress("download", "warning", message=redact_text(message))

    def error(self, message: str) -> None:
        emit_progress("download", "error", message=redact_text(message))


def reusable(out_dir: Path, source_url: str | None = None) -> bool:
    video = out_dir / "source.mp4"
    complete = video.is_file() and video.stat().st_size > 0 and all((out_dir / name).exists() for name in CORE_FILES[1:])
    if not complete or not source_url:
        return complete
    metadata = read_json(out_dir / "metadata.json", {}) or {}
    return metadata.get("source_url") == source_url


def source_identity(out_dir: Path) -> str:
    metadata = read_json(out_dir / "metadata.json", {}) or {}
    return str(metadata.get("source_url") or "")


def clean_download_workfiles(out_dir: Path) -> None:
    for path in out_dir.glob("download.*"):
        if path.is_file():
            path.unlink()
    for name in ("audio_16k.wav", "qwen_asr.json"):
        path = out_dir / name
        if path.is_file():
            path.unlink()


def existing_result(out_dir: Path) -> dict[str, Any]:
    manifest_path = out_dir / "assets" / "asset_manifest.json"
    if not manifest_path.exists():
        build_asset_manifest(out_dir)
    metadata = read_json(out_dir / "metadata.json", {}) or {}
    transcript_source = str(metadata.get("transcript_source") or "existing")
    blocked = ["transcript"] if transcript_source in {"blocked", "none"} else []
    return {
        "status": "reused",
        "source_url": metadata.get("source_url", ""),
        "video_id": metadata.get("video_id", ""),
        "video_file": str(out_dir / "source.mp4"),
        "video_size_bytes": (out_dir / "source.mp4").stat().st_size,
        "metadata": str(out_dir / "metadata.json"),
        "page_metadata": str(out_dir / "page_metadata.json"),
        "transcript": str(out_dir / "transcript.txt"),
        "segments": str(out_dir / "segments.json"),
        "note_budget": str(out_dir / "note_budget.json"),
        "asset_manifest": str(manifest_path),
        "subtitle_source": "existing",
        "transcript_source": transcript_source,
        "warnings": ["已复用的证据包缺少完整转写"] if blocked else [],
        "blocked_stages": blocked,
        "reused_artifacts": list(CORE_FILES) + ["assets/asset_manifest.json"],
    }


def download_with_cli(url: str, out_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    executable = shutil.which("yt-dlp")
    if not executable:
        raise TKNoteError("缺少 yt-dlp；请运行 pip install yt-dlp")
    command = [
        executable,
        "--dump-single-json",
        "--no-simulate",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--socket-timeout",
        "30",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "all",
        "--sub-format",
        "srt/vtt/best",
        "-f",
        "bv*[height<=1080]+ba/b[height<=1080]/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(out_dir / "download.%(ext)s"),
    ]
    if command_exists("ffmpeg"):
        command.extend(("--convert-subs", "srt"))
    if browser_impersonation_available():
        command.extend(("--impersonate", "chrome"))
    if args.cookies_from_browser:
        command.extend(("--cookies-from-browser", args.cookies_from_browser))
    if args.proxy:
        command.extend(("--proxy", args.proxy))
    command.append(url)
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if completed.returncode != 0:
        secrets = [args.proxy or "", os.environ.get("TIKTOK_MS_TOKEN", "")]
        detail = redact_text(completed.stderr or completed.stdout or "unknown yt-dlp error", secrets)
        raise TKNoteError(f"TikTok 下载失败：{detail[-500:]}")
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise TKNoteError("yt-dlp CLI 下载完成但没有返回有效元数据")


def download_video(url: str, out_dir: Path, args: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    emit_progress("download", "running", message="正在提取 TikTok 视频、元数据和可用字幕")
    clean_download_workfiles(out_dir)
    failures: list[str] = []

    # Scraper7 sometimes supplies a real, short-lived media transport URL with
    # the search result. Consume it only in memory and never persist it.
    media_hint = str(os.environ.get("VIRALX_TK_MEDIA_URL") or "").strip()
    if media_hint:
        try:
            candidate = download_media_transport(media_hint, url, out_dir, args, label="Scraper7 媒体地址")
            final_path = finalize_download(candidate, out_dir)
            info = fallback_info(url, extractor="Scraper7 transport")
            emit_progress(
                "download", "completed", video_file=str(final_path),
                size_bytes=final_path.stat().st_size, acquisition_route="scraper7-media",
            )
            return info, final_path
        except TKNoteError:
            failures.append("Scraper7 临时媒体地址不可用")
            emit_progress("download", "warning", message="Scraper7 临时媒体地址不可用，正在尝试 TK Note 解析")

    try:
        import yt_dlp
    except Exception:
        yt_dlp = None

    out_template = str(out_dir / "download.%(ext)s")
    options: dict[str, Any] = {
        "outtmpl": out_template,
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "continuedl": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLogger(),
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["all"],
        "subtitlesformat": "srt/vtt/best",
    }
    if command_exists("ffmpeg"):
        options["convertsubtitles"] = "srt"
    if browser_impersonation_available():
        options["impersonate"] = browser_impersonation_target()
    if args.cookies_from_browser:
        options["cookiesfrombrowser"] = (args.cookies_from_browser,)
    if args.proxy:
        options["proxy"] = args.proxy

    try:
        if yt_dlp is None:
            info = download_with_cli(url, out_dir, args)
        else:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise TKNoteError("yt-dlp 未返回有效的视频元数据")
        candidates = media_files(out_dir)
        if not candidates:
            raise TKNoteError("yt-dlp 已结束但没有生成可用视频文件")
        final_path = finalize_download(candidates[0], out_dir)
        emit_progress(
            "download", "completed", video_file=str(final_path),
            size_bytes=final_path.stat().st_size, acquisition_route="yt-dlp",
        )
        return info, final_path
    except TKNoteError:
        failures.append("yt-dlp 解析失败")
    except Exception as exc:
        failures.append(f"yt-dlp 解析失败（{type(exc).__name__}）")

    emit_progress("download", "warning", message="yt-dlp 被 TikTok 网页挑战拦截，正在启用真实 Chrome 兜底")
    try:
        page = browser_media_page(url, args)
        candidate = download_media_transport(
            str(page.get("media") or ""),
            url,
            out_dir,
            args,
            user_agent=str(page.get("userAgent") or DEFAULT_BROWSER_UA),
            label="真实浏览器媒体地址",
        )
        final_path = finalize_download(candidate, out_dir)
        info = fallback_info(url, page, extractor="ViralX browser")
        emit_progress(
            "download", "completed", video_file=str(final_path),
            size_bytes=final_path.stat().st_size, acquisition_route="browser",
        )
        return info, final_path
    except TKNoteError as exc:
        failures.append(str(exc))

    summary = "；".join(failures[-3:])
    raise TKNoteError(
        "TikTok 原片采集失败："
        f"{summary}。请确认代理可用；若页面要求验证，可设置 VIRALX_TK_BROWSER_VISIBLE=1 后重试。"
    )


def extract_audio(video: Path, audio: Path) -> None:
    if not command_exists("ffmpeg"):
        raise TKNoteError("没有可用字幕且未安装 ffmpeg，无法提取音频进行本地 ASR")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio)]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, check=False)
    if completed.returncode != 0 or not audio.exists():
        raise TKNoteError(f"ffmpeg 音频提取失败：{completed.stderr[-300:]}")


def run_qwen(audio: Path, out_dir: Path, language: str, chunk_seconds: float) -> tuple[list[dict[str, Any]], str]:
    qwen_python = find_shared_qwen_python()
    if not qwen_python:
        raise TKNoteError("共享 Qwen3-ASR 环境不可用")
    result_path = out_dir / "qwen_asr.json"
    script_path = Path(__file__).with_name("run_qwen_asr.py")
    command = [
        str(qwen_python), str(script_path), "--audio", str(audio), "--out", str(result_path),
        "--language", "Chinese" if language == "auto" else language, "--chunk-seconds", str(chunk_seconds),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600, check=False)
    if completed.returncode != 0:
        raise TKNoteError(f"Qwen3-ASR 失败：{completed.stderr[-400:]}")
    payload = read_json(result_path, {}) or {}
    return payload.get("segments") or [], str(payload.get("text") or "").strip()


def run_whisper(audio: Path, out_dir: Path, language: str, model: str) -> tuple[list[dict[str, Any]], str]:
    whisper_python = find_shared_whisper_python()
    if not whisper_python:
        raise TKNoteError("共享 Whisper 环境不可用；请安装 openai-whisper 或设置 RIMAGINATION_WHISPER_PYTHON")
    command = [
        str(whisper_python), "-m", "whisper", str(audio), "--model", model, "--output_dir", str(out_dir),
        "--output_format", "json", "--verbose", "False",
    ]
    if language != "auto":
        command.extend(("--language", language))
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600, check=False)
    if completed.returncode != 0:
        raise TKNoteError(f"Whisper ASR 失败：{completed.stderr[-400:]}")
    payload = read_json(out_dir / f"{audio.stem}.json", {}) or {}
    segments = [
        {"start": item.get("start", 0), "end": item.get("end", 0), "text": str(item.get("text") or "").strip()}
        for item in payload.get("segments", []) if str(item.get("text") or "").strip()
    ]
    return segments, str(payload.get("text") or transcript_from_segments(segments)).strip()


def make_transcript(out_dir: Path, video: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], str, str, list[str]]:
    warnings: list[str] = []
    subtitles = subtitle_files(out_dir)
    if subtitles:
        selected = subtitles[0]
        segments = parse_subtitle(selected)
        text = transcript_from_segments(segments)
        if text:
            return segments, text, f"subtitle:{selected.name}", warnings
        warnings.append(f"字幕文件 {selected.name} 没有解析出有效文本")
    if args.asr_backend == "none":
        return [], "", "none", warnings + ["未发现可用字幕，且本次关闭了本地 ASR"]

    audio = out_dir / "audio_16k.wav"
    emit_progress("asr", "running", message="未发现可用字幕，准备本地 ASR")
    try:
        extract_audio(video, audio)
        backend = args.asr_backend
        if backend == "auto":
            backend = "qwen3-asr" if find_shared_qwen_python() else "whisper"
        if backend == "qwen3-asr":
            segments, text = run_qwen(audio, out_dir, args.language, args.qwen_chunk_seconds)
        elif backend == "whisper":
            segments, text = run_whisper(audio, out_dir, args.language, args.whisper_model)
        else:
            raise TKNoteError(f"不支持的 ASR 后端：{backend}")
        emit_progress("asr", "completed", backend=backend, transcript_chars=len(text))
        return segments, text, f"asr:{backend}", warnings
    except TKNoteError as exc:
        emit_progress("asr", "blocked", message=str(exc))
        warnings.append(str(exc))
        return [], "", "blocked", warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract TikTok video, safe metadata, subtitles/ASR, and reusable evidence assets.")
    parser.add_argument("source", help="TikTok URL or share text containing a TikTok URL")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--asr-backend", choices=["auto", "none", "qwen3-asr", "whisper"], default="auto")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--qwen-chunk-seconds", type=float, default=60.0)
    parser.add_argument("--cookies-from-browser", choices=["chrome", "edge", "firefox", "brave", "opera", "vivaldi"])
    parser.add_argument("--proxy")
    parser.add_argument(
        "--refresh-derived",
        action="store_true",
        help="Keep the verified source video and rebuild transcript/evidence outputs.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        url = validate_tiktok_url(args.source)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        existing_url = source_identity(args.out_dir)
        has_existing_video = (args.out_dir / "source.mp4").is_file() and (args.out_dir / "source.mp4").stat().st_size > 0
        if reusable(args.out_dir, url) and not args.force and not args.refresh_derived:
            emit_progress("inspect", "reused", message="核心资产完整，跳过下载和 ASR")
            print(json.dumps(existing_result(args.out_dir), ensure_ascii=False))
            return 0

        if has_existing_video and existing_url and existing_url != url and not args.force:
            raise TKNoteError("输出目录已属于另一条 TikTok 来源；请更换目录，或明确使用 --force 覆盖")

        reused_artifacts: list[str] = []
        acquisition_warnings: list[str] = []
        if has_existing_video and existing_url == url and not args.force:
            video = args.out_dir / "source.mp4"
            metadata = read_json(args.out_dir / "metadata.json", {}) or {}
            reused_artifacts.extend(("source.mp4", "metadata.json"))
            message = (
                "保留已校验原片，只刷新字幕、ASR 与证据资产"
                if args.refresh_derived
                else "原视频与元数据已存在，只补齐缺失的下游资产"
            )
            emit_progress("download", "reused", message=message)
        else:
            try:
                info, video = download_video(url, args.out_dir, args)
                metadata = normalize_metadata(info, url)
                write_json(args.out_dir / "page_metadata.json", safe_page_metadata(info, url))
            except TKNoteError as exc:
                # A forced refresh is transactional: never destroy a previously
                # verified source file because TikTok changed its challenge.
                if has_existing_video and existing_url == url:
                    video = args.out_dir / "source.mp4"
                    metadata = read_json(args.out_dir / "metadata.json", {}) or {}
                    acquisition_warnings.append("原片刷新受阻，已继续复用此前校验通过的本地证据")
                    reused_artifacts.extend(("source.mp4", "metadata.json"))
                    emit_progress(
                        "download", "reused",
                        message="TikTok 当前阻止重新下载；旧原片仍有效，已安全复用",
                    )
                else:
                    raise exc

        transcript_path = args.out_dir / "transcript.txt"
        segments_path = args.out_dir / "segments.json"
        transcript_fresh = (
            transcript_path.is_file()
            and segments_path.is_file()
            and transcript_path.stat().st_mtime >= video.stat().st_mtime
            and not args.force
            and not args.refresh_derived
        )
        if transcript_fresh:
            transcript = transcript_path.read_text(encoding="utf-8", errors="replace").strip()
            segments = read_json(segments_path, []) or []
            transcript_source = str(metadata.get("transcript_source") or "existing")
            warnings = []
            reused_artifacts.extend(("transcript.txt", "segments.json"))
            emit_progress("asr", "reused", message="转写资产新于原视频，跳过字幕解析和 ASR")
        else:
            segments, transcript, transcript_source, warnings = make_transcript(args.out_dir, video, args)
        warnings = acquisition_warnings + warnings
        metadata["transcript_source"] = transcript_source
        write_json(args.out_dir / "metadata.json", metadata)
        write_json(args.out_dir / "segments.json", segments)
        (args.out_dir / "transcript.txt").write_text(transcript + ("\n" if transcript else ""), encoding="utf-8")
        (args.out_dir / "transcript.cleaned.md").write_text(
            render_transcript_markdown(metadata, transcript, transcript_source), encoding="utf-8"
        )
        budget = compute_note_budget(args.out_dir)
        manifest = build_asset_manifest(args.out_dir)
        blocked = ["transcript"] if transcript_source in {"blocked", "none"} else []
        if video.stat().st_size > 200 * 1024 * 1024:
            warnings.append("视频超过 LibTV 200MB 上传上限，需要压缩后再拉片")
            blocked.append("libtv_upload_size")
        result = {
            "status": "partial" if blocked else "success",
            "source_url": url,
            "video_id": metadata.get("video_id", ""),
            "video_file": str(video),
            "video_size_bytes": video.stat().st_size,
            "metadata": str(args.out_dir / "metadata.json"),
            "page_metadata": str(args.out_dir / "page_metadata.json"),
            "transcript": str(args.out_dir / "transcript.txt"),
            "segments": str(args.out_dir / "segments.json"),
            "note_budget": str(args.out_dir / "note_budget.json"),
            "asset_manifest": str(args.out_dir / "assets" / "asset_manifest.json"),
            "subtitle_source": transcript_source if transcript_source.startswith("subtitle:") else None,
            "transcript_source": transcript_source,
            "visual_dependency": budget.get("visual_dependency", {}),
            "warnings": warnings,
            "blocked_stages": blocked,
            "reused_artifacts": reused_artifacts,
        }
        emit_progress("complete", result["status"], video_id=result["video_id"], blocked_stages=blocked)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except TKNoteError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
