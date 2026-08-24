"""LibTV 一键拉片适配器。

ViralX 通过项目内安装的官方 ``libtv-skill`` 脚本完成上传、创建会话和
查询进度。本模块只负责编排这些脚本，不改写 LibTV 的用户指令。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional


DEFAULT_IM_BASE = "https://im.liblib.tv"
DEFAULT_REQUEST = "一键拉片"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

MEDIA_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+\.(?:png|jpe?g|webp|mp4|mov|webm)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)
REPORT_MARKERS = (
    "拉片",
    "镜头",
    "分镜",
    "时间轴",
    "画面",
    "景别",
    "运镜",
    "旁白",
    "##",
    "|---",
)
PROGRESS_MARKERS = ("正在", "处理中", "请稍候", "排队中", "生成中", "分析中")
FINAL_STATES = {"completed", "complete", "done", "finished", "success", "succeeded"}


class LibTVError(RuntimeError):
    """LibTV 调用失败，错误内容已移除密钥。"""


@dataclass
class LibTVAnalysisResult:
    analysis: str
    status: str
    session_id: str
    project_uuid: str
    project_url: str
    result_urls: List[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value:
                    parts.append(_content_to_text(value))
            elif item:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        value = content.get("text") or content.get("content")
        if value:
            return _content_to_text(value)
        return json.dumps(content, ensure_ascii=False)
    return str(content).strip() if content is not None else ""


def _message_state(message: Dict[str, object]) -> str:
    candidates = [
        message.get("status"),
        message.get("state"),
        message.get("finishReason"),
        message.get("finish_reason"),
    ]
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend((metadata.get("status"), metadata.get("state")))
    for value in candidates:
        if value:
            return str(value).strip().lower()
    return ""


def _extract_result_urls(messages: Iterable[Dict[str, object]]) -> List[str]:
    urls: List[str] = []
    for message in messages:
        content = message.get("content", "")
        text = _content_to_text(content)
        urls.extend(MEDIA_URL_RE.findall(text))

        if message.get("role") != "tool" or not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue
        task_result = payload.get("task_result", {}) if isinstance(payload, dict) else {}
        if not isinstance(task_result, dict):
            continue
        for key in ("images", "videos"):
            for item in task_result.get(key, []) or []:
                if not isinstance(item, dict):
                    continue
                url = item.get("previewPath") or item.get("url")
                if url:
                    urls.append(str(url))

    unique: List[str] = []
    seen = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _extract_report(messages: Iterable[Dict[str, object]]) -> Optional[str]:
    """返回最近一条看起来已经完成的 assistant 拉片结果。"""
    candidates: List[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        text = _content_to_text(message.get("content", ""))
        if not text:
            continue

        state = _message_state(message)
        is_progress = any(marker in text for marker in PROGRESS_MARKERS)
        looks_structured = len(text) >= 80 or any(marker in text for marker in REPORT_MARKERS)
        explicitly_done = state in FINAL_STATES or ("完成" in text and not is_progress)
        if (looks_structured and not is_progress) or explicitly_done:
            candidates.append(text)

    return candidates[-1] if candidates else None


def _latest_assistant_text(messages: Iterable[Dict[str, object]]) -> str:
    latest = ""
    for message in messages:
        if message.get("role") == "assistant":
            text = _content_to_text(message.get("content", ""))
            if text:
                latest = text
    return latest


class LibTVAnalyzer:
    """使用官方 libtv-skill 脚本执行一次完整的视频拉片。"""

    def __init__(
        self,
        access_key: str = "",
        im_base: str = "",
        poll_interval: float = 8,
        timeout: float = 180,
        skill_dir: Optional[Path] = None,
        runner: Optional[Callable[[str, List[str], float], Dict[str, object]]] = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.access_key = access_key or os.environ.get("LIBTV_ACCESS_KEY", "")
        self.im_base = (
            im_base
            or os.environ.get("OPENAPI_IM_BASE")
            or os.environ.get("IM_BASE_URL")
            or DEFAULT_IM_BASE
        )
        self.poll_interval = max(float(poll_interval), 0)
        self.timeout = max(float(timeout), 1)
        self.skill_dir = skill_dir or (
            Path(__file__).parent / ".agents" / "skills" / "libtv-skill"
        )
        configured_scripts_dir = os.environ.get("VIRALX_LIBTV_SCRIPTS_DIR", "")
        self.scripts_dir = (
            self.skill_dir / "scripts"
            if skill_dir is not None
            else Path(configured_scripts_dir)
            if configured_scripts_dir
            else self.skill_dir / "scripts"
        )
        self._runner = runner
        self._sleep = sleeper
        self._clock = clock

    def _redact(self, value: str) -> str:
        if self.access_key:
            return value.replace(self.access_key, "[REDACTED]")
        return value

    def _run_script(
        self, script_name: str, args: List[str], timeout: float
    ) -> Dict[str, object]:
        if self._runner:
            return self._runner(script_name, args, timeout)

        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            raise LibTVError(f"缺少官方 LibTV 脚本：{script_path}")

        env = os.environ.copy()
        env["LIBTV_ACCESS_KEY"] = self.access_key
        if self.im_base:
            env["OPENAPI_IM_BASE"] = self.im_base

        try:
            completed = subprocess.run(
                [sys.executable, str(script_path), *args],
                cwd=str(Path(__file__).parent),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LibTVError(f"LibTV {script_name} 调用超时") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "未知错误").strip()
            raise LibTVError(self._redact(f"LibTV {script_name} 失败：{detail}"))

        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            preview = self._redact(completed.stdout[:300])
            raise LibTVError(f"LibTV {script_name} 返回了无效 JSON：{preview}") from exc

    @staticmethod
    def _message_key(message: Dict[str, object]) -> str:
        if message.get("id"):
            return f"id:{message['id']}"
        return json.dumps(message, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _max_seq(messages: Iterable[Dict[str, object]], current: int) -> int:
        maximum = current
        for message in messages:
            try:
                maximum = max(maximum, int(message.get("seq", 0) or 0))
            except (TypeError, ValueError):
                continue
        return maximum

    def analyze(
        self, video_file_path: str, user_request: str = DEFAULT_REQUEST
    ) -> LibTVAnalysisResult:
        if not self.access_key:
            raise LibTVError("未配置 LIBTV_ACCESS_KEY，请先在设置页填写 LibTV Access Key")

        video_path = Path(video_file_path)
        if not video_path.is_file():
            raise LibTVError(f"待拉片视频不存在：{video_path}")
        if video_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise LibTVError("LibTV 仅支持 200MB 以内的视频，请先压缩后重试")

        upload = self._run_script("upload_file.py", [str(video_path)], timeout=150)
        oss_url = str(upload.get("url", "")).strip()
        if not oss_url:
            raise LibTVError("LibTV 上传成功但未返回视频地址")

        request_text = (user_request or DEFAULT_REQUEST).strip()
        message = f"{request_text}\n参考视频：{oss_url}"
        session = self._run_script("create_session.py", [message], timeout=45)
        session_id = str(session.get("sessionId", "")).strip()
        project_uuid = str(session.get("projectUuid", "")).strip()
        project_url = str(session.get("projectUrl", "")).strip()
        if not session_id:
            raise LibTVError("LibTV 未返回 sessionId")

        started_at = self._clock()
        after_seq = 0
        consecutive_errors = 0
        seen = set()
        messages: List[Dict[str, object]] = []

        while self._clock() - started_at < self.timeout:
            try:
                args = [session_id, "--after-seq", str(after_seq)]
                if project_uuid:
                    args.extend(("--project-id", project_uuid))
                payload = self._run_script("query_session.py", args, timeout=45)
                consecutive_errors = 0
            except LibTVError:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    raise
                self._sleep(min(self.poll_interval, 1))
                continue

            batch = payload.get("messages", [])
            if not isinstance(batch, list):
                batch = []
            for item in batch:
                if not isinstance(item, dict):
                    continue
                key = self._message_key(item)
                if key not in seen:
                    seen.add(key)
                    messages.append(item)
            after_seq = self._max_seq(batch, after_seq)

            result_urls = _extract_result_urls(messages)
            report = _extract_report(messages)
            if report or result_urls:
                analysis = report or "LibTV 已完成拉片，结果见下方链接。"
                if result_urls and not all(url in analysis for url in result_urls):
                    analysis += "\n\n## LibTV 结果\n" + "\n".join(
                        f"- {url}" for url in result_urls
                    )
                return LibTVAnalysisResult(
                    analysis=analysis,
                    status="completed",
                    session_id=session_id,
                    project_uuid=project_uuid,
                    project_url=project_url,
                    result_urls=result_urls,
                )

            self._sleep(self.poll_interval)

        latest = _latest_assistant_text(messages)
        timeout_text = latest or "LibTV 拉片仍在处理中，可稍后从项目画布继续查看。"
        return LibTVAnalysisResult(
            analysis=timeout_text,
            status="timeout",
            session_id=session_id,
            project_uuid=project_uuid,
            project_url=project_url,
            result_urls=_extract_result_urls(messages),
        )
