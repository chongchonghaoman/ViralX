"""Video acquisition layer for ViralX.

International TikTok URLs go through the vendored TK Note skill so download,
metadata, transcript, and provenance remain resumable. Other HTTP(S) video
URLs keep a small yt-dlp compatibility path (notably for Douyin links).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlparse


TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vt.tiktok.com", "vm.tiktok.com"}


class VideoIngestError(RuntimeError):
    """Stable acquisition error safe to return to the local ViralX UI."""


def is_tiktok_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in TIKTOK_HOSTS or host.endswith(".tiktok.com")


def _safe_cache_key(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]", "", str(value or ""))[:80]
    return cleaned or "video"


@dataclass
class VideoAsset:
    provider: str
    status: str
    video_file: str
    video_id: str
    source_url: str
    metadata_path: str = ""
    transcript_path: str = ""
    transcript_source: str = ""
    asset_manifest: str = ""
    warnings: List[str] = field(default_factory=list)
    blocked_stages: List[str] = field(default_factory=list)
    progress_events: List[Dict[str, object]] = field(default_factory=list)
    metadata: Dict[str, object] = field(default_factory=dict)

    def analysis_details(self) -> Dict[str, object]:
        prefix = "tk_note" if self.provider == "tk-note" else "video_ingest"
        return {
            "acquisition_provider": self.provider,
            f"{prefix}_status": self.status,
            f"{prefix}_transcript_source": self.transcript_source,
            f"{prefix}_asset_manifest": self.asset_manifest,
            f"{prefix}_warnings": self.warnings,
            f"{prefix}_blocked_stages": self.blocked_stages,
            f"{prefix}_reused": self.status == "reused",
        }

    def video_fields(self) -> Dict[str, object]:
        if not self.metadata:
            return {}
        fields = {
            "video_id": self.metadata.get("video_id"),
            "title": self.metadata.get("title"),
            "author": self.metadata.get("author"),
            "duration": self.metadata.get("duration"),
            "views": self.metadata.get("view_count"),
            "likes": self.metadata.get("like_count"),
            "comments": self.metadata.get("comment_count"),
            "shares": self.metadata.get("share_count"),
        }
        return {key: value for key, value in fields.items() if value not in (None, "")}


class TKNoteCollector:
    """Invoke the project-local TK Note skill and consume its JSON contract."""

    def __init__(
        self,
        cache_dir: Path,
        skill_dir: Optional[Path] = None,
        asr_backend: str = "auto",
        language: str = "auto",
        cookies_from_browser: str = "",
        proxy: str = "",
        timeout: float = 1800,
        runner: Optional[Callable[[List[str], float], subprocess.CompletedProcess]] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        configured_script = os.environ.get("VIRALX_TK_NOTE_SCRIPT", "")
        self.skill_dir = skill_dir or Path(__file__).parent / ".agents" / "skills" / "tk-note"
        self.script = (
            self.skill_dir / "scripts" / "extract_tiktok_text.py"
            if skill_dir is not None
            else Path(configured_script)
            if configured_script
            else self.skill_dir / "scripts" / "extract_tiktok_text.py"
        )
        self.asr_backend = asr_backend if asr_backend in {"auto", "none", "qwen3-asr", "whisper"} else "auto"
        self.language = language or "auto"
        self.cookies_from_browser = cookies_from_browser or ""
        self.proxy = proxy or ""
        self.timeout = max(float(timeout), 30)
        self._runner = runner

    def _run(self, command: List[str]) -> subprocess.CompletedProcess:
        if self._runner:
            return self._runner(command, self.timeout)
        try:
            return subprocess.run(
                command,
                cwd=str(Path(__file__).parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoIngestError("TK Note 采集超时；已完成的缓存资产仍会保留") from exc

    @staticmethod
    def _parse_progress(stderr: str) -> List[Dict[str, object]]:
        events: List[Dict[str, object]] = []
        for line in (stderr or "").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("stage"):
                events.append(payload)
        return events

    @staticmethod
    def _parse_result(stdout: str) -> Dict[str, object]:
        for line in reversed((stdout or "").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise VideoIngestError("TK Note 没有返回有效 JSON 结果")

    @staticmethod
    def _read_metadata(path_value: object) -> Dict[str, object]:
        if not path_value:
            return {}
        try:
            payload = json.loads(Path(str(path_value)).read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def collect(self, video_url: str, video_id: str, force: bool = False) -> VideoAsset:
        if not self.script.is_file():
            raise VideoIngestError(f"缺少项目内 TK Note 脚本：{self.script}")
        out_dir = self.cache_dir / _safe_cache_key(video_id)
        command = [
            sys.executable,
            str(self.script),
            video_url,
            "--out-dir",
            str(out_dir),
            "--asr-backend",
            self.asr_backend,
            "--language",
            self.language,
        ]
        if self.cookies_from_browser:
            command.extend(("--cookies-from-browser", self.cookies_from_browser))
        if self.proxy:
            command.extend(("--proxy", self.proxy))
        if force:
            command.append("--force")

        completed = self._run(command)
        progress = self._parse_progress(completed.stderr)
        payload = self._parse_result(completed.stdout)
        if completed.returncode != 0 or payload.get("status") == "error":
            message = str(payload.get("message") or "TK Note 无法下载当前 TikTok 视频")
            raise VideoIngestError(message)
        video_file = Path(str(payload.get("video_file") or ""))
        if not video_file.is_file() or video_file.stat().st_size <= 0:
            raise VideoIngestError("TK Note 返回成功但没有生成非空 source.mp4")

        metadata_path = str(payload.get("metadata") or "")
        return VideoAsset(
            provider="tk-note",
            status=str(payload.get("status") or "success"),
            video_file=str(video_file),
            video_id=str(payload.get("video_id") or video_id),
            source_url=str(payload.get("source_url") or video_url),
            metadata_path=metadata_path,
            transcript_path=str(payload.get("transcript") or ""),
            transcript_source=str(payload.get("transcript_source") or ""),
            asset_manifest=str(payload.get("asset_manifest") or ""),
            warnings=[str(item) for item in payload.get("warnings", [])],
            blocked_stages=[str(item) for item in payload.get("blocked_stages", [])],
            progress_events=progress,
            metadata=self._read_metadata(metadata_path),
        )


class GenericVideoDownloader:
    """Small yt-dlp compatibility route for non-TikTok links."""

    def __init__(self, output_dir: Optional[str] = None, timeout: float = 180):
        self.output_dir = Path(output_dir or Path(__file__).parent / "video_cache" / "generic")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = max(float(timeout), 30)

    def output_path(self, video_id: str) -> Path:
        return self.output_dir / f"{_safe_cache_key(video_id)}.mp4"

    def download(self, video_url: str, video_id: str, force: bool = False) -> Optional[str]:
        output_path = self.output_path(video_id)
        if output_path.is_file() and output_path.stat().st_size > 0 and not force:
            return str(output_path)
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--quiet",
            "--no-warnings",
            "--retries",
            "3",
            "--fragment-retries",
            "3",
            "-o",
            str(output_path),
            "--merge-output-format",
            "mp4",
            video_url,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None
        return str(output_path) if completed.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0 else None


class VideoAssetCollector:
    """Route URLs to TK Note or the generic compatibility downloader."""

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        tk_note_skill_dir: Optional[str] = None,
        tk_note_asr_backend: str = "auto",
        tk_note_language: str = "auto",
        tk_note_cookies_from_browser: str = "",
        tk_note_proxy: str = "",
        tk_note_timeout: float = 1800,
        tk_note_collector: Optional[TKNoteCollector] = None,
        generic_downloader: Optional[GenericVideoDownloader] = None,
    ):
        root = Path(cache_dir or Path(__file__).parent / "video_cache")
        if not root.is_absolute():
            root = Path(__file__).parent / root
        root.mkdir(parents=True, exist_ok=True)
        self.tk_note = tk_note_collector or TKNoteCollector(
            cache_dir=root / "tk-note",
            skill_dir=Path(tk_note_skill_dir) if tk_note_skill_dir else None,
            asr_backend=tk_note_asr_backend,
            language=tk_note_language,
            cookies_from_browser=tk_note_cookies_from_browser,
            proxy=tk_note_proxy,
            timeout=tk_note_timeout,
        )
        self.generic = generic_downloader or GenericVideoDownloader(str(root / "generic"))
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, video_id: str) -> threading.Lock:
        key = _safe_cache_key(video_id)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def prepare(self, video_url: str, video_id: str, force: bool = False) -> VideoAsset:
        with self._lock_for(video_id):
            if is_tiktok_url(video_url):
                return self.tk_note.collect(video_url, video_id, force=force)
            was_cached = self.generic.output_path(video_id).is_file() and not force
            path = self.generic.download(video_url, video_id, force=force)
            if not path:
                raise VideoIngestError("无法下载原视频，请检查链接、网络或站点登录状态后重试")
            return VideoAsset(
                provider="yt-dlp",
                status="reused" if was_cached else "success",
                video_file=path,
                video_id=video_id,
                source_url=video_url,
            )
