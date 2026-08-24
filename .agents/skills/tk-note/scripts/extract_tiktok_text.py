#!/usr/bin/env python3
"""Extract a TikTok video into DyNote-compatible local evidence assets."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from _common import (
    TKNoteError,
    build_asset_manifest,
    command_exists,
    compute_note_budget,
    emit_progress,
    find_shared_qwen_python,
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
    try:
        import yt_dlp
    except Exception:
        yt_dlp = None

    emit_progress("download", "running", message="正在提取 TikTok 视频、元数据和可用字幕")
    clean_download_workfiles(out_dir)
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
    except TKNoteError:
        raise
    except Exception as exc:
        secrets = [args.proxy or "", os.environ.get("TIKTOK_MS_TOKEN", "")]
        raise TKNoteError(redact_text(f"TikTok 下载失败：{exc}", secrets)) from exc

    if not isinstance(info, dict):
        raise TKNoteError("yt-dlp 未返回有效的视频元数据")
    candidates = media_files(out_dir)
    if not candidates:
        raise TKNoteError("yt-dlp 已结束但没有生成可用视频文件")
    downloaded = candidates[0]
    final_path = out_dir / "source.mp4"
    if final_path.exists():
        final_path.unlink()
    shutil.move(str(downloaded), str(final_path))
    emit_progress("download", "completed", video_file=str(final_path), size_bytes=final_path.stat().st_size)
    return info, final_path


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
    if importlib.util.find_spec("whisper") is None:
        raise TKNoteError("当前 Python 环境未安装 Whisper")
    command = [
        sys.executable, "-m", "whisper", str(audio), "--model", model, "--output_dir", str(out_dir),
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
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        url = validate_tiktok_url(args.source)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        existing_url = source_identity(args.out_dir)
        has_existing_video = (args.out_dir / "source.mp4").is_file() and (args.out_dir / "source.mp4").stat().st_size > 0
        if reusable(args.out_dir, url) and not args.force:
            emit_progress("inspect", "reused", message="核心资产完整，跳过下载和 ASR")
            print(json.dumps(existing_result(args.out_dir), ensure_ascii=False))
            return 0

        if has_existing_video and existing_url and existing_url != url and not args.force:
            raise TKNoteError("输出目录已属于另一条 TikTok 来源；请更换目录，或明确使用 --force 覆盖")

        reused_artifacts: list[str] = []
        if has_existing_video and existing_url == url and not args.force:
            video = args.out_dir / "source.mp4"
            metadata = read_json(args.out_dir / "metadata.json", {}) or {}
            reused_artifacts.extend(("source.mp4", "metadata.json"))
            emit_progress("download", "reused", message="原视频与元数据已存在，只补齐缺失的下游资产")
        else:
            info, video = download_video(url, args.out_dir, args)
            metadata = normalize_metadata(info, url)
            write_json(args.out_dir / "page_metadata.json", safe_page_metadata(info, url))

        transcript_path = args.out_dir / "transcript.txt"
        segments_path = args.out_dir / "segments.json"
        transcript_fresh = (
            transcript_path.is_file()
            and segments_path.is_file()
            and transcript_path.stat().st_mtime >= video.stat().st_mtime
            and not args.force
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
