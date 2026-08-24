#!/usr/bin/env python3
"""Offline regression tests for TK Note's DyNote-compatible contracts."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import _common as common
import create_analysis_plan as planner
import extract_tiktok_text as extractor
import inspect_workflow_state as workflow


def test_url_routing() -> None:
    assert common.validate_tiktok_url("看看 https://www.tiktok.com/@a/video/123") == "https://www.tiktok.com/@a/video/123"
    try:
        common.validate_tiktok_url("https://www.douyin.com/video/123")
    except common.TKNoteError as exc:
        assert "dy-note" in str(exc)
    else:
        raise AssertionError("Douyin URL should be rejected")


def test_subtitle_and_assets() -> None:
    sample = """1
00:00:00,000 --> 00:00:01,250
First line.

2
00:00:01,250 --> 00:00:03,000
第二句话。
"""
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        subtitle = out_dir / "download.en.srt"
        subtitle.write_text(sample, encoding="utf-8")
        segments = common.parse_subtitle(subtitle)
        assert len(segments) == 2
        assert segments[0]["end"] == 1.25
        transcript = common.transcript_from_segments(segments)
        assert "First line." in transcript and "第二句话。" in transcript
        (out_dir / "source.mp4").write_bytes(b"fake-video")
        metadata = {
            "schema": "tk-note-metadata-v1",
            "source_url": "https://www.tiktok.com/@a/video/123",
            "video_id": "123",
            "duration": 180,
            "like_count": 10000,
        }
        common.write_json(out_dir / "metadata.json", metadata)
        common.write_json(out_dir / "page_metadata.json", {"normalized": metadata})
        common.write_json(out_dir / "segments.json", segments)
        (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
        (out_dir / "transcript.cleaned.md").write_text("# transcript\n", encoding="utf-8")
        budget = common.compute_note_budget(out_dir)
        assert budget["recommended_note_chars_min"] >= 800
        manifest = common.build_asset_manifest(out_dir)
        assert manifest["schema"] == "tk-note-assets-v1"
        assert (out_dir / "assets" / "video" / "source.mp4").exists()
        assert "资产先行" in (out_dir / "assets" / "README.md").read_text(encoding="utf-8")


def test_redaction() -> None:
    raw = {
        "id": "123",
        "url": "https://signed.example/video",
        "http_headers": {"Cookie": "secret"},
        "nested": {"ms_token": "secret", "caption": "safe"},
    }
    safe = common.safe_value(raw)
    assert "url" not in safe and "http_headers" not in safe
    assert safe["nested"] == {"caption": "safe"}


def test_plan_and_workflow_reuse() -> None:
    plan = planner.build_plan("viral-analysis", "分析钩子和镜头", ["https://www.tiktok.com/@a/video/123"], "research-pass")
    assert plan["schema"] == "tk-note-analysis-plan-v1"
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        for name, content in {
            "source.mp4": b"video",
            "metadata.json": b"{}",
            "transcript.txt": b"hello",
            "segments.json": b"[]",
            "note_budget.json": json.dumps({"visual_dependency": {"risk": "low"}}).encode(),
        }.items():
            (out_dir / name).write_bytes(content)
        state = workflow.inspect(out_dir, "viral-analysis")
        assert "video" in state["reusable_artifacts"]
        assert any("下载" in item or "download" in item.lower() for item in state["avoid_rework"])


def test_reuse_is_bound_to_source_url() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        (out_dir / "source.mp4").write_bytes(b"video")
        common.write_json(out_dir / "metadata.json", {"source_url": "https://www.tiktok.com/@a/video/123"})
        (out_dir / "transcript.txt").write_text("hello", encoding="utf-8")
        common.write_json(out_dir / "segments.json", [])
        common.write_json(out_dir / "note_budget.json", {})
        assert extractor.reusable(out_dir, "https://www.tiktok.com/@a/video/123")
        assert not extractor.reusable(out_dir, "https://www.tiktok.com/@b/video/456")


def test_comment_sample_is_archived_with_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        payload = {
            "rows": [{"comment_id": "c1", "text": "Need this", "author": "viewer", "is_reply": False}],
            "coverage": {
                "visible_rows": 1,
                "main_comment_count": 1,
                "reply_count": 0,
                "total_reported": 50,
                "reported_gap": 49,
                "is_sample": True,
            },
        }
        common.write_json(out_dir / "tiktok_comments_123_sample.json", payload)
        manifest = common.build_asset_manifest(out_dir)
        assert manifest["artifacts"]["comments"]["summary"]["is_sample"] is True
        assert manifest["artifacts"]["comments"]["summary"]["reported_gap"] == 49
        assert "Need this" in (out_dir / "assets" / "comments" / "comments.text.md").read_text(encoding="utf-8")


def main() -> None:
    test_url_routing()
    test_subtitle_and_assets()
    test_redaction()
    test_plan_and_workflow_reuse()
    test_reuse_is_bound_to_source_url()
    test_comment_sample_is_archived_with_coverage()
    print("selftest: ok")


if __name__ == "__main__":
    main()
