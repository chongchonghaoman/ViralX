"""Persistent, server-owned checkpoints for evidence-first analysis recovery."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any


TASK_SCHEMA = "viralx.analysis_task.v1"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
PUBLIC_VIDEO_FIELDS = {
    "video_id", "title", "author", "duration", "likes", "comments", "shares", "views",
    "hashtags", "comments_data", "source_url", "canonical_url", "web_url", "url",
    "ai_analysis", "remake_script", "analysis_provider", "pipeline_stage", "pipeline_status",
    "evidence_status", "evidence_bundle", "shot_provider", "shot_model", "shot_status",
    "shot_evidence_quality", "shot_block_reason", "fallback_used", "fallback_chain",
    "model_status", "model_error_code", "model_grounding_error", "acquisition_provider",
    "tk_note_status", "video_ingest_status", "tk_note_reused", "video_ingest_reused",
}


def _utc_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    """Round-trip through JSON so task records cannot contain arbitrary objects."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class CheckpointStore:
    def __init__(self, cache_root: str | Path, retention_hours: int = 24):
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.root = self.cache_root / ".viralx-tasks"
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = max(1, int(retention_hours)) * 3600
        self._lock = threading.RLock()

    def _path(self, task_id: str) -> Path:
        if not TASK_ID_RE.fullmatch(str(task_id or "")):
            raise ValueError("invalid task id")
        return self.root / f"{task_id}.json"

    def _write(self, record: dict[str, Any]) -> None:
        target = self._path(record["task_id"])
        temporary = target.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)

    def create_final_checkpoint(self, video: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        task_id = secrets.token_urlsafe(24)
        safe_video = {
            key: _json_value(value)
            for key, value in video.items()
            if key in PUBLIC_VIDEO_FIELDS
        }
        record = {
            "schema": TASK_SCHEMA,
            "task_id": task_id,
            "created_at": _utc_iso(now),
            "updated_at": _utc_iso(now),
            "expires_at": _utc_iso(now + self.retention_seconds),
            "expires_epoch": now + self.retention_seconds,
            "status": "ready",
            "resumable_stage": "final-analysis",
            "retry_scope": "model-only",
            "video": safe_video,
            "internal": {
                "evidence_bundle_path": str(video.get("evidence_bundle_path") or ""),
                "shot_evidence_path": str(video.get("shot_evidence_path") or ""),
                "raw_model_report_path": str(video.get("raw_model_report_path") or ""),
            },
        }
        self._write(record)
        return self.public(record)

    def load(self, task_id: str) -> dict[str, Any]:
        path = self._path(task_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise KeyError(task_id) from exc
        if record.get("schema") != TASK_SCHEMA or record.get("task_id") != task_id:
            raise ValueError("invalid task record")
        if float(record.get("expires_epoch") or 0) <= time.time():
            try:
                path.unlink()
            except OSError:
                pass
            raise KeyError(task_id)
        return record

    def update(self, task_id: str, *, status: str, video: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self.load(task_id)
        record["status"] = status
        record["updated_at"] = _utc_iso(time.time())
        if video is not None:
            record["video"] = {
                key: _json_value(value)
                for key, value in video.items()
                if key in PUBLIC_VIDEO_FIELDS
            }
        self._write(record)
        return self.public(record)

    @staticmethod
    def public(record: dict[str, Any]) -> dict[str, Any]:
        video = deepcopy(record.get("video") or {})
        return {
            "task_id": record.get("task_id", ""),
            "status": record.get("status", "unknown"),
            "resumable_stage": record.get("resumable_stage", ""),
            "retry_scope": record.get("retry_scope", ""),
            "created_at": record.get("created_at", ""),
            "updated_at": record.get("updated_at", ""),
            "expires_at": record.get("expires_at", ""),
            "video": video,
            "artifacts": {
                "evidence_bundle": bool(video.get("evidence_bundle")),
                "shot_evidence": bool((video.get("evidence_bundle") or {}).get("shot_evidence")),
                "final_report": video.get("pipeline_status") == "completed",
            },
        }
