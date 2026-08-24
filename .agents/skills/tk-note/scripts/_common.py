#!/usr/bin/env python3
"""Shared, platform-safe helpers for TK Note."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vt.tiktok.com",
    "vm.tiktok.com",
}
SENSITIVE_KEYS = {
    "url",
    "manifest_url",
    "fragment_base_url",
    "download_url",
    "play_addr",
    "download_addr",
    "http_headers",
    "cookies",
    "cookie",
    "ms_token",
    "token",
    "authorization",
    "proxy",
    "formats",
    "requested_formats",
    "requested_downloads",
    "automatic_captions",
    "subtitles",
}
MEDIA_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}


class TKNoteError(RuntimeError):
    """Stable domain error safe to show to users."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(path.parent), prefix=path.name, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temp_name = handle.name
    Path(temp_name).replace(path)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def emit_progress(stage: str, status: str = "running", **details: Any) -> None:
    payload = {"stage": stage, "status": status, **details}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def extract_first_url(value: str) -> str:
    match = re.search(r"https?://[^\s]+", value or "")
    if not match:
        raise TKNoteError("未找到 TikTok HTTP(S) 链接")
    return match.group(0).rstrip("，。！？、,.;:!?)）]}")


def validate_tiktok_url(value: str) -> str:
    url = extract_first_url(value)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in TIKTOK_HOSTS and not host.endswith(".tiktok.com"):
        if host.endswith("douyin.com"):
            raise TKNoteError("这是国内抖音链接，请使用 dy-note")
        raise TKNoteError(f"TK Note 仅接受国际 TikTok 链接，当前域名：{host or 'unknown'}")
    return url


def infer_video_id(url: str, metadata: dict[str, Any] | None = None) -> str:
    if metadata:
        raw = metadata.get("id") or metadata.get("display_id")
        if raw:
            return re.sub(r"[^0-9A-Za-z_-]", "", str(raw))[:80]
    match = re.search(r"/video/(\d+)", url)
    if match:
        return match.group(1)
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def redact_text(value: str, secrets: Iterable[str] = ()) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    text = re.sub(r"(?i)(ms_token|cookie|authorization)=?[^\s&]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@", r"\1[REDACTED]@", text)
    return text


def safe_value(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    if lowered in SENSITIVE_KEYS or any(
        marker in lowered for marker in ("cookie", "token", "signature", "authorization", "play_addr", "download_addr")
    ):
        return None
    if isinstance(value, dict):
        cleaned = {}
        for child_key, child_value in value.items():
            safe = safe_value(child_value, str(child_key))
            if safe is not None:
                cleaned[str(child_key)] = safe
        return cleaned
    if isinstance(value, list):
        return [safe for item in value if (safe := safe_value(item, key)) is not None][:200]
    if isinstance(value, str) and re.search(
        r"(?i)(bytecdn|tiktokcdn|akamaized|mime_type=|x-expires=|x-signature=|signature=)", value
    ):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def normalize_metadata(info: dict[str, Any], source_url: str) -> dict[str, Any]:
    tags = info.get("tags") or info.get("hashtags") or []
    if isinstance(tags, str):
        tags = [item.lstrip("#") for item in re.findall(r"#[\w-]+", tags)]
    uploader = info.get("uploader") or info.get("creator") or info.get("channel") or info.get("uploader_id")
    result = {
        "schema": "tk-note-metadata-v1",
        "platform": "tiktok",
        "source_url": source_url,
        "video_id": infer_video_id(source_url, info),
        "title": info.get("title") or info.get("description") or "TikTok video",
        "description": info.get("description") or "",
        "author": uploader or "",
        "author_id": info.get("uploader_id") or info.get("channel_id") or "",
        "duration": info.get("duration") or 0,
        "timestamp": info.get("timestamp"),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count") or 0,
        "like_count": info.get("like_count") or 0,
        "comment_count": info.get("comment_count") or 0,
        "share_count": info.get("repost_count") or info.get("share_count") or 0,
        "hashtags": tags if isinstance(tags, list) else [],
        "language": info.get("language") or "",
        "extractor": info.get("extractor_key") or info.get("extractor") or "TikTok",
        "collected_at": utc_now(),
    }
    return safe_value(result)


def safe_page_metadata(info: dict[str, Any], source_url: str) -> dict[str, Any]:
    return {
        "schema": "tk-note-page-metadata-v1",
        "normalized": normalize_metadata(info, source_url),
        "available_subtitle_languages": sorted((info.get("subtitles") or {}).keys()),
        "available_auto_caption_languages": sorted((info.get("automatic_captions") or {}).keys()),
        "format_summary": {
            "ext": info.get("ext"),
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "filesize": info.get("filesize") or info.get("filesize_approx"),
        },
        "collected_at": utc_now(),
    }


def subtitle_files(out_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in out_dir.glob("download.*")
        if path.suffix.lower() in {".srt", ".vtt"} and path.is_file() and path.stat().st_size > 0
    )


def media_files(out_dir: Path) -> list[Path]:
    candidates = []
    for path in out_dir.glob("download.*"):
        if path.suffix.lower() in MEDIA_SUFFIXES and path.is_file() and path.stat().st_size > 0:
            candidates.append(path)
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


TIMECODE_RE = re.compile(
    r"(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})\s+-->\s+"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})"
)


def _seconds(match: re.Match[str], prefix: str) -> float:
    return (
        int(match.group(prefix + "h")) * 3600
        + int(match.group(prefix + "m")) * 60
        + int(match.group(prefix + "s"))
        + int(match.group(prefix + "ms")) / 1000
    )


def parse_subtitle(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"^WEBVTT.*?(?=\n\n|\r\n\r\n)", "", text, flags=re.S)
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        match = TIMECODE_RE.search(block)
        if not match:
            continue
        body = block[match.end() :]
        body = re.sub(r"<[^>]+>", "", body)
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        cleaned = " ".join(lines).strip()
        if cleaned:
            segments.append(
                {"start": round(_seconds(match, "s"), 3), "end": round(_seconds(match, "e"), 3), "text": cleaned}
            )
    return segments


def transcript_from_segments(segments: list[dict[str, Any]]) -> str:
    output: list[str] = []
    previous = ""
    for segment in segments:
        text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
        if text and text != previous:
            output.append(text)
            previous = text
    return "\n".join(output).strip()


def visible_text_chars(text: str) -> int:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return len(re.sub(r"\s+", "", text))


def compute_note_budget(out_dir: Path) -> dict[str, Any]:
    metadata = read_json(out_dir / "metadata.json", {}) or {}
    segments = read_json(out_dir / "segments.json", []) or []
    transcript = (out_dir / "transcript.txt").read_text(encoding="utf-8", errors="replace") if (out_dir / "transcript.txt").exists() else ""
    chars = visible_text_chars(transcript)
    duration = float(metadata.get("duration") or 0)
    if not duration and segments:
        duration = max(float(item.get("end") or 0) for item in segments if isinstance(item, dict))
    minutes = duration / 60 if duration else 0.0
    density = chars / minutes if minutes else None
    risk = "low"
    reasons: list[str] = []
    warnings: list[str] = []
    if duration >= 60 and chars == 0:
        risk = "high"
        reasons.append("no_transcript_text")
        warnings.append("视频有时长但没有字幕或 ASR 文本，不能把 caption 当完整内容。")
    elif minutes >= 3 and (chars <= 240 or (density is not None and density < 120)):
        risk = "high"
        reasons.append("low_transcript_density")
        warnings.append("长视频转写密度很低，详细理解需要 LibTV、关键帧或 OCR 视觉证据。")
    elif minutes >= 1 and density is not None and density < 180:
        risk = "medium"
        reasons.append("medium_low_transcript_density")
        warnings.append("转写文本偏少；快读可用，详细拆解需要视觉证据。")
    interactions = sum(float(metadata.get(key) or 0) for key in ("like_count", "comment_count", "share_count"))
    quality_multiplier = min(1.4, 0.9 + (0.5 if interactions >= 100000 else 0.3 if interactions >= 10000 else 0.1))
    base_min = max(800, min(45000, round(500 + minutes * 60 + chars * 0.08)))
    target_min = max(800, min(65000, round(base_min * quality_multiplier)))
    target_max = max(1200, min(90000, round(target_min * 1.45)))
    budget = {
        "schema": "tk-note-budget-v1",
        "content_type": "tiktok_video",
        "out_dir": str(out_dir),
        "duration_seconds": round(duration, 3),
        "duration_minutes": round(minutes, 3),
        "transcript_chars": chars,
        "segment_count": len(segments),
        "transcript_density_chars_per_minute": round(density, 3) if density is not None else None,
        "visual_dependency": {
            "risk": risk,
            "needs_visual_review": risk in {"medium", "high"},
            "reasons": reasons,
            "warnings": warnings,
            "hallucination_guard": "字幕或本地 ASR 是口述事实主干；LibTV、关键帧或 OCR 才能补足画面与内嵌文字。",
        },
        "evidence_warnings": warnings,
        "quality_multiplier": quality_multiplier,
        "recommended_note_chars_min": target_min,
        "recommended_note_chars_max": target_max,
        "quick_note_chars": max(600, round(target_min * 0.45)),
        "deep_note_chars": round(target_max * 1.55),
        "writing_guidance": "按现有证据写清核心观点、钩子、节奏和可迁移方法；缺少画面证据时不得补故事。",
        "generated_at": utc_now(),
    }
    write_json(out_dir / "note_budget.json", budget)
    return budget


def render_transcript_markdown(metadata: dict[str, Any], transcript: str, source: str) -> str:
    return (
        f"# TikTok 视频文本素材\n\n"
        f"- 来源：{metadata.get('source_url', '')}\n"
        f"- 作者：{metadata.get('author') or '未知'}\n"
        f"- 视频 ID：{metadata.get('video_id') or '未知'}\n"
        f"- 文本来源：{source}\n\n"
        f"## 转写正文\n\n{transcript or '（没有可用的字幕或 ASR 文本）'}\n"
    )


def copy_asset(source: Path, destination: Path) -> dict[str, Any] | None:
    if not source.exists() or not source.is_file():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return {"source": str(source), "path": str(destination), "size_bytes": destination.stat().st_size}


def build_asset_manifest(out_dir: Path) -> dict[str, Any]:
    assets_dir = out_dir / "assets"
    artifacts: dict[str, Any] = {}
    mapping = {
        "video": (out_dir / "source.mp4", assets_dir / "video" / "source.mp4"),
        "metadata": (out_dir / "metadata.json", assets_dir / "metadata" / "metadata.json"),
        "page_metadata": (out_dir / "page_metadata.json", assets_dir / "metadata" / "page_metadata.json"),
        "transcript": (out_dir / "transcript.txt", assets_dir / "transcripts" / "transcript.txt"),
        "segments": (out_dir / "segments.json", assets_dir / "transcripts" / "segments.json"),
        "transcript_markdown": (out_dir / "transcript.cleaned.md", assets_dir / "transcripts" / "transcript.cleaned.md"),
        "note_budget": (out_dir / "note_budget.json", assets_dir / "metadata" / "note_budget.json"),
    }
    for key, (source, destination) in mapping.items():
        item = copy_asset(source, destination)
        if item:
            artifacts[key] = item
    subtitles = []
    for subtitle in subtitle_files(out_dir):
        item = copy_asset(subtitle, assets_dir / "transcripts" / "source_subtitles" / subtitle.name)
        if item:
            subtitles.append(item)
    if subtitles:
        artifacts["source_subtitles"] = subtitles
    comment_files = sorted(
        out_dir.glob("tiktok_comments_*.json"),
        key=lambda path: (
            "_full.json" in path.name,
            "_sample.json" in path.name,
            "main_only" not in path.name,
            path.stat().st_mtime,
        ),
        reverse=True,
    )
    if comment_files:
        comment_source = comment_files[0]
        comment_payload = read_json(comment_source, {}) or {}
        rows = comment_payload.get("rows", []) if isinstance(comment_payload, dict) else []
        rows = [row for row in rows if isinstance(row, dict)]
        comment_dir = assets_dir / "comments"
        comment_json = copy_asset(comment_source, comment_dir / "comments.json")
        csv_source = comment_source.with_suffix(".csv")
        comment_csv = copy_asset(csv_source, comment_dir / "comments.csv")
        comment_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = comment_dir / "comments.rows.jsonl"
        jsonl_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        text_path = comment_dir / "comments.text.md"
        comment_lines = ["# TikTok 可见评论样本", ""]
        coverage = comment_payload.get("coverage", {}) if isinstance(comment_payload, dict) else {}
        comment_lines.extend(
            (
                f"- 可见行数：{coverage.get('visible_rows', len(rows))}",
                f"- 主评论：{coverage.get('main_comment_count', 0)}",
                f"- 回复：{coverage.get('reply_count', 0)}",
                f"- 是否样本：{'是' if coverage.get('is_sample', True) else '否'}",
                "",
            )
        )
        for row in rows:
            level = "回复" if row.get("is_reply") else "主评论"
            author = row.get("author_display_name") or row.get("author") or "未知用户"
            text = str(row.get("text") or "").strip()
            if text:
                comment_lines.append(f"- [{level}] {author}: {text}")
        text_path.write_text("\n".join(comment_lines) + "\n", encoding="utf-8")
        artifacts["comments"] = {
            "source": str(comment_source),
            "json": comment_json,
            "csv": comment_csv,
            "rows_jsonl": str(jsonl_path),
            "text_markdown": str(text_path),
            "summary": {
                "row_count": len(rows),
                "is_sample": bool(coverage.get("is_sample", True)),
                "total_reported": coverage.get("total_reported"),
                "reported_gap": coverage.get("reported_gap"),
            },
        }
    manifest = {
        "schema": "tk-note-assets-v1",
        "out_dir": str(out_dir),
        "generated_at": utc_now(),
        "artifacts": artifacts,
        "evidence_contract": {
            "factual_spine": ["transcript", "segments"],
            "visual_evidence": ["video"],
            "audience_signal": ["comments"],
            "rule": "Generate notes from these assets; never overwrite raw evidence with a summary.",
        },
    }
    write_json(assets_dir / "asset_manifest.json", manifest)
    (assets_dir / "README.md").write_text(
        "# TK Note 证据资产\n\n"
        "资产先行，笔记后置。`transcripts/` 是口述事实主干，`video/` 是视觉证据，"
        "`comments/` 仅代表当前会话可见样本；分析结果不能覆盖这些原始材料。\n",
        encoding="utf-8",
    )
    return manifest


def find_shared_qwen_python() -> Path | None:
    override = os.environ.get("RIMAGINATION_QWEN_PYTHON")
    candidates = [Path(override)] if override else []
    base = Path(os.environ.get("RIMAGINATION_NOTE_CACHE", Path.home() / ".cache" / "rimagination-notes"))
    candidates.extend((base / "qwen3-asr-venv" / "Scripts" / "python.exe", base / "qwen3-asr-venv" / "bin" / "python"))
    return next((path for path in candidates if path and path.is_file()), None)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None
