"""Provider-neutral shot evidence for the ViralX evidence pipeline.

The local scene detector is adapted from ShotLoom's MIT-licensed
``backend/services/shot_detector.py`` at commit
``78b65e24a587052ff2c0c4ccae72575295bde34f``. ViralX intentionally reuses
only the detection idea (PySceneDetect ContentDetector + AdaptiveDetector),
not ShotLoom's web application, accounts, tasks, or recommendation prompts.

Unlike the upstream implementation, ViralX never drops every segment shorter
than 0.5 seconds. Only detector noise shorter than 80 ms is merged, so fast
cuts remain part of the auditable timeline.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests

from libtv_analyzer import DEFAULT_SHOT_MODEL, LibTVAnalyzer, LibTVError


SHOT_EVIDENCE_SCHEMA = "viralx.shot_evidence.v1"
EVIDENCE_BUNDLE_SCHEMA = "viralx.evidence_bundle.v1"
SHOTLOOM_SOURCE_COMMIT = "78b65e24a587052ff2c0c4ccae72575295bde34f"
VALID_ENGINES = {"auto", "shotloom", "libtv", "skip"}
VALID_MODEL_SOURCES = {"inherit", "qwen", "custom"}
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3-vl-flash"


class ShotAnalyzerError(RuntimeError):
    """A safe error at the shot-evidence boundary."""


class ShotAnalyzerTransportError(ShotAnalyzerError):
    """A retry-exhausted upstream error that may be recoverable with a smaller batch."""

    def __init__(self, message: str, *, degradable: bool = True):
        super().__init__(message)
        self.degradable = degradable


@dataclass
class ShotBoundary:
    index: int
    start_time: float
    end_time: float
    duration: float

    @property
    def shot_id(self) -> str:
        return f"S{self.index + 1:03d}"


@dataclass
class ShotAnalysisResult:
    provider: str
    model: str
    status: str
    analysis: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    block_reason: str = ""
    fallback_used: bool = False
    fallback_chain: list[dict[str, str]] = field(default_factory=list)
    session_id: str = ""
    project_uuid: str = ""
    project_url: str = ""
    result_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_shot_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize the shot engine without ever returning a secret in status."""
    source = str(config.get("shot_model_source") or "inherit").strip().lower()
    engine = str(config.get("shot_engine") or "shotloom").strip().lower()
    if source not in VALID_MODEL_SOURCES:
        source = "inherit"
    if engine not in VALID_ENGINES:
        engine = "shotloom"

    final_vision = bool(config.get("model_supports_vision"))
    final_protocol = str(config.get("model_protocol") or "openai").lower()
    if source == "inherit":
        model_config = {
            "api_key": str(config.get("model_api_key") or ""),
            "base_url": str(config.get("model_base_url") or "").rstrip("/"),
            "model": str(config.get("model_name") or ""),
            "compatible": final_protocol == "openai" and final_vision,
            "label": "复用上方视觉模型",
        }
    elif source == "qwen":
        model_config = {
            "api_key": str(config.get("shot_model_api_key") or ""),
            "base_url": str(config.get("shot_model_base_url") or DEFAULT_QWEN_BASE_URL).rstrip("/"),
            "model": str(config.get("shot_model_name") or DEFAULT_QWEN_MODEL),
            "compatible": True,
            "label": "Qwen VL",
        }
    else:
        model_config = {
            "api_key": str(config.get("shot_model_api_key") or ""),
            "base_url": str(config.get("shot_model_base_url") or "").rstrip("/"),
            "model": str(config.get("shot_model_name") or ""),
            "compatible": True,
            "label": "自定义视觉模型",
        }

    try:
        threshold = min(max(float(config.get("shot_scene_threshold", 27.0)), 5.0), 80.0)
    except (TypeError, ValueError):
        threshold = 27.0
    return {
        "engine": engine,
        "model_source": source,
        "threshold": threshold,
        **model_config,
    }


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _format_time(seconds: float) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    minutes, remainder = divmod(milliseconds, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def merge_short_boundaries(
    cut_times: Iterable[float],
    duration: float,
    min_duration: float = 0.08,
) -> list[ShotBoundary]:
    """Build one contiguous timeline while retaining genuine fast cuts."""
    duration = max(float(duration or 0), 0.0)
    if duration <= 0:
        return []
    minimum = min(max(float(min_duration), 0.02), 0.2)
    normalized_cuts: set[float] = set()
    for item in cut_times:
        try:
            value = float(item)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and minimum <= value < duration:
            normalized_cuts.add(round(value, 4))
    cuts = sorted(normalized_cuts)
    accepted = [0.0]
    for cut in cuts:
        if cut - accepted[-1] >= minimum:
            accepted.append(cut)
    if duration - accepted[-1] < minimum and len(accepted) > 1:
        accepted.pop()
    accepted.append(duration)
    return [
        ShotBoundary(
            index=index,
            start_time=round(start, 4),
            end_time=round(end, 4),
            duration=round(end - start, 4),
        )
        for index, (start, end) in enumerate(zip(accepted, accepted[1:]))
        if end > start
    ]


def shotloom_dependency_status() -> dict[str, Any]:
    missing = []
    try:
        import cv2  # noqa: F401
    except ImportError:
        missing.append("opencv-python-headless")
    try:
        import scenedetect  # noqa: F401
    except ImportError:
        missing.append("scenedetect")
    return {
        "installed": not missing,
        "missing": missing,
        "source_commit": SHOTLOOM_SOURCE_COMMIT,
    }


def detect_shots(video_path: str, threshold: float = 27.0) -> list[ShotBoundary]:
    """Detect hard and adaptive cuts, then normalize them to a full timeline."""
    dependencies = shotloom_dependency_status()
    if not dependencies["installed"]:
        raise ShotAnalyzerError("缺少 ShotLoom Core 依赖：" + "、".join(dependencies["missing"]))
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import AdaptiveDetector, ContentDetector

        video = open_video(video_path)
        duration = float(video.duration.get_seconds())
        content_manager = SceneManager()
        content_manager.add_detector(ContentDetector(threshold=float(threshold)))
        content_manager.detect_scenes(video, show_progress=False)

        adaptive_video = open_video(video_path)
        adaptive_manager = SceneManager()
        adaptive_manager.add_detector(AdaptiveDetector())
        adaptive_manager.detect_scenes(adaptive_video, show_progress=False)

        cut_times: set[float] = set()
        for scenes in (content_manager.get_scene_list(), adaptive_manager.get_scene_list()):
            for index, (start, _end) in enumerate(scenes):
                if index:
                    cut_times.add(round(float(start.get_seconds()), 4))
        return merge_short_boundaries(cut_times, duration)
    except ShotAnalyzerError:
        raise
    except Exception as exc:
        raise ShotAnalyzerError(f"镜头检测失败：{type(exc).__name__}: {str(exc)[:160]}") from exc


def _strip_json_fence(value: str) -> str:
    text = str(value or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S | re.I)
    return fence.group(1).strip() if fence else text


def _visual_facts(item: dict[str, Any]) -> list[str]:
    facts = []
    for key in (
        "visual_summary",
        "subject_action",
        "scene",
        "on_screen_text",
        "shot_scale",
        "camera_movement",
        "transition_from_previous",
    ):
        value = item.get(key)
        if isinstance(value, list):
            value = "；".join(str(part).strip() for part in value if str(part).strip())
        value = str(value or "").strip()
        if value and value.lower() not in {"unknown", "none", "null", "无法判断", "未识别"}:
            facts.append(f"{key}: {value}")
    return facts


class ShotLoomCoreAnalyzer:
    """Local scene detection plus an OpenAI-compatible vision endpoint."""

    provider = "shotloom"

    def __init__(self, config: dict[str, Any], session: Any = requests):
        self.config = normalize_shot_config(config)
        self.session = session

    def status(self) -> dict[str, Any]:
        dependencies = shotloom_dependency_status()
        reasons = []
        if not dependencies["installed"]:
            reasons.append("缺少 " + "、".join(dependencies["missing"]))
        if not self.config["compatible"]:
            reasons.append("复用模型必须是 OpenAI-compatible 且支持视觉")
        if not self.config["api_key"]:
            reasons.append("镜头视觉模型未配置 API Key")
        if not self.config["base_url"]:
            reasons.append("镜头视觉模型未配置 Base URL")
        if not self.config["model"]:
            reasons.append("镜头视觉模型未配置模型名称")
        return {
            "provider": self.provider,
            "ready": not reasons,
            "installed": dependencies["installed"],
            "missing": dependencies["missing"],
            "model_source": self.config["model_source"],
            "model": self.config["model"],
            "source_commit": SHOTLOOM_SOURCE_COMMIT,
            "message": "ShotLoom Core 已就绪" if not reasons else "；".join(reasons),
        }

    @staticmethod
    def _sample_times(shot: ShotBoundary) -> list[float]:
        if shot.duration <= 0.6:
            return [shot.start_time + shot.duration * 0.5]
        return [
            shot.start_time + shot.duration * 0.25,
            shot.start_time + shot.duration * 0.75,
        ]

    @staticmethod
    def _frame_data(video_path: str, seconds: float) -> str:
        import cv2

        capture = cv2.VideoCapture(video_path)
        try:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(seconds, 0) * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ShotAnalyzerError(f"无法读取 {_format_time(seconds)} 的关键帧")
            height, width = frame.shape[:2]
            if width > 960:
                frame = cv2.resize(frame, (960, max(2, int(height * 960 / width))))
            encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if not encoded:
                raise ShotAnalyzerError(f"无法编码 {_format_time(seconds)} 的关键帧")
            return base64.b64encode(buffer.tobytes()).decode("ascii")
        finally:
            capture.release()

    def _post_with_retry(self, payload: dict[str, Any], headers: dict[str, str]):
        transient_statuses = {408, 425, 429, 500, 502, 503, 504}
        last_reason = "连接异常"
        for attempt in range(3):
            try:
                response = self.session.post(
                    f"{self.config['base_url']}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=180,
                )
            except (requests.RequestException, ConnectionError, TimeoutError, OSError) as exc:
                last_reason = type(exc).__name__
            else:
                if response.status_code == 413:
                    raise ShotAnalyzerTransportError("镜头视觉请求体过大", degradable=True)
                if response.status_code not in transient_statuses:
                    return response
                last_reason = f"HTTP {response.status_code}"
                if response.status_code == 429 and attempt == 2:
                    raise ShotAnalyzerTransportError(
                        "镜头视觉模型限流，已重试 3 次",
                        degradable=False,
                    )
            if attempt < 2:
                time.sleep(0.75 * (2 ** attempt))
        raise ShotAnalyzerTransportError(f"镜头视觉模型连接不稳定，已重试 3 次（{last_reason}）")

    def _request_batch(self, video_path: str, shots: list[ShotBoundary]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{
            "type": "text",
            "text": (
                "你是镜头事实记录员，不是营销分析师。逐个分析下列镜头，只记录关键帧中直接可见的事实。"
                "禁止推断声音、配音、情绪、受众、卖点、留存、转化或优化建议；看不清就写 unknowns。"
                "只返回 JSON：{\"shots\":[{\"shot_id\":\"S001\",\"visual_summary\":\"\","
                "\"subject_action\":\"\",\"scene\":\"\",\"on_screen_text\":\"\","
                "\"shot_scale\":\"\",\"camera_movement\":\"\","
                "\"transition_from_previous\":\"\",\"unknowns\":[],\"confidence\":0.0}]}。"
            ),
        }]
        for shot in shots:
            times = self._sample_times(shot)
            content.append({
                "type": "text",
                "text": f"{shot.shot_id} {_format_time(shot.start_time)}-{_format_time(shot.end_time)}，关键帧如下：",
            })
            for moment in times:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{self._frame_data(video_path, moment)}"},
                })

        request_payload = {
            "model": self.config["model"],
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 4096,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        request_headers = {
            "Authorization": f"Bearer {self.config['api_key']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://viralx.metrolabs.mobi",
            "X-Title": "ViralX Shot Evidence",
        }
        response = self._post_with_retry(request_payload, request_headers)
        # Several otherwise compatible vision endpoints do not implement
        # response_format. Retry the same evidence request without that optional
        # hint; do not change providers or weaken the JSON parser.
        if response.status_code in {400, 404, 422}:
            request_payload.pop("response_format", None)
            response = self._post_with_retry(request_payload, request_headers)
        if response.status_code != 200:
            raise ShotAnalyzerError(f"镜头视觉模型返回 HTTP {response.status_code}")
        try:
            raw = response.json()["choices"][0]["message"]["content"]
            payload = json.loads(_strip_json_fence(raw))
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ShotAnalyzerError("镜头视觉模型没有返回有效 JSON 证据") from exc
        items = payload.get("shots")
        if not isinstance(items, list):
            raise ShotAnalyzerError("镜头视觉模型缺少 shots 数组")
        records = [item for item in items if isinstance(item, dict)]
        requested_ids = [shot.shot_id for shot in shots]
        returned_ids = [str(item.get("shot_id") or "").strip().upper() for item in records]
        if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != set(requested_ids):
            raise ShotAnalyzerError("镜头视觉模型返回的镜头编号与请求批次不一致")
        return records

    def _request_batch_resilient(self, video_path: str, shots: list[ShotBoundary]) -> list[dict[str, Any]]:
        try:
            return self._request_batch(video_path, shots)
        except ShotAnalyzerTransportError as exc:
            if not exc.degradable or len(shots) <= 1:
                raise
            midpoint = max(1, len(shots) // 2)
            return [
                *self._request_batch_resilient(video_path, shots[:midpoint]),
                *self._request_batch_resilient(video_path, shots[midpoint:]),
            ]

    def analyze(self, video_path: str, user_request: str = "") -> ShotAnalysisResult:
        state = self.status()
        if not state["ready"]:
            raise ShotAnalyzerError(state["message"])
        source = Path(video_path)
        if not source.is_file() or source.stat().st_size <= 0:
            raise ShotAnalyzerError("TK Note 原视频文件不存在或为空")

        shots = detect_shots(str(source), threshold=self.config["threshold"])
        if not shots:
            raise ShotAnalyzerError("没有检测到可分析的镜头时间线")

        records_by_id: dict[str, dict[str, Any]] = {}
        for start in range(0, len(shots), 5):
            for item in self._request_batch_resilient(str(source), shots[start:start + 5]):
                shot_id = str(item.get("shot_id") or "").strip().upper()
                if re.fullmatch(r"S\d{3}", shot_id):
                    records_by_id[shot_id] = item

        normalized = []
        for shot in shots:
            item = records_by_id.get(shot.shot_id, {})
            facts = _visual_facts(item)
            unknowns = item.get("unknowns") if isinstance(item.get("unknowns"), list) else []
            try:
                confidence = min(max(float(item.get("confidence", 0)), 0.0), 1.0)
            except (TypeError, ValueError):
                confidence = 0.0
            normalized.append({
                "shot_id": shot.shot_id,
                "start_ms": int(round(shot.start_time * 1000)),
                "end_ms": int(round(shot.end_time * 1000)),
                "duration_ms": int(round(shot.duration * 1000)),
                "keyframes_ms": [int(round(value * 1000)) for value in self._sample_times(shot)],
                "visual_facts": facts,
                "unknowns": [str(value).strip() for value in unknowns if str(value).strip()],
                "confidence": confidence,
            })

        duration_ms = int(round(shots[-1].end_time * 1000))
        analyzed_ms = sum(item["duration_ms"] for item in normalized if item["visual_facts"])
        timeline_ms = sum(item["duration_ms"] for item in normalized)
        evidence = {
            "schema": SHOT_EVIDENCE_SCHEMA,
            "provider": self.provider,
            "model": self.config["model"],
            "source": {
                "shotloom_commit": SHOTLOOM_SOURCE_COMMIT,
                "sha256": _sha256_file(source),
                "file_name": source.name,
            },
            "duration_ms": duration_ms,
            "shot_count": len(normalized),
            "shots": normalized,
            "quality": {
                "timeline_coverage": round(timeline_ms / max(duration_ms, 1), 4),
                "analyzed_coverage": round(analyzed_ms / max(duration_ms, 1), 4),
                "analyzed_shots": sum(bool(item["visual_facts"]) for item in normalized),
                "total_shots": len(normalized),
            },
            "audio_policy": "Audio facts are accepted only from TK Note transcript evidence.",
        }
        lines = []
        for item in normalized:
            facts = "；".join(item["visual_facts"]) or "未获得可核验视觉事实"
            lines.append(
                f"[SHOT:{item['shot_id']}] {_format_time(item['start_ms'] / 1000)}-"
                f"{_format_time(item['end_ms'] / 1000)} {facts}"
            )
        evidence["shot_analysis"] = "\n".join(lines)
        return ShotAnalysisResult(
            provider=self.provider,
            model=self.config["model"],
            status="completed",
            analysis=evidence["shot_analysis"],
            evidence=evidence,
        )


def _timestamp_seconds(token: str) -> float:
    parts = token.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        hours = "0"
    else:
        hours, minutes, seconds = parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class LibTVProviderAdapter:
    """Wrap the official CLI behind the same shot-evidence result contract."""

    provider = "libtv"
    _TIME_RE = re.compile(r"\b(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d{1,3})?\b")

    def __init__(self, analyzer: LibTVAnalyzer | None = None):
        self.analyzer = analyzer or LibTVAnalyzer()

    def status(self) -> dict[str, Any]:
        installed = bool(self.analyzer.available)
        connected = installed and bool(self.analyzer.is_authenticated())
        return {
            "provider": self.provider,
            "ready": connected,
            "installed": installed,
            "connected": connected,
            "model": DEFAULT_SHOT_MODEL,
            "message": (
                "LibTV 已连接"
                if connected else
                "未找到官方 LibTV CLI" if not installed else "LibTV 尚未完成网页授权"
            ),
        }

    def _normalize_evidence(self, video_path: str, details: dict[str, Any]) -> dict[str, Any]:
        analysis = str((details.get("evidence") or {}).get("shot_analysis") or details.get("analysis") or "").strip()
        timestamped = []
        for line in analysis.splitlines():
            tokens = self._TIME_RE.findall(line)
            if tokens:
                timestamped.append(([_timestamp_seconds(token) for token in tokens], line.strip()))
        if not timestamped:
            return {}

        starts = sorted({times[0] for times, _line in timestamped})
        records = []
        for index, (times, line) in enumerate(timestamped):
            start = times[0]
            next_starts = [value for value in starts if value > start]
            end = times[1] if len(times) > 1 and times[1] > start else (next_starts[0] if next_starts else start + 1.0)
            records.append({
                "shot_id": f"S{index + 1:03d}",
                "start_ms": int(round(start * 1000)),
                "end_ms": int(round(end * 1000)),
                "duration_ms": int(round((end - start) * 1000)),
                "keyframes_ms": [],
                "visual_facts": [self._TIME_RE.sub("", line).strip(" -–—|：:") or line],
                "unknowns": [],
                "confidence": 0.7,
            })
        duration_ms = max(item["end_ms"] for item in records)
        normalized_analysis = "\n".join(
            f"[SHOT:{item['shot_id']}] {_format_time(item['start_ms'] / 1000)}-"
            f"{_format_time(item['end_ms'] / 1000)} {'；'.join(item['visual_facts'])}"
            for item in records
        )
        return {
            "schema": SHOT_EVIDENCE_SCHEMA,
            "provider": self.provider,
            "model": DEFAULT_SHOT_MODEL,
            "source": {
                "sha256": _sha256_file(video_path),
                "file_name": Path(video_path).name,
            },
            "duration_ms": duration_ms,
            "shot_count": len(records),
            "shots": records,
            "quality": {
                "timeline_coverage": 1.0 if records[0]["start_ms"] == 0 else 0.0,
                "analyzed_coverage": 1.0 if records[0]["start_ms"] == 0 else 0.0,
                "analyzed_shots": len(records),
                "total_shots": len(records),
            },
            "shot_analysis": normalized_analysis,
            "raw_analysis": analysis,
            "project_url": details.get("project_url", ""),
            "audio_policy": "Audio facts are accepted only from TK Note transcript evidence.",
        }

    def analyze(self, video_path: str, user_request: str = "") -> ShotAnalysisResult:
        state = self.status()
        if not state["ready"]:
            raise ShotAnalyzerError(state["message"])
        try:
            details = self.analyzer.analyze(
                video_path,
                user_request=user_request or "逐镜头拉片并输出结构化事实证据",
            ).to_dict()
        except LibTVError as exc:
            raise ShotAnalyzerError(str(exc)) from exc
        evidence = self._normalize_evidence(video_path, details)
        return ShotAnalysisResult(
            provider=self.provider,
            model=DEFAULT_SHOT_MODEL,
            status=str(details.get("status") or "error"),
            analysis=str(evidence.get("shot_analysis") or details.get("analysis") or ""),
            evidence=evidence,
            session_id=str(details.get("session_id") or ""),
            project_uuid=str(details.get("project_uuid") or ""),
            project_url=str(details.get("project_url") or ""),
            result_urls=list(details.get("result_urls") or []),
        )


def validate_shot_evidence(details: ShotAnalysisResult | dict[str, Any]) -> str:
    """Return a human-readable block reason, or an empty string when auditable."""
    payload = details.to_dict() if isinstance(details, ShotAnalysisResult) else (details or {})
    evidence = payload.get("evidence") or {}
    if str(payload.get("status") or "").lower() != "completed":
        return f"镜头引擎状态为 {payload.get('status') or 'unknown'}"
    if evidence.get("schema") != SHOT_EVIDENCE_SCHEMA:
        return "镜头证据 schema 不匹配"
    source_hash = str((evidence.get("source") or {}).get("sha256") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", source_hash):
        return "镜头证据缺少原片 SHA-256"
    shots = evidence.get("shots") or []
    if not isinstance(shots, list) or not shots:
        return "镜头证据没有可核验镜头"
    ids = [str(item.get("shot_id") or "") for item in shots if isinstance(item, dict)]
    if len(ids) != len(shots) or len(set(ids)) != len(ids) or any(not re.fullmatch(r"S\d{3}", item) for item in ids):
        return "镜头 ID 缺失、重复或格式无效"
    quality = evidence.get("quality") or {}
    try:
        timeline_coverage = float(quality.get("timeline_coverage") or 0)
        analyzed_coverage = float(quality.get("analyzed_coverage") or 0)
    except (TypeError, ValueError):
        return "镜头证据质量字段不是有效数值"
    if not math.isfinite(timeline_coverage) or not math.isfinite(analyzed_coverage):
        return "镜头证据质量字段不是有限数值"
    if timeline_coverage < 0.98:
        return "镜头时间线覆盖率低于 98%"
    if analyzed_coverage < 0.90:
        return "已分析镜头覆盖率低于 90%"
    if any(not (item.get("visual_facts") or []) for item in shots):
        return "至少一个镜头缺少可核验视觉事实"
    return ""


class ShotAnalyzerRouter:
    """Select ShotLoom Core first and use LibTV only as an explicit fallback."""

    def __init__(
        self,
        config: dict[str, Any],
        shotloom: ShotLoomCoreAnalyzer | None = None,
        libtv: LibTVProviderAdapter | None = None,
    ):
        self.config = normalize_shot_config(config)
        self.engine = self.config["engine"]
        self.shotloom = shotloom or ShotLoomCoreAnalyzer(config)
        self.libtv = libtv or LibTVProviderAdapter()

    def status(self) -> dict[str, Any]:
        shotloom = self.shotloom.status()
        libtv = self.libtv.status()
        if self.engine == "skip":
            ready = True
        elif self.engine == "shotloom":
            ready = bool(shotloom.get("ready"))
        elif self.engine == "libtv":
            ready = bool(libtv.get("ready"))
        else:
            ready = bool(shotloom.get("ready") or libtv.get("ready"))
        return {
            "engine": self.engine,
            "ready": ready,
            "shotloom": shotloom,
            "libtv": libtv,
        }

    def analyze(self, video_path: str, user_request: str = "") -> ShotAnalysisResult:
        if self.engine == "skip":
            return ShotAnalysisResult(
                provider="none",
                model="",
                status="blocked",
                block_reason="已选择只采集：没有镜头证据，最终模型不会运行",
            )
        providers = (
            [("shotloom", self.shotloom), ("libtv", self.libtv)]
            if self.engine == "auto" else
            [(self.engine, self.shotloom if self.engine == "shotloom" else self.libtv)]
        )
        chain: list[dict[str, str]] = []
        for index, (name, provider) in enumerate(providers):
            try:
                state = provider.status()
                if not state.get("ready"):
                    raise ShotAnalyzerError(str(state.get("message") or f"{name} 未就绪"))
                result = provider.analyze(video_path, user_request=user_request)
                error = validate_shot_evidence(result)
                if error:
                    raise ShotAnalyzerError(error)
                result.fallback_used = index > 0
                result.fallback_chain = [*chain, {"provider": name, "status": "completed", "reason": ""}]
                return result
            except (ShotAnalyzerError, requests.RequestException, OSError, ValueError) as exc:
                chain.append({"provider": name, "status": "failed", "reason": str(exc)[:240]})
        reason = "；".join(f"{item['provider']}: {item['reason']}" for item in chain)
        return ShotAnalysisResult(
            provider=providers[-1][0],
            model="",
            status="blocked",
            block_reason=reason or "没有可用的镜头证据引擎",
            fallback_used=len(providers) > 1,
            fallback_chain=chain,
        )
