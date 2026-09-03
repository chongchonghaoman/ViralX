"""Official LibTV CLI integration for local ViralX.

LibTV authentication is owned by the official CLI. ViralX only asks the CLI
whether it is signed in and starts ``libtv login web`` when the user requests
it; credential files and tokens are never read by this module.
"""

from __future__ import annotations

from .paths import PROJECT_ROOT

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse


LIBTV_CLI_PAGE = "https://www.liblib.tv/cli"
LIBTV_CANVAS_URL = "https://www.liblib.tv/canvas?projectId={}"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
DEFAULT_SHOT_MODEL = "GVLM 3.1 Flash"
_LOGIN_URL_RE = re.compile(r"https://www\.liblib\.tv/[^\s]+callback_url=[^\s]+")


class LibTVError(RuntimeError):
    """A safe, user-facing LibTV integration error."""


@dataclass
class LibTVAnalysisResult:
    analysis: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    project_uuid: str = ""
    project_url: str = ""
    result_urls: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["result_urls"] = self.result_urls or []
        return payload


def find_libtv_cli() -> str:
    """Find the official CLI without assuming the shell has refreshed PATH."""
    configured = os.environ.get("LIBTV_CLI_BINARY", "").strip()
    if configured and Path(configured).is_file():
        return str(Path(configured))

    discovered = shutil.which("libtv") or shutil.which("libtv.exe")
    if discovered:
        return discovered

    cli_home = Path.home() / ".libtv"
    for candidate in (cli_home / "libtv.exe", cli_home / "libtv"):
        if candidate.is_file():
            return str(candidate)
    return ""


def _hidden_process_options() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _safe_message(value: Any) -> str:
    """Keep CLI diagnostics useful without ever echoing token-shaped values."""
    text = str(value or "").strip()
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(
        r"(?i)(authorization|access[_ -]?token|refresh[_ -]?token|api[_ -]?key)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text[:600]


def _default_runner(cli_path: str, args: list[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(
        [cli_path, *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **_hidden_process_options(),
    )


def libtv_authenticated(cli_path: str = "") -> bool:
    """Ask the CLI for account state; do not inspect its credential storage."""
    binary = cli_path or find_libtv_cli()
    if not binary:
        return False
    try:
        completed = subprocess.run(
            [binary, "account", "info"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            **_hidden_process_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


class LibTVAuthManager:
    """Own the local CLI web-login process and expose a token-free state model."""

    def __init__(self, cwd: Path | str | None = None, cli_path: str = ""):
        self.cwd = Path(cwd or PROJECT_ROOT)
        self.cli_path = cli_path or find_libtv_cli()
        self._process: Optional[subprocess.Popen] = None
        self._login_url = ""
        self._error = ""
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._auth_cache = (0.0, False)

    def _version(self) -> str:
        if not self.cli_path:
            return ""
        try:
            completed = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
                **_hidden_process_options(),
            )
            return _safe_message(completed.stdout or completed.stderr).splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    def _is_authenticated(self, force: bool = False) -> bool:
        now = time.monotonic()
        checked_at, cached = self._auth_cache
        if not force and now - checked_at < 3:
            return cached
        connected = libtv_authenticated(self.cli_path)
        self._auth_cache = (now, connected)
        return connected

    def status(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            if not self.cli_path:
                return {
                    "state": "unavailable",
                    "connected": False,
                    "cli_installed": False,
                    "cli_version": "",
                    "login_url": "",
                    "message": "未找到官方 LibTV CLI，请先安装后重新连接。",
                    "install_url": LIBTV_CLI_PAGE,
                }

            connected = self._is_authenticated(force=force)
            if connected:
                self._error = ""
                return {
                    "state": "connected",
                    "connected": True,
                    "cli_installed": True,
                    "cli_version": self._version(),
                    "login_url": "",
                    "message": "已通过官方 LibTV CLI 登录，本机拉片已就绪。",
                    "install_url": LIBTV_CLI_PAGE,
                }

            running = self._process is not None and self._process.poll() is None
            if running:
                state = "awaiting_browser" if self._login_url else "starting"
                return {
                    "state": state,
                    "connected": False,
                    "cli_installed": True,
                    "cli_version": self._version(),
                    "login_url": self._login_url,
                    "message": (
                        "请在 LibTV 官方网页完成授权，完成后会自动同步到本机。"
                        if self._login_url
                        else "正在启动 LibTV 网页授权…"
                    ),
                    "install_url": LIBTV_CLI_PAGE,
                }

            if self._error:
                state, message = "error", self._error
            else:
                state, message = "disconnected", "尚未连接 LibTV；连接时会打开官方授权页。"
            return {
                "state": state,
                "connected": False,
                "cli_installed": True,
                "cli_version": self._version(),
                "login_url": "",
                "message": message,
                "install_url": LIBTV_CLI_PAGE,
            }

    def _watch_login(self, process: subprocess.Popen) -> None:
        output: list[str] = []
        try:
            if process.stdout:
                for line in process.stdout:
                    output.append(line)
                    match = _LOGIN_URL_RE.search(line)
                    if match:
                        candidate = match.group(0).rstrip(".,)")
                        parsed = urlparse(candidate)
                        if parsed.scheme == "https" and parsed.hostname == "www.liblib.tv":
                            with self._condition:
                                self._login_url = candidate
                                self._condition.notify_all()
            return_code = process.wait()
        except Exception as exc:  # pragma: no cover - defensive process boundary
            return_code = -1
            output.append(str(exc))

        with self._condition:
            self._auth_cache = (0.0, False)
            if return_code != 0 and not self._is_authenticated(force=True):
                diagnostic = _safe_message(" ".join(output))
                self._error = diagnostic or "LibTV 网页授权未完成，请重试。"
            self._process = None
            self._login_url = ""
            self._condition.notify_all()

    def start_login(self) -> dict[str, Any]:
        with self._condition:
            if not self.cli_path:
                return self.status(force=True)
            if self._is_authenticated(force=True):
                return self.status(force=True)
            if self._process is None or self._process.poll() is not None:
                self._error = ""
                self._login_url = ""
                try:
                    self._process = subprocess.Popen(
                        [self.cli_path, "login", "web"],
                        cwd=str(self.cwd),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                        **_hidden_process_options(),
                    )
                except OSError as exc:
                    self._error = f"无法启动 LibTV CLI：{_safe_message(exc)}"
                    return self.status(force=True)
                threading.Thread(
                    target=self._watch_login,
                    args=(self._process,),
                    name="libtv-web-login",
                    daemon=True,
                ).start()

            deadline = time.monotonic() + 4
            while not self._login_url and self._process and self._process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=min(remaining, 0.25))
            return self.status(force=False)

    def logout(self) -> dict[str, Any]:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
            self._process = None
            self._login_url = ""
            self._error = ""
            if self.cli_path:
                try:
                    subprocess.run(
                        [self.cli_path, "logout"],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=8,
                        check=False,
                        **_hidden_process_options(),
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
            self._auth_cache = (0.0, False)
            return self.status(force=True)


def _find_project_uuid(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("uuid", "projectUuid", "project_uuid", "projectId", "project_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for item in value.values():
            found = _find_project_uuid(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_project_uuid(item)
            if found:
                return found
    elif isinstance(value, str):
        text = value.strip()
        patterns = (
            r"[?&]projectId=([A-Za-z0-9_-]{6,})",
            r"(?i)(?:projectUuid|project_uuid|projectId|project_id|uuid)\s*['\"]?\s*[:=：]\s*['\"]?([A-Za-z0-9_-]{6,})",
            r"(?i)(?:项目|画布)(?:\s*(?:UUID|ID|标识))?\s*[:=：]\s*([A-Za-z0-9_-]{6,})",
            r"\b([0-9a-fA-F]{8}-[0-9a-fA-F-]{27,})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
    return ""


def _extract_generated_text(value: Any) -> str:
    """Extract generated text from the CLI's nested node response."""
    if isinstance(value, dict):
        for key in ("content", "output", "result", "answer", "markdown", "text"):
            if key not in value:
                continue
            found = _extract_generated_text(value[key])
            if found:
                return found
        for key in ("data", "node", "nodes", "task", "response"):
            if key not in value:
                continue
            found = _extract_generated_text(value[key])
            if found:
                return found
    elif isinstance(value, list):
        parts = [_extract_generated_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    elif isinstance(value, str):
        text = value.strip()
        if text and not text.startswith(("http://", "https://")):
            return text[:30000]
    return ""


class LibTVAnalyzer:
    """Create a LibTV canvas, upload the source, and run multimodal shot analysis."""

    def __init__(
        self,
        cli_path: str = "",
        runner: Optional[Callable[[list[str], float], Any]] = None,
        auth_checker: Optional[Callable[[], bool]] = None,
        cwd: Path | str | None = None,
        timeout: float = 180,
        shot_model: str = "",
    ):
        self.cli_path = cli_path or find_libtv_cli()
        self.cwd = Path(cwd or PROJECT_ROOT)
        self.timeout = max(15.0, float(timeout or 180))
        self.shot_model = str(shot_model or os.environ.get("LIBTV_SHOT_MODEL") or DEFAULT_SHOT_MODEL).strip()
        self.runner = runner
        self.auth_checker = auth_checker or (lambda: libtv_authenticated(self.cli_path))

    @property
    def available(self) -> bool:
        return bool(self.cli_path)

    def is_authenticated(self) -> bool:
        return bool(self.available and self.auth_checker())

    def _run_json(self, args: list[str], timeout: float) -> dict[str, Any]:
        try:
            result = (
                self.runner(args, timeout)
                if self.runner
                else _default_runner(self.cli_path, args, timeout)
            )
        except subprocess.TimeoutExpired as exc:
            raise LibTVError("LibTV CLI 操作超时，请稍后重试。") from exc
        except OSError as exc:
            raise LibTVError(f"无法启动 LibTV CLI：{_safe_message(exc)}") from exc

        if isinstance(result, dict):
            return result

        return_code = getattr(result, "returncode", 0)
        stdout = getattr(result, "stdout", "") or ""
        stderr = getattr(result, "stderr", "") or ""
        if return_code != 0:
            detail = _safe_message(stderr or stdout)
            lowered = detail.lower()
            if any(word in lowered for word in ("login", "unauth", "401", "credential")):
                raise LibTVError("LibTV 登录已失效，请在设置页重新连接。")
            raise LibTVError(detail or "LibTV CLI 执行失败。")
        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            payload = {"raw": stdout}
        if isinstance(payload, dict):
            return payload
        return {"data": payload, "raw": stdout}

    def analyze(self, video_file_path: str, user_request: str = "逐帧拉片") -> LibTVAnalysisResult:
        if not self.available:
            raise LibTVError("未找到官方 LibTV CLI，请先安装并在设置页连接。")
        if not self.is_authenticated():
            raise LibTVError("尚未登录 LibTV，请在设置页点击“连接 LibTV”完成网页授权。")

        video_path = Path(video_file_path).resolve()
        if not video_path.is_file():
            raise LibTVError("待上传的视频文件不存在。")
        if video_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise LibTVError("视频超过 LibTV CLI 当前 200 MB 上传限制。")

        project_name = f"ViralX 拉片 · {video_path.stem[:48]}"
        created = self._run_json(
            ["project", "create", project_name, "--description", "由 ViralX 采集并交给 LibTV 继续逐帧拉片"],
            min(self.timeout, 45),
        )
        project_uuid = _find_project_uuid(created)
        if not project_uuid:
            raise LibTVError("LibTV 已响应，但没有返回画布项目 ID。")

        self._run_json(
            [
                "upload",
                "ViralX 原视频",
                "--resource",
                str(video_path),
                "--type",
                "video",
                "--project",
                project_uuid,
                "--x",
                "0",
                "--y",
                "0",
            ],
            self.timeout,
        )
        shot_prompt = f"""你是 ViralX 的专业短视频拉片分析师。请直接分析左侧原视频，输出可供下游模型引用的证据，不要生成新视频，也不要编造不可见信息。

请使用 Markdown 严格输出：
1. 基础时长与内容概览；
2. 按时间码拆分镜头，每个镜头写明画面、动作、景别、机位、转场、字幕、声音和商品展示；
3. 前 3 秒钩子、节奏变化、情绪曲线与转化节点；
4. 明确区分“画面可观察事实”和“分析推断”；
5. 最后列出可被最终模型直接引用的逐条证据。

用户任务：{user_request}"""
        analysis_node = "ViralX 专业拉片"
        generated = self._run_json(
            [
                "node",
                "--project",
                project_uuid,
                "--x",
                "520",
                "--y",
                "0",
                "create",
                analysis_node,
                "--type",
                "text",
                "--left",
                "ViralX 原视频",
                "--prompt",
                shot_prompt,
                "--set",
                f"model={self.shot_model}",
                "--run",
            ],
            max(self.timeout, 300),
        )
        shot_evidence = _extract_generated_text(generated)
        if not shot_evidence:
            inspected = self._run_json(
                ["node", "--project", project_uuid, analysis_node],
                min(self.timeout, 45),
            )
            shot_evidence = _extract_generated_text(inspected)
        if not shot_evidence:
            raise LibTVError("LibTV 已创建画布，但拉片节点没有返回可读取的分析证据。")

        project_url = LIBTV_CANVAS_URL.format(project_uuid)
        return LibTVAnalysisResult(
            analysis=shot_evidence,
            status="completed",
            evidence={
                "provider": "libtv",
                "model": self.shot_model,
                "shot_analysis": shot_evidence,
                "project_uuid": project_uuid,
                "project_url": project_url,
            },
            project_uuid=project_uuid,
            project_url=project_url,
            result_urls=[project_url],
        )
