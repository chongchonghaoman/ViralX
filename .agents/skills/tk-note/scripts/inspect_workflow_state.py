#!/usr/bin/env python3
"""Inspect reusable TK Note artifacts and recommend only missing work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import read_json


ARTIFACTS = {
    "video": "source.mp4",
    "metadata": "metadata.json",
    "page_metadata": "page_metadata.json",
    "transcript": "transcript.txt",
    "segments": "segments.json",
    "note_budget": "note_budget.json",
    "analysis_plan": "analysis_plan.json",
    "learning_note": "learning_note.md",
    "note_score": "note_score.json",
    "asset_manifest": "assets/asset_manifest.json",
}


def file_info(path: Path) -> dict:
    return {
        "exists": path.is_file(),
        "path": str(path),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "mtime": path.stat().st_mtime if path.is_file() else None,
    }


def inspect(out_dir: Path, mode: str) -> dict:
    files = {name: file_info(out_dir / relative) for name, relative in ARTIFACTS.items()}
    comment_files = sorted(out_dir.glob("tiktok_comments_*.json"))
    files["comments"] = {
        "exists": bool(comment_files),
        "paths": [str(path) for path in comment_files],
        "size_bytes": sum(path.stat().st_size for path in comment_files),
    }
    reusable = [name for name, info in files.items() if info.get("exists")]
    next_steps: list[str] = []
    avoid: list[str] = []
    video_ready = files["video"]["exists"] and files["video"]["size_bytes"] > 0
    transcript_ready = files["transcript"]["exists"] and files["segments"]["exists"]
    if not video_ready:
        next_steps.append("运行 extract_tiktok_text.py 下载视频和安全元数据")
    else:
        avoid.append("source.mp4 已存在；除非来源改变或文件损坏，不要重复下载")
    if not transcript_ready:
        next_steps.append("复用已下载视频补字幕或本地 ASR；不要重下视频")
    else:
        avoid.append("transcript.txt 与 segments.json 已存在；不要重复 ASR")
    if mode == "comment-insight" and not files["comments"]["exists"]:
        next_steps.append("运行 fetch_tiktok_comments.py 获取有覆盖说明的评论样本")
    if not files["note_budget"]["exists"]:
        next_steps.append("运行 compute_note_budget.py")
    if not files["asset_manifest"]["exists"]:
        next_steps.append("运行 archive_tk_note_assets.py")
    budget = read_json(out_dir / "note_budget.json", {}) or {}
    visual = budget.get("visual_dependency", {}) if isinstance(budget, dict) else {}
    if visual.get("needs_visual_review"):
        next_steps.append("转写密度不足：交给 LibTV 或补关键帧/OCR 后再做完整画面结论")
    dependencies = [
        out_dir / "metadata.json",
        out_dir / "transcript.txt",
        out_dir / "segments.json",
        *comment_files,
    ]
    newest_dependency = max((path.stat().st_mtime for path in dependencies if path.exists()), default=0)
    stale = {
        "note_budget": files["note_budget"]["exists"] and (files["note_budget"]["mtime"] or 0) < newest_dependency,
        "asset_manifest": files["asset_manifest"]["exists"] and (files["asset_manifest"]["mtime"] or 0) < newest_dependency,
        "note_score": files["note_score"]["exists"] and files["learning_note"]["exists"] and (files["note_score"]["mtime"] or 0) < (files["learning_note"]["mtime"] or 0),
    }
    if stale["note_budget"]:
        next_steps.append("原始证据比 note_budget.json 新，重新计算预算")
    if stale["asset_manifest"]:
        next_steps.append("原始证据比 manifest 新，重新归档 assets/")
    return {
        "schema": "tk-note-workflow-state-v1",
        "mode": mode,
        "out_dir": str(out_dir),
        "files": files,
        "stale": stale,
        "reusable_artifacts": reusable,
        "recommended_next_steps": list(dict.fromkeys(next_steps)),
        "avoid_rework": avoid,
        "force_rerun_when": [
            "来源 URL 或视频 ID 改变",
            "现有文件缺失、损坏或为空",
            "证据等级不足以回答用户的新问题",
            "用户明确要求重新下载或更高保真 ASR",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect TK Note workflow state before rerunning work.")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--mode", default="single-video-note")
    args = parser.parse_args()
    print(json.dumps(inspect(args.out_dir, args.mode), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
