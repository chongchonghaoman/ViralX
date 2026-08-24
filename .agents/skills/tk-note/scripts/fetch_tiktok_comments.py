#!/usr/bin/env python3
"""Fetch a bounded TikTok comment sample with checkpoint and coverage metadata."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

from _common import TKNoteError, emit_progress, read_json, validate_tiktok_url, write_json


def user_value(user: Any, name: str, default: Any = "") -> Any:
    if isinstance(user, dict):
        return user.get(name, default)
    return getattr(user, name, default)


def normalize_comment(comment: Any, parent_id: str | None = None) -> dict[str, Any]:
    raw = getattr(comment, "as_dict", {}) or {}
    author = getattr(comment, "author", None)
    raw_user = raw.get("user", {}) if isinstance(raw, dict) else {}
    return {
        "comment_id": str(getattr(comment, "id", None) or raw.get("cid") or ""),
        "parent_id": parent_id,
        "is_reply": bool(parent_id),
        "text": str(getattr(comment, "text", None) or raw.get("text") or "").strip(),
        "like_count": int(getattr(comment, "likes_count", None) or raw.get("digg_count") or 0),
        "reply_count_reported": int(raw.get("reply_comment_total") or 0),
        "created_at": raw.get("create_time"),
        "author": str(user_value(author, "username", None) or raw_user.get("unique_id") or ""),
        "author_display_name": str(raw_user.get("nickname") or ""),
        "author_verified": bool(raw_user.get("custom_verify") or raw_user.get("enterprise_verify_reason")),
    }


def coverage_payload(rows: list[dict[str, Any]], requested: int, total_reported: int, full: bool) -> dict[str, Any]:
    main_count = sum(1 for row in rows if not row.get("is_reply"))
    reply_count = len(rows) - main_count
    return {
        "requested_main_comments": requested,
        "visible_rows": len(rows),
        "main_comment_count": main_count,
        "reply_count": reply_count,
        "total_reported": total_reported or None,
        "reported_gap": max((total_reported or 0) - main_count, 0) if total_reported else None,
        "is_sample": not full or (bool(total_reported) and main_count < total_reported),
        "scope_note": "这是当前会话可见评论的有界样本，不代表完整评论区或总体舆论。",
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else [
        "comment_id", "parent_id", "is_reply", "text", "like_count", "reply_count_reported",
        "created_at", "author", "author_display_name", "author_verified",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


async def collect(args: argparse.Namespace) -> dict[str, Any]:
    try:
        from TikTokApi import TikTokApi
    except Exception as exc:
        raise TKNoteError("评论路线缺少 TikTokApi；运行 pip install TikTokApi 并安装 Playwright 浏览器") from exc

    url = validate_tiktok_url(args.source)
    metadata = read_json(args.out_dir / "metadata.json", {}) or {}
    video_id = str(metadata.get("video_id") or "video")
    requested = args.main_count if not args.full else max(args.main_count, args.full_count)
    ms_token = os.environ.get("TIKTOK_MS_TOKEN")
    session_options: dict[str, Any] = {
        "num_sessions": 1,
        "sleep_after": 3,
        "browser": os.environ.get("TIKTOK_BROWSER", "chromium"),
        "headless": not args.headful,
    }
    if ms_token:
        session_options["ms_tokens"] = [ms_token]
    if args.proxy:
        session_options["proxies"] = [args.proxy]

    rows: list[dict[str, Any]] = []
    comments: list[Any] = []
    emit_progress("comments", "running", requested=requested)
    try:
        async with TikTokApi() as api:
            await api.create_sessions(**session_options)
            video = api.video(url=url)
            async for comment in video.comments(count=requested):
                comments.append(comment)
                rows.append(normalize_comment(comment))
                if len(comments) % 20 == 0:
                    emit_progress("comments", "running", main_comments=len(comments))

            basename = f"tiktok_comments_{video_id}_{'full' if args.full else 'sample'}"
            checkpoint = args.out_dir / f"{basename}_main_only.json"
            checkpoint_payload = {
                "schema": "tk-note-comments-v1",
                "source_url": url,
                "video_id": video_id,
                "checkpoint": "main_only",
                "rows": rows,
                "coverage": coverage_payload(rows, requested, int(metadata.get("comment_count") or 0), args.full),
            }
            write_json(checkpoint, checkpoint_payload)
            emit_progress("comments", "checkpoint", path=str(checkpoint), main_comments=len(comments))

            if not args.no_replies:
                for index, comment in enumerate(comments, start=1):
                    reported = int((getattr(comment, "as_dict", {}) or {}).get("reply_comment_total") or 0)
                    if reported <= 0:
                        continue
                    try:
                        async for reply in comment.replies(count=min(reported, args.reply_count)):
                            rows.append(normalize_comment(reply, parent_id=str(getattr(comment, "id", ""))))
                    except Exception as exc:
                        emit_progress("comments", "warning", message=f"第 {index} 条主评论回复抓取失败：{type(exc).__name__}")
    except Exception as exc:
        raise TKNoteError(
            "TikTok 评论抓取被阻止；保留已下载视频并继续 LibTV。可尝试 TIKTOK_MS_TOKEN、非无头浏览器或用户授权代理。"
        ) from exc

    basename = f"tiktok_comments_{video_id}_{'full' if args.full else 'sample'}"
    json_path = args.out_dir / f"{basename}.json"
    csv_path = args.out_dir / f"{basename}.csv"
    coverage = coverage_payload(rows, requested, int(metadata.get("comment_count") or 0), args.full)
    payload = {
        "schema": "tk-note-comments-v1",
        "source_url": url,
        "video_id": video_id,
        "rows": rows,
        "row_count": len(rows),
        "coverage": coverage,
    }
    write_json(json_path, payload)
    write_csv(csv_path, rows)
    emit_progress("comments", "completed", rows=len(rows), is_sample=coverage["is_sample"])
    return {"status": "success", "json": str(json_path), "csv": str(csv_path), "coverage": coverage}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch a bounded TikTok comment sample with coverage metadata.")
    parser.add_argument("source")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--main-count", type=int, default=100)
    parser.add_argument("--reply-count", type=int, default=50)
    parser.add_argument("--full-count", type=int, default=1000)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--no-replies", action="store_true")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--proxy")
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = asyncio.run(collect(args))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except TKNoteError as exc:
        print(json.dumps({"status": "blocked", "stage": "comments", "message": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
