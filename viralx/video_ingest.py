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
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import unquote, urlparse, urlsplit, urlunsplit
from urllib.request import getproxies

from .tiktok_viral_analyzer import safe_error_message
from .paths import PROJECT_ROOT


TIKTOK_HOSTS = {"tiktok.com", "www.tiktok.com", "m.tiktok.com", "vt.tiktok.com", "vm.tiktok.com"}
LOG_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


class VideoIngestError(RuntimeError):
    """Stable acquisition error safe to return to the local ViralX UI."""

    def __init__(self, message: str, *, code: str = "collection_failed", task_log: str = ""):
        super().__init__(message)
        self.code = code
        self.task_log = task_log


def is_tiktok_url(value: str) -> bool:
    try:
        host = (urlparse(value).hostname or "").lower()
    except ValueError:
        return False
    return host in TIKTOK_HOSTS or host.endswith(".tiktok.com")


def _safe_cache_key(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_-]", "", str(value or ""))[:80]
    return cleaned or "video"


def _safe_source_url(value: str) -> str:
    """Keep a public page URL while dropping query strings and signed-media data."""
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if not (host in TIKTOK_HOSTS or host.endswith(".tiktok.com")):
        return ""
    return urlunsplit((parsed.scheme or "https", parsed.netloc, parsed.path, "", ""))


def _proxy_secret_parts(value: str) -> List[str]:
    if not value:
        return []
    parts = [value]
    try:
        parsed = urlsplit(value)
        parts.extend(filter(None, (unquote(parsed.username or ""), unquote(parsed.password or ""))))
    except ValueError:
        pass
    return parts


def _redact_log_urls(value: str) -> str:
    """Keep canonical TikTok page URLs only; remove signed/CDN/request URLs."""
    def replace(match: re.Match) -> str:
        candidate = match.group(0).rstrip(".,;:)]}")
        suffix = match.group(0)[len(candidate):]
        safe_page = _safe_source_url(candidate)
        return (safe_page or "[url redacted]") + suffix

    return LOG_URL_PATTERN.sub(replace, value)


def _system_proxy() -> str:
    """Honor the user's Windows/system proxy when no explicit proxy is supplied."""
    try:
        proxies = getproxies()
    except (OSError, ValueError):
        return ""
    for key in ("https", "http", "all"):
        candidate = str(proxies.get(key) or "").strip()
        if not candidate:
            continue
        try:
            parsed = urlsplit(candidate)
            _ = parsed.port
        except ValueError:
            continue
        if parsed.scheme.lower() in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"} and parsed.hostname:
            return candidate
    return ""


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
    task_log: str = ""
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
            f"{prefix}_task_log": self.task_log,
            f"{prefix}_warnings": self.warnings,
            f"{prefix}_blocked_stages": self.blocked_stages,
            f"{prefix}_reused": self.status == "reused",
        }

    def video_fields(self) -> Dict[str, object]:
        if not self.metadata:
            return {}
        def first(*names: str) -> object:
            return next((self.metadata.get(name) for name in names if self.metadata.get(name) not in (None, "")), None)

        def positive(*names: str) -> object:
            value = first(*names)
            try:
                return value if not isinstance(value, bool) and float(value) > 0 else None
            except (TypeError, ValueError):
                return None

        author = first("author", "author_name", "unique_id")
        if isinstance(author, dict):
            author = author.get("unique_id") or author.get("uniqueId") or author.get("nickname")
        fields = {
            "video_id": first("video_id", "id"),
            "title": first("title", "description", "desc"),
            "author": author,
            "duration": positive("duration"),
            # Zero is commonly a fallback collector placeholder. Keep the
            # already verified search metric unless acquisition has a real count.
            "views": positive("view_count", "play_count", "playCount", "views", "number_of_plays"),
            "likes": positive("like_count", "digg_count", "diggCount", "likes", "number_of_hearts"),
            "comments": positive("comment_count", "commentCount", "comments", "number_of_comments"),
            "shares": positive("share_count", "shareCount", "shares", "number_of_reposts"),
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
        self.skill_dir = skill_dir or PROJECT_ROOT / ".agents" / "skills" / "tk-note"
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
        explicit_proxy = proxy or ""
        self.proxy = explicit_proxy or _system_proxy()
        self.proxy_source = "explicit" if explicit_proxy else "system" if self.proxy else "none"
        self.timeout = max(float(timeout), 30)
        self._runner = runner

    def _run(self, command: List[str], extra_env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
        if self._runner:
            return self._runner(command, self.timeout)
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        if extra_env:
            env.update(extra_env)
        try:
            return subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VideoIngestError("TK Note 采集超时；已完成的缓存资产仍会保留") from exc

    def _safe_message(self, value: object) -> str:
        return _redact_log_urls(safe_error_message(value, _proxy_secret_parts(self.proxy)))

    @staticmethod
    def _append_task_log(path: Path, payload: Dict[str, object]) -> None:
        record = {
            "schema": "viralx.tk-note-task.v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _log_progress(self, task_log: Path, events: List[Dict[str, object]]) -> None:
        for event in events:
            self._append_task_log(task_log, {
                "event": "progress",
                "stage": str(event.get("stage") or ""),
                "status": str(event.get("status") or ""),
                "message": self._safe_message(event.get("message") or ""),
            })

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

    def collect(
        self,
        video_url: str,
        video_id: str,
        force: bool = False,
        media_url: str = "",
    ) -> VideoAsset:
        if not self.script.is_file():
            raise VideoIngestError(f"缺少项目内 TK Note 脚本：{self.script}")
        out_dir = self.cache_dir / _safe_cache_key(video_id)
        task_log = out_dir / "task.jsonl"
        self._append_task_log(task_log, {
            "event": "collection_started",
            "video_id": str(video_id or ""),
            "source_url": _safe_source_url(video_url),
            "refresh_derived": bool(force),
            "media_transport_available": bool(media_url),
            "cookie_browser": self.cookies_from_browser or "none",
            "proxy_configured": bool(self.proxy),
            "proxy_source": self.proxy_source,
        })
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
            # The public UI's "refresh evidence" action must never destroy a
            # valid source video. TK Note refreshes transcript/derived assets;
            # explicit CLI --force remains the only full redownload operation.
            command.append("--refresh-derived")

        try:
            child_env = {"VIRALX_TK_MEDIA_URL": media_url} if media_url else None
            completed = self._run(command, child_env)
            progress = self._parse_progress(completed.stderr)
            self._log_progress(task_log, progress)
            payload = self._parse_result(completed.stdout)
            if completed.returncode != 0 or payload.get("status") == "error":
                message = str(payload.get("message") or "TK Note 无法下载当前 TikTok 视频")
                raise VideoIngestError(message)
        except VideoIngestError as exc:
            message = self._safe_message(exc)
            self._append_task_log(task_log, {
                "event": "collection_failed",
                "stage": "download",
                "status": "error",
                "error_code": getattr(exc, "code", "collection_failed"),
                "message": message,
            })
            raise VideoIngestError(
                message,
                code=getattr(exc, "code", "collection_failed"),
                task_log=str(task_log),
            ) from exc
        video_file = Path(str(payload.get("video_file") or ""))
        if not video_file.is_file() or video_file.stat().st_size <= 0:
            message = "TK Note 返回成功但没有生成非空 source.mp4"
            self._append_task_log(task_log, {
                "event": "collection_failed",
                "stage": "download",
                "status": "error",
                "error_code": "missing_video_file",
                "message": message,
            })
            raise VideoIngestError(message, code="missing_video_file", task_log=str(task_log))

        metadata_path = str(payload.get("metadata") or "")
        self._append_task_log(task_log, {
            "event": "collection_completed",
            "stage": "download",
            "status": str(payload.get("status") or "success"),
            "video_id": str(payload.get("video_id") or video_id),
            "video_size_bytes": video_file.stat().st_size,
            "transcript_source": str(payload.get("transcript_source") or ""),
            "blocked_stages": [str(item) for item in payload.get("blocked_stages", [])],
        })
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
            task_log=str(task_log),
            warnings=[str(item) for item in payload.get("warnings", [])],
            blocked_stages=[str(item) for item in payload.get("blocked_stages", [])],
            progress_events=progress,
            metadata=self._read_metadata(metadata_path),
        )


class GenericVideoDownloader:
    """Small yt-dlp compatibility route for non-TikTok links."""

    def __init__(self, output_dir: Optional[str] = None, timeout: float = 180):
        self.output_dir = Path(output_dir or PROJECT_ROOT / "video_cache" / "generic")
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
        root = Path(cache_dir or PROJECT_ROOT / "video_cache")
        if not root.is_absolute():
            root = PROJECT_ROOT / root
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

    def prepare(
        self,
        video_url: str,
        video_id: str,
        force: bool = False,
        media_url: str = "",
    ) -> VideoAsset:
        with self._lock_for(video_id):
            if is_tiktok_url(video_url):
                if media_url:
                    return self.tk_note.collect(video_url, video_id, force=force, media_url=media_url)
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
