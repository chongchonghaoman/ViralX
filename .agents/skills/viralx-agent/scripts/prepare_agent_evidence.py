#!/usr/bin/env python3
"""Prepare local, timestamped evidence for the active Codex model.

This program performs acquisition and deterministic media processing only. It
does not call a model API and never reads model API credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SCHEMA = "viralx.agent-evidence.v1"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


class PreparationError(RuntimeError):
    pass


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def canonical_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PreparationError("Source is neither a readable local video nor an HTTP(S) URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def safe_slug(source: str) -> str:
    match = re.search(r"/video/(\d+)", source)
    if match:
        return match.group(1)
    path = Path(source)
    if path.exists():
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-.") or "local-video"
        digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
        return f"{base[:48]}-{digest}"
    return f"url-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"


def locate_tk_note_script() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("VIRALX_TK_NOTE_SCRIPT", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path(__file__).resolve().parents[2] / "tk-note" / "scripts" / "extract_tiktok_text.py")
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        candidates.append(Path(codex_home).expanduser() / "skills" / "tk-note" / "scripts" / "extract_tiktok_text.py")
    user_profile = os.environ.get("USERPROFILE", "").strip()
    if user_profile:
        candidates.append(Path(user_profile) / ".codex" / "skills" / "tk-note" / "scripts" / "extract_tiktok_text.py")
    candidates.append(Path.home() / ".codex" / "skills" / "tk-note" / "scripts" / "extract_tiktok_text.py")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise PreparationError("TK Note extractor not found; install .agents/skills/tk-note or set VIRALX_TK_NOTE_SCRIPT")


def parse_last_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise PreparationError("TK Note did not return its machine-readable result")


def acquire_url(source: str, task_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    script = locate_tk_note_script()
    command = [
        sys.executable,
        str(script),
        source,
        "--out-dir",
        str(task_dir),
        "--asr-backend",
        args.asr_backend,
        "--language",
        args.language,
    ]
    if args.cookies_from_browser:
        command.extend(["--cookies-from-browser", args.cookies_from_browser])
    if args.proxy:
        command.extend(["--proxy", args.proxy])
    if args.force:
        command.append("--force")
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = parse_last_json(completed.stdout)
    if completed.returncode != 0 or payload.get("status") == "error":
        message = str(payload.get("message") or "TK Note acquisition failed")
        raise PreparationError(message[:600])
    return payload


def read_json(path: Path | None, fallback: Any) -> Any:
    if not path or not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def existing_path(value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    return path.resolve() if path.is_file() else None


def local_assets(source_path: Path, task_dir: Path) -> dict[str, Any]:
    parent = source_path.parent
    metadata = next((p for p in (parent / "metadata.json", parent / "page_metadata.json") if p.is_file()), None)
    transcript = parent / "transcript.txt"
    segments = parent / "segments.json"
    asset_manifest = parent / "assets" / "asset_manifest.json"
    return {
        "status": "local",
        "source_url": "",
        "video_id": "",
        "video_file": str(source_path.resolve()),
        "metadata": str(metadata.resolve()) if metadata else "",
        "transcript": str(transcript.resolve()) if transcript.is_file() else "",
        "segments": str(segments.resolve()) if segments.is_file() else "",
        "asset_manifest": str(asset_manifest.resolve()) if asset_manifest.is_file() else "",
        "warnings": ["Local video has no TK Note sidecar transcript"] if not transcript.is_file() else [],
        "blocked_stages": ["transcript"] if not transcript.is_file() else [],
        "task_dir": str(task_dir.resolve()),
    }


def require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise PreparationError(f"{name} was not found on PATH")
    return binary


def probe_duration(video: Path) -> float:
    ffprobe = require_binary("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise PreparationError("ffprobe could not read the video")
    try:
        duration = float(json.loads(completed.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PreparationError("ffprobe did not return a valid duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise PreparationError("Video duration is invalid")
    return duration


def adaptive_frame_times(duration: float, max_frames: int = 36) -> list[float]:
    if duration <= 0 or max_frames < 1:
        return []
    start = 0.0 if duration < 0.3 else 0.1
    end = max(start, duration - 0.1)
    if max_frames == 1 or end <= start:
        return [round(min(duration / 2.0, end), 3)]
    target_gap = 1.0 if duration <= 20 else 2.0 if duration <= 90 else 4.0
    desired = max(2, int(math.ceil((end - start) / target_gap)) + 1)
    count = min(max_frames, desired)
    if count == 2:
        return [round(start, 3), round(end, 3)]
    step = (end - start) / (count - 1)
    return [round(start + step * index, 3) for index in range(count)]


def timestamp_label(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    minutes, remainder = divmod(total_ms, 60_000)
    secs, millis = divmod(remainder, 1000)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def frame_filename(index: int, seconds: float) -> str:
    safe_time = timestamp_label(seconds).replace(":", "-").replace(".", "-")
    return f"F{index:03d}_{safe_time}.jpg"


def frame_luma(ffmpeg: str, image: Path) -> float | None:
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        str(image),
        "-vf",
        "signalstats,metadata=print",
        "-frames:v",
        "1",
        "-f",
        "null",
        "-",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    match = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", completed.stderr)
    return float(match.group(1)) if match else None


def extract_frames(video: Path, frame_dir: Path, times: list[float]) -> list[dict[str, Any]]:
    ffmpeg = require_binary("ffmpeg")
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    for index, target_seconds in enumerate(times, start=1):
        output: Path | None = None
        seconds = target_seconds
        for rewind in (0.0, 0.75, 1.5, 3.0):
            candidate_seconds = round(max(0.0, target_seconds - rewind), 3)
            candidate_output = frame_dir / frame_filename(index, candidate_seconds)
            command = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{candidate_seconds:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(1280,iw)':-2",
                "-q:v",
                "3",
                str(candidate_output),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if completed.returncode != 0 or not candidate_output.is_file() or candidate_output.stat().st_size == 0:
                continue
            output = candidate_output
            seconds = candidate_seconds
            luma = frame_luma(ffmpeg, candidate_output)
            if luma is None or luma > 2.0 or rewind == 3.0:
                break
            candidate_output.unlink(missing_ok=True)
            output = None
        if output is None:
            raise PreparationError(f"ffmpeg failed to extract frame F{index:03d}")
        label = timestamp_label(seconds)
        frames.append(
            {
                "id": f"F{index:03d}",
                "timestamp_seconds": seconds,
                "timestamp": label,
                "citation": f"[FRAME:F{index:03d}@{label}]",
                "path": str(output.resolve()),
            }
        )
    return frames


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def comments_available(asset_manifest: Path | None) -> bool:
    payload = read_json(asset_manifest, {})
    artifacts = payload.get("artifacts", {}) if isinstance(payload, dict) else {}
    comments = artifacts.get("comments") if isinstance(artifacts, dict) else None
    if isinstance(comments, dict):
        return bool(comments.get("path") or comments.get("source"))
    if isinstance(comments, list):
        return bool(comments)
    return False


def write_brief(path: Path, manifest: dict[str, Any]) -> None:
    evidence = manifest["evidence"]
    coverage = manifest["coverage"]
    lines = [
        "# ViralX Agent evidence brief",
        "",
        f"- Manifest: `{path.with_name('manifest.json').resolve()}`",
        f"- Source video: `{manifest['source']['video_path']}`",
        f"- Duration: {coverage['duration_seconds']:.3f}s",
        f"- Frames: {coverage['frame_count']} (maximum observed gap {coverage['max_gap_seconds']:.3f}s)",
        f"- Frame coverage limited: {str(coverage['coverage_limited']).lower()}",
        f"- Metadata: `{evidence.get('metadata_path') or 'unavailable'}`",
        f"- Transcript: `{evidence.get('transcript_path') or 'unavailable'}`",
        f"- Segments: `{evidence.get('segments_path') or 'unavailable'}`",
        f"- TK Note asset manifest: `{evidence.get('asset_manifest_path') or 'unavailable'}`",
        f"- Comments collected: {str(evidence['comments_available']).lower()}",
        "",
        "Inspect every frame listed in manifest.json before writing report.md. Use each frame's exact citation label.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="TikTok URL or path to a local video")
    parser.add_argument("--out-dir", type=Path, required=True, help="Root directory for generated evidence")
    parser.add_argument("--max-frames", type=int, default=36, choices=range(1, 49), metavar="1-48")
    parser.add_argument("--asr-backend", choices=["auto", "none", "qwen3-asr", "whisper"], default="auto")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--cookies-from-browser", choices=["chrome", "edge", "firefox", "brave", "opera", "vivaldi"])
    parser.add_argument("--proxy")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        local_candidate = Path(args.source).expanduser()
        is_local = local_candidate.is_file()
        if is_local:
            source_path = local_candidate.resolve()
            if source_path.suffix.lower() not in VIDEO_SUFFIXES:
                raise PreparationError("Local source does not have a supported video extension")
            source_identity = str(source_path)
        else:
            source_identity = canonical_url(args.source)

        task_dir = args.out_dir.expanduser().resolve() / safe_slug(source_identity)
        task_dir.mkdir(parents=True, exist_ok=True)
        acquisition = local_assets(source_path, task_dir) if is_local else acquire_url(source_identity, task_dir, args)
        video = existing_path(acquisition.get("video_file"))
        if not video:
            raise PreparationError("Acquisition did not produce a readable source video")

        metadata = existing_path(acquisition.get("metadata"))
        transcript = existing_path(acquisition.get("transcript"))
        segments = existing_path(acquisition.get("segments"))
        asset_manifest = existing_path(acquisition.get("asset_manifest"))
        duration = probe_duration(video)
        times = adaptive_frame_times(duration, args.max_frames)
        agent_dir = task_dir / "agent-evidence"
        frames = extract_frames(video, agent_dir / "frames", times)
        gaps = [right["timestamp_seconds"] - left["timestamp_seconds"] for left, right in zip(frames, frames[1:])]
        max_gap = max(gaps, default=duration)
        target_gap = 1.0 if duration <= 20 else 2.0 if duration <= 90 else 4.0
        manifest_path = agent_dir / "manifest.json"
        brief_path = agent_dir / "evidence-brief.md"
        report_path = agent_dir / "report.md"
        manifest = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "kind": "local_file" if is_local else "tiktok_url",
                "canonical_url": "" if is_local else source_identity,
                "video_path": str(video),
                "video_sha256": sha256_file(video),
            },
            "evidence": {
                "metadata_path": str(metadata) if metadata else "",
                "transcript_path": str(transcript) if transcript else "",
                "segments_path": str(segments) if segments else "",
                "asset_manifest_path": str(asset_manifest) if asset_manifest else "",
                "transcript_available": bool(transcript and transcript.stat().st_size > 0),
                "comments_available": comments_available(asset_manifest),
                "warnings": [str(item)[:300] for item in acquisition.get("warnings", []) if item],
                "blocked_stages": [str(item)[:80] for item in acquisition.get("blocked_stages", []) if item],
            },
            "coverage": {
                "duration_seconds": round(duration, 3),
                "frame_count": len(frames),
                "max_gap_seconds": round(max_gap, 3),
                "target_gap_seconds": target_gap,
                "coverage_limited": max_gap > target_gap * 1.25,
                "sampling_note": "Timestamped still frames; not continuous video playback",
            },
            "frames": frames,
            "report_contract": {
                "output_path": str(report_path.resolve()),
                "visual_citation_format": "[FRAME:F001@00:00.100]",
                "metadata_citation_format": "[META:field]",
                "transcript_citation": "[TK:transcript]",
                "comments_citation": "[COMMENTS:sample] or [COMMENTS:unavailable]",
            },
            "model_policy": {
                "external_model_api_used": False,
                "synthesis_runtime": "active-agent-model",
                "model_api_credentials_read": False,
            },
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_brief(brief_path, manifest)
        emit(
            {
                "status": "success",
                "schema": SCHEMA,
                "task_dir": str(task_dir),
                "manifest": str(manifest_path.resolve()),
                "brief": str(brief_path.resolve()),
                "report": str(report_path.resolve()),
                "frame_count": len(frames),
                "external_model_api_used": False,
            }
        )
        return 0
    except (PreparationError, OSError) as exc:
        emit({"status": "error", "message": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
