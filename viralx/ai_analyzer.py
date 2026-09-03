import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import re
import time
import hashlib
import base64
import subprocess
import threading
import requests
import anthropic
import google.genai as genai
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from .paths import PROJECT_ROOT
from .evidence_contract import (
    evidence_bundle_text as _evidence_bundle_text,
    final_evidence_prompt as _final_evidence_prompt,
    final_video_prompt as _final_video_prompt,
    grounded_sources_text as _grounded_sources_text,
    grounding_error as _grounding_error,
    normalize_report_citations as _normalize_report_citations,
    persist_evidence_audit as _persist_evidence_audit,
)
from .libtv_analyzer import LibTVAnalyzer, LibTVError
from .model_providers import MODEL_PROVIDER_PRESETS, normalize_model_config
from .shot_analyzers import (
    EVIDENCE_BUNDLE_SCHEMA,
    LibTVProviderAdapter,
    ShotAnalyzerRouter,
    normalize_shot_config,
    validate_shot_evidence,
)
from .video_ingest import VideoAssetCollector, VideoIngestError, is_tiktok_url


def _sha256_path(path_value: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path_value).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_config():
    config_path = PROJECT_ROOT / "config.json"
    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
    env_map = {
        'MODEL_PROVIDER': 'model_provider',
        'MODEL_PROTOCOL': 'model_protocol',
        'MODEL_API_KEY': 'model_api_key',
        'MODEL_BASE_URL': 'model_base_url',
        'MODEL_NAME': 'model_name',
        'GEMINI_API_KEY': 'gemini_api_key',
        'GEMINI_MODEL': 'gemini_model',
        'OPENROUTER_API_KEY': 'openrouter_api_key',
        'OPENROUTER_MODEL': 'openrouter_model',
        'VIRALX_SHOT_ENGINE': 'shot_engine',
        'SHOT_MODEL_SOURCE': 'shot_model_source',
        'SHOT_MODEL_API_KEY': 'shot_model_api_key',
        'SHOT_MODEL_BASE_URL': 'shot_model_base_url',
        'SHOT_MODEL_NAME': 'shot_model_name',
        'SHOT_SCENE_THRESHOLD': 'shot_scene_threshold',
        'VIRALX_VIDEO_CACHE_DIR': 'video_cache_dir',
    }
    for env_name, config_name in env_map.items():
        if os.environ.get(env_name):
            config[config_name] = os.environ[env_name]
    if os.environ.get('VIRALX_RUNTIME', '').lower() == 'edgeone':
        config.setdefault('video_cache_dir', '/tmp/viralx/video_cache')
    return config


def _tiktok_numeric_id(value: object) -> str:
    """Return only TikTok's auditable numeric post id, never an opaque media id."""
    match = re.search(r"(?<!\d)(\d{10,24})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


_MODEL_FAILURE_PREFIX_RE = re.compile(
    r"^(?:"
    r"分析(?:失败|异常)|"
    r"分析结果为空|"
    r"模型\s*API\s*没有返回最终分析|"
    r"[^：:\n]{1,48}\s+分析失败"
    r")(?:[：:]|$)"
)


def _model_result_error(report: object) -> str:
    """Recognize provider error sentinels without scanning valid report prose."""
    text = str(report or "").strip()
    if not text:
        return "模型没有返回报告"
    first_line = text.splitlines()[0].strip()
    return first_line[:240] if _MODEL_FAILURE_PREFIX_RE.match(first_line) else ""


class AICache:
    """AI 分析结果缓存"""
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.environ.get('VIRALX_CACHE_DIR')
        if cache_dir is None:
            cache_dir = (
                Path('/tmp/viralx/cache')
                if os.environ.get('VIRALX_RUNTIME', '').lower() == 'edgeone'
                else PROJECT_ROOT / "cache"
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)

    def _cache_key(self, video_id: str, analysis_type: str = "video_script") -> str:
        key_str = f"{video_id}_{analysis_type}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, video_id: str, analysis_type: str = "video_script", ttl: int = 3600) -> str | None:
        cache_file = self.cache_dir / f"{self._cache_key(video_id, analysis_type)}.json"
        if not cache_file.exists():
            return None
        try:
            age = time.time() - cache_file.stat().st_mtime
            if age > ttl:
                return None
            return json.loads(cache_file.read_text(encoding='utf-8')).get("result")
        except Exception:
            return None

    def set(self, video_id: str, result: str, analysis_type: str = "video_script"):
        try:
            cache_file = self.cache_dir / f"{self._cache_key(video_id, analysis_type)}.json"
            cache_file.write_text(json.dumps({"result": result}, ensure_ascii=False), encoding='utf-8')
        except Exception as e:
            print(f"[缓存写入失败] {e}")


class OpenAICompatibleAnalyzer:
    """OpenAI-compatible video-frame and metadata analyzer."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        provider_name: str = "模型 API",
        supports_vision: bool = True,
    ):
        config = load_config()
        self.api_key = api_key
        self.model_name = model
        self.base_url = str(base_url or "").rstrip("/")
        self.provider_name = provider_name
        self.supports_vision = supports_vision
        self.video_dir = Path(config.get('video_cache_dir', PROJECT_ROOT / "video_cache"))
        self.video_dir.mkdir(exist_ok=True, parents=True)
        self.request_attempts = self._bounded_env_int("VIRALX_MODEL_REQUEST_ATTEMPTS", 4, 1, 6)
        self.request_gap_seconds = self._bounded_env_float("VIRALX_MODEL_REQUEST_GAP_SECONDS", 2.5, 0.0, 30.0)
        self._request_lock = threading.Lock()
        self._last_request_completed_at = 0.0
        self.last_transport_attempts = []

    @staticmethod
    def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    @staticmethod
    def _bounded_env_float(name: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(os.environ.get(name, str(default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(value, maximum))

    def extract_frames(self, video_path: str, output_dir: str = None, max_frames: int = 64) -> list:
        """Extract a timeline-wide fallback sample instead of the first few frames."""
        if output_dir is None:
            source_key = hashlib.sha256(str(Path(video_path).resolve()).encode("utf-8")).hexdigest()[:12]
            output_dir = self.video_dir / "frames" / source_key
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True, parents=True)

        for f in output_dir.glob("frame_*.jpg"):
            f.unlink()

        try:
            duration = self._probe_duration(video_path)
            fps = min(2.0, max(0.1, max_frames / duration)) if duration else 1.0
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", f"fps={fps:.5f},scale='min(960,iw)':-2",
                "-q:v", "5",
                str(output_dir / "frame_%04d.jpg"),
                "-y"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"[帧提取失败] {result.stderr[:100]}")
                return []

            frames = sorted(output_dir.glob("frame_*.jpg"))[:max_frames]
            print(f"[帧提取完成] {len(frames)} 帧")
            return [str(f) for f in frames]
        except Exception as e:
            print(f"[帧提取异常] {e}")
            return []

    @staticmethod
    def _probe_duration(video_path: str) -> float:
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1", video_path,
                ],
                capture_output=True, text=True, timeout=30,
            )
            return max(float(probe.stdout.strip() or 0), 0.0)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0.0

    @staticmethod
    def _timestamp(seconds: float) -> str:
        milliseconds = max(0, int(round(seconds * 1000)))
        minutes, remainder = divmod(milliseconds, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{minutes:02d}:{secs:02d}.{millis:03d}"

    @staticmethod
    def _video_mime(path: str) -> str:
        return {
            ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
        }.get(Path(path).suffix.lower(), "video/mp4")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://viralx.metrolabs.mobi",
            "X-Title": "ViralX",
        }

    @staticmethod
    def _retry_after_seconds(response, fallback: float) -> float:
        raw = str((getattr(response, "headers", {}) or {}).get("Retry-After") or "").strip()
        try:
            return max(0.0, min(float(raw), 30.0)) if raw else fallback
        except ValueError:
            return fallback

    def _request(self, content_parts, timeout: int = 360, temperature: float = 0.1):
        """Send one model request with bounded pacing and transient-error retries."""
        retryable_statuses = {408, 425, 429, 500, 502, 503, 504, 520, 522, 524}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content_parts}],
            "max_tokens": 8192,
            "temperature": temperature,
        }
        attempts = []
        last_exception = None

        with self._request_lock:
            for attempt in range(1, self.request_attempts + 1):
                gap_remaining = self.request_gap_seconds - (time.monotonic() - self._last_request_completed_at)
                if gap_remaining > 0:
                    time.sleep(gap_remaining)
                try:
                    response = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                        timeout=timeout,
                    )
                    self._last_request_completed_at = time.monotonic()
                    status_code = int(getattr(response, "status_code", 0) or 0)
                    if status_code in retryable_statuses:
                        outcome = "retryable_http"
                    elif 200 <= status_code < 300:
                        outcome = "completed"
                    else:
                        outcome = "http_error"
                    attempts.append({"attempt": attempt, "outcome": outcome, "status_code": status_code})
                    if status_code not in retryable_statuses or attempt >= self.request_attempts:
                        self.last_transport_attempts = attempts
                        return response
                    wait_seconds = self._retry_after_seconds(response, min(2 ** attempt, 12.0))
                    print(f"[{self.provider_name} 暂时不可用] HTTP {status_code}，{wait_seconds:g} 秒后重试（{attempt}/{self.request_attempts}）")
                    time.sleep(wait_seconds)
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                    self._last_request_completed_at = time.monotonic()
                    last_exception = exc
                    attempts.append({
                        "attempt": attempt,
                        "outcome": "retryable_exception",
                        "error_type": type(exc).__name__,
                    })
                    if attempt >= self.request_attempts:
                        break
                    wait_seconds = min(2 ** attempt, 12.0)
                    print(f"[{self.provider_name} 连接中断] {wait_seconds:g} 秒后重试（{attempt}/{self.request_attempts}）")
                    time.sleep(wait_seconds)

        self.last_transport_attempts = attempts
        error_type = type(last_exception).__name__ if last_exception else "ConnectionError"
        raise requests.exceptions.ConnectionError(
            f"模型连接不稳定，已自动尝试 {len(attempts)} 次（{error_type}）"
        ) from last_exception

    @staticmethod
    def _mark_video_input(video_data: dict, **updates) -> None:
        bundle = video_data.get("evidence_bundle") or {}
        if isinstance(bundle.get("video_input"), dict):
            bundle["video_input"].update(updates)

    def _analyze_sampled_frames(self, video_data: dict, video_file_path: str, prompt: str) -> str:
        frames = self.extract_frames(video_file_path)
        if not frames:
            return f"{self.provider_name} 分析失败：原视频无法读取，且没有生成可用的全片抽帧"
        self._mark_video_input(
            video_data, status="running", transport="timeline-frames",
            frame_count=len(frames), fps="adaptive<=2",
        )
        duration = self._probe_duration(video_file_path)
        interval = duration / max(len(frames), 1) if duration else 1.0
        fallback_disclosure = (
            "\n\n=== 视觉输入降级声明 ===\n"
            "当前接口没有接受原生连续视频，下面提供的是覆盖全片时间线的带时间戳抽帧。"
            "你不能据此断言帧间连续动作、转场细节或音频事实；[VIDEO:*] 引用只能覆盖对应抽帧附近的时间。"
        )
        content_parts = [{"type": "text", "text": prompt + fallback_disclosure}]
        for index, frame in enumerate(frames):
            timestamp = self._timestamp(min(index * interval, duration or index * interval))
            encoded = base64.b64encode(Path(frame).read_bytes()).decode("ascii")
            content_parts.extend([
                {"type": "text", "text": f"[FRAME:{index + 1:03d}@{timestamp}] 原视频时间线抽帧"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
            ])
        response = self._request(content_parts)
        if response.status_code == 200:
            self._mark_video_input(
                video_data, status="completed", transport="timeline-frames",
                frame_count=len(frames), fps="adaptive<=2",
                transport_attempts=list(self.last_transport_attempts),
            )
            return response.json()["choices"][0]["message"]["content"].strip()
        self._mark_video_input(
            video_data, status="error", transport="timeline-frames",
            transport_attempts=list(self.last_transport_attempts),
        )
        return f"{self.provider_name} 分析失败：HTTP {response.status_code}"

    def analyze(self, video_data: dict, video_file_path: str = None) -> str:
        """Prefer provider-native source-video input; degrade to full-timeline frames."""
        video_id = video_data.get('video_id', '')

        try:
            if self.supports_vision and video_file_path and os.path.exists(video_file_path):
                print(f"[{self.provider_name} 原片分析] {video_id}...")
                prompt = _final_video_prompt(video_data)
                source = Path(video_file_path)
                # DashScope's OpenAI-compatible contract accepts a Base64 Data
                # URL for video_url. Keep an explicit cap so unusually large
                # files degrade to timeline-wide frames instead of exhausting RAM.
                if source.stat().st_size <= 96 * 1024 * 1024:
                    encoded = base64.b64encode(source.read_bytes()).decode("ascii")
                    content_parts = [
                        {
                            "type": "video_url",
                            "video_url": {"url": f"data:{self._video_mime(video_file_path)};base64,{encoded}"},
                            "fps": 2,
                        },
                        {"type": "text", "text": prompt},
                    ]
                    self._mark_video_input(video_data, status="running", transport="video-base64", fps=2)
                    response = self._request(content_parts)
                    if response.status_code == 200:
                        self._mark_video_input(
                            video_data, status="completed", transport="video-base64", fps=2,
                            transport_attempts=list(self.last_transport_attempts),
                        )
                        return response.json()["choices"][0]["message"]["content"].strip()
                    if response.status_code not in {400, 404, 413, 415, 422}:
                        self._mark_video_input(
                            video_data, status="error", transport="video-base64",
                            transport_attempts=list(self.last_transport_attempts),
                        )
                        return f"{self.provider_name} 分析失败：HTTP {response.status_code}"
                self._mark_video_input(video_data, status="degraded", transport="timeline-frames")
                return self._analyze_sampled_frames(video_data, video_file_path, prompt)

            return self._analyze_text_only(video_data)

        except Exception as e:
            print(f"[{self.provider_name} 分析异常] {type(e).__name__}")
            self._mark_video_input(
                video_data, status="error",
                transport_attempts=list(self.last_transport_attempts),
            )
            return f"{self.provider_name} 分析失败：{str(e)[:160]}"

    def _build_analysis_prompt(self, video_data: dict, metadata_text: str, frame_count: int) -> str:
        return f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

=== 证据协议（最高优先级） ===
你正在做证据综合，不是在补全一篇营销文章。每条关于原视频的具体事实必须在句末标注来源：
- 平台标题、作者和互动数据用 [META:title] 或 [META:metrics]
- 评论正文和标签只能分别来自 [META:comments]、[META:hashtags]；标为“未采集”时禁止推断
- 字幕或 ASR 只能引用 [TK:transcript]；歌词不得冒充商品台词
- 画面、动作、镜头、字幕和声音只允许引用 [LIBTV:shot] 或本次直接看到的 [FRAME:sample]
- 营销解释必须明确写“推断”，并同时引用支撑它的事实来源
- 复刻脚本必须按原片时间轴做高保真结构迁移；保留段落顺序、时长比例、镜头功能、节奏和视觉效果，只替换目标产品与不可复用资产
- 不得擅自发明原片或产品资料未支持的功能、场景、控制方式、价格、效果或用户反馈
- 证据不足的栏目必须写“未采集/无法判断”，禁止用常识填空

=== 可引用证据源 ===
{_grounded_sources_text(video_data)}

=== 视频数据 ===
{metadata_text}

=== 视频帧 ===
视频共提取了 {frame_count} 帧图片，代表每秒的画面。

=== 你的任务 ===
1. 仔细观看这些视频帧
2. 不要复述画面内容（用户自己有眼睛），重点分析为什么能爆
3. 输出结构化深度拆解报告

请严格按照以下格式输出 Markdown：

## 🎯 核心卖点

| 卖点层级 | 具体内容 | 呈现方式 |
|---------|---------|---------|
| **痛点解决** | （视频解决了什么痛点） | （如何呈现的：文字/画面/配音） |
| **核心优势** | （产品最大卖点是什么） | （用了什么词/表达方式） |
| **价值感知** | （让用户觉得值在哪） | （如何传达性价比） |
| **效果承诺** | （使用后的美好结果） | （如何可视化呈现） |
| **购买便利** | （如何引导购买） | （链接/话术等） |
| **信任建立** | （如何让人相信） | （品牌背书/测评/展示等） |

### 卖点提炼技巧
- （总结2-3个最核心的卖点表达技巧，用**强调**标注关键词）

---

## 🎬 视听语言

### 标题语言结构

```
（用箭头图展示标题的结构层次）
```

### 标签策略分析

| 标签类型 | 数量 | 具体标签 | 覆盖人群 |
| ---- | --- | ----- | ----- |
| 平台电商 | X个 | #XXX #XXX | XXX用户 |
| 产品品类 | X个 | #XXX #XXX | XXX用户 |
| 生活方式 | X个 | #XXX #XXX | XXX用户 |
| 内容类型 | X个 | #XXX #XXX | XXX用户 |
| 价格敏感 | X个 | #XXX | XXX用户 |

**标签特点**：只根据实际标签判断；没有标签证据时写“未采集” [META:hashtags]

---

## 💬 用户反馈洞察

### 互动数据解读

| 指标 | 数值 | 基准比 | 数据含义 |
| --- | --- | ----- | ----- |
| 点赞 | X | 100% | 基础认可度 |
| 评论 | X | X% | 低/中/高，说明什么 |
| 分享 | X | X% | 超高/正常/低分享率 |

### 用户行为证据

**① 评论反映的真实需求（仅在有评论正文时填写）**
```
✓ 需求1
✓ 需求2
```

**② 分享驱动因素**（如果有高分享率）
```
📌 驱动1
```

### 用户潜在关注点（无评论正文时只能标为待验证假设）

| 关注维度 | 推测热点问题 | 优先级 |
|---------|-------------| ------ |

---

## 📝 高保真结构迁移：复刻执行脚本

执行目标：尽可能复现原片已经验证的结构、节奏与视觉效果；不是自由创意延伸。

### 迁移边界
用“必须保留 / 可以替换 / 禁止新增”三栏说明边界。

### 逐段执行表
每段必须包含：原片时间段与证据引用、目标片时间段、镜头景别与机位/运镜、画面动作、目标产品替换、台词/字幕、声音、光线/视觉效果、转场、CTA、执行备注。
段落顺序与总时长应尽量贴近原片；缺少产品资料时写“待补充产品资料”，不得擅自发明功能或效果。

---

## 📊 拆解总结

| 维度 | 核心发现 | 可复用技巧 |
|-----|---------|-----------|
| **卖点** | | |
| **语言** | | |
| **标签** | | |
| **数据** | | |
| **洞察** | | |

---
*拆解完毕*"""

    def _build_metadata_text(self, video_data: dict) -> str:
        comments_text = ""
        if video_data.get('comments_data') and len(video_data['comments_data']) > 0:
            comments_list = [f"- {c['text']} (👍{c['likes']})" for c in video_data['comments_data'][:15]]
            comments_text = "\n".join(comments_list)

        return f"""视频标题: {video_data.get('title', '') or '无标题'}
作者: @{video_data.get('author', 'unknown')}
视频时长: {video_data.get('duration', '未知')} 秒
点赞: {video_data.get('likes', 0):,}
评论数: {video_data.get('comments', 0):,}
分享数: {video_data.get('shares', 0):,}
播放量: {video_data.get('views', 0):,}

高赞评论:
{comments_text or '（无评论数据）'}

=== ViralX 统一证据包 ===
{_evidence_bundle_text(video_data)}"""

    def _analyze_text_prompt(self, video_data: dict) -> str:
        return _final_evidence_prompt(video_data)

    def grounding_error(self, report: str, video_data: dict | None = None) -> str:
        return _grounding_error(report, video_data)

    def _analyze_text_only(self, video_data: dict) -> str:
        """纯文本分析（无视频文件时）"""
        prompt = self._analyze_text_prompt(video_data)

        try:
            resp = self._request(prompt, timeout=120)
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            else:
                return f"{self.provider_name} 分析失败：HTTP {resp.status_code}"
        except Exception as e:
            return f"{self.provider_name} 分析失败：{str(e)[:100]}"


class OpenRouterAnalyzer(OpenAICompatibleAnalyzer):
    """Backward-compatible OpenRouter constructor."""

    def __init__(self, api_key: str = "", model: str = "openrouter/auto"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=MODEL_PROVIDER_PRESETS["openrouter"]["base_url"],
            provider_name="OpenRouter",
            supports_vision=True,
        )


class AnthropicCompatibleAnalyzer:
    """Anthropic Messages-compatible analyzer with sampled video frames."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        provider_name: str = "Anthropic Claude",
        supports_vision: bool = True,
    ):
        self.api_key = api_key
        self.model_name = model
        self.base_url = str(base_url or "").rstrip("/")
        self.provider_name = provider_name
        self.supports_vision = supports_vision
        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120,
        )
        self.prompt_helper = OpenAICompatibleAnalyzer(
            api_key="",
            model=model,
            base_url="https://example.invalid",
            provider_name=provider_name,
            supports_vision=supports_vision,
        )

    @staticmethod
    def _extract_text(message) -> str:
        return "".join(
            block.text
            for block in (message.content or [])
            if getattr(block, "type", "") == "text"
        ).strip()

    def _request(self, content: list) -> str:
        message = self.client.messages.create(
            model=self.model_name,
            max_tokens=8192,
            temperature=0.7,
            messages=[{"role": "user", "content": content}],
        )
        return self._extract_text(message) or "分析结果为空"

    def analyze(self, video_data: dict, video_file_path: str = None) -> str:
        frames = []
        if self.supports_vision and video_file_path and os.path.exists(video_file_path):
            frames = self.prompt_helper.extract_frames(video_file_path)
        prompt = (
            _final_video_prompt(video_data) + (
                "\n\n=== 视觉输入声明 ===\n"
                "当前接口接收的是覆盖全片时间线的带时间戳抽帧，不是原生连续视频。"
                "不得推断帧间动作、转场或音频；[VIDEO:*] 只能引用对应抽帧附近的时间。"
            )
            if frames
            else self.prompt_helper._analyze_text_prompt(video_data)
        )
        content = [{"type": "text", "text": prompt}]
        selected_frames = frames[:24]
        duration = self.prompt_helper._probe_duration(video_file_path) if selected_frames else 0.0
        interval = duration / max(len(selected_frames), 1) if duration else 1.0
        for index, frame in enumerate(selected_frames):
            timestamp = self.prompt_helper._timestamp(min(index * interval, duration or index * interval))
            content.extend([{
                "type": "text",
                "text": f"[FRAME:{index + 1:03d}@{timestamp}] 原视频时间线抽帧",
            }, {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(Path(frame).read_bytes()).decode("ascii"),
                },
            }])
        try:
            return self._request(content)
        except Exception as exc:
            if frames:
                try:
                    return self._request([{"type": "text", "text": self.prompt_helper._analyze_text_prompt(video_data)}])
                except Exception as retry_exc:
                    exc = retry_exc
            print(f"[{self.provider_name} 分析异常] {type(exc).__name__}")
            return f"{self.provider_name} 分析失败：{str(exc)[:100]}"


class GeminiAnalyzer:
    """Gemini 多模态分析器（支持视频 + 文本）"""

    def __init__(self, api_key: str = None, model: str = "gemini-3.7-flash"):
        config = load_config()
        self.api_key = api_key or config.get('gemini_api_key', '')
        self.model_name = model or config.get('gemini_model', 'gemini-3.7-flash')
        self.video_dir = Path(config.get('video_cache_dir', PROJECT_ROOT / "video_cache"))
        self.video_dir.mkdir(exist_ok=True)
        self.client = genai.Client(api_key=self.api_key)

    def analyze(self, video_data: dict, video_file_path: str = None) -> str:
        """用 Gemini 分析视频 + 文本数据"""
        video_id = video_data.get('video_id', '')

        metadata_text = self._build_metadata_text(video_data)

        try:
            if video_file_path and os.path.exists(video_file_path):
                print(f"[Gemini 多模态分析] {video_id}...")
                uploaded_file = self.client.files.upload(file=video_file_path)
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded_file = self.client.files.get(name=uploaded_file.name)

                prompt = _final_video_prompt(video_data)

                _legacy_prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

=== 视频数据 ===
{metadata_text}

=== 你的任务 ===
1. 仔细观看这个TikTok视频
2. 不要复述画面内容（用户自己有眼睛），重点分析为什么能爆
3. 输出结构化深度拆解报告

请严格按照以下格式输出 Markdown：

## 🎯 核心卖点

| 卖点层级 | 具体内容 | 呈现方式 |
|---------|---------|---------|
| **痛点解决** | （视频解决了什么痛点） | （如何呈现的：文字/画面/配音） |
| **核心优势** | （产品最大卖点是什么） | （用了什么词/表达方式） |
| **价值感知** | （让用户觉得值在哪） | （如何传达性价比） |
| **效果承诺** | （使用后的美好结果） | （如何可视化呈现） |
| **购买便利** | （如何引导购买） | （链接/话术等） |
| **信任建立** | （如何让人相信） | （品牌背书/测评/展示等） |

### 卖点提炼技巧
- （总结2-3个最核心的卖点表达技巧，用**强调**标注关键词）

---

## 🎬 视听语言

### 标题语言结构

```
（用箭头图展示标题的结构层次）
```

### 标签策略分析

| 标签类型 | 数量 | 具体标签 | 覆盖人群 |
| ---- | --- | ----- | ----- |
| 平台电商 | X个 | #XXX #XXX | XXX用户 |
| 产品品类 | X个 | #XXX #XXX | XXX用户 |
| 生活方式 | X个 | #XXX #XXX | XXX用户 |
| 内容类型 | X个 | #XXX #XXX | XXX用户 |
| 价格敏感 | X个 | #XXX | XXX用户 |

**标签特点**：精准垂直，覆盖"搜索-种草-购买"全链路

---

## 💬 用户反馈洞察

### 互动数据解读

| 指标 | 数值 | 基准比 | 数据含义 |
| --- | --- | ----- | ----- |
| 点赞 | X | 100% | 基础认可度 |
| 评论 | X | X% | 低/中/高，说明什么 |
| 分享 | X | X% | 超高/正常/低分享率 |

### 用户行为推断

**① 评论反映的真实需求**
```
✓ 需求1
✓ 需求2
```

**② 分享驱动因素**（如果有高分享率）
```
📌 驱动1
```

### 用户潜在关注点

| 关注维度 | 推测热点问题 | 优先级 |
|---------|-------------| ------ |

---

## 📝 翻拍脚本

### 版本一：产品展示型（{video_data.get('duration', 'X')}秒）

```
【开场钩子 - 0:00-0:0X】
画面：（描述）
配音：（暗示什么情绪/痛点）

【痛点引入 - 0:0X-0:0X】
画面：
配音：

【解决方案 - 0:0X-0:0X】
画面：
配音：

【卖点轰炸 - 0:0X-0:0X】
画面：
配音/字幕：（核心卖点）

【效果展示 - 0:0X-0:0X】
画面：（如何展示效果）

【购买引导 - 0:0X-0:XX】
画面：
文字：
```

### 版本二：对比测评型（X秒）
（类似结构）

### 版本三：情绪共鸣型（15秒快剪）
（类似结构）

---

## 📊 拆解总结

| 维度 | 核心发现 | 可复用技巧 |
|-----|---------|-----------|
| **卖点** | | |
| **语言** | | |
| **标签** | | |
| **数据** | | |
| **洞察** | | |

---
*拆解完毕*"""

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[uploaded_file, prompt],
                    config={
                        "temperature": 0.7,
                        "max_output_tokens": 8192,
                    }
                )
                result = response.text.strip() if hasattr(response, 'text') and response.text else "分析结果为空"

                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

                return result
            else:
                return self._analyze_text_only(video_data)

        except Exception as e:
            print(f"[Gemini 分析失败] {e}")
            return f"Gemini 分析失败: {str(e)[:100]}"

    def _build_metadata_text(self, video_data: dict) -> str:
        comments_text = ""
        if video_data.get('comments_data') and len(video_data['comments_data']) > 0:
            comments_list = [f"- {c['text']} (👍{c['likes']})" for c in video_data['comments_data'][:15]]
            comments_text = "\n".join(comments_list)

        return f"""视频标题: {video_data.get('title', '') or '无标题'}
作者: @{video_data.get('author', 'unknown')}
视频时长: {video_data.get('duration', '未知')} 秒
点赞: {video_data.get('likes', 0):,}
评论数: {video_data.get('comments', 0):,}
分享数: {video_data.get('shares', 0):,}
播放量: {video_data.get('views', 0):,}

高赞评论:
{comments_text or '（无评论数据）'}

=== ViralX 统一证据包 ===
{_evidence_bundle_text(video_data)}"""

    def _analyze_text_only(self, video_data: dict) -> str:
        """纯文本分析（无视频文件时）"""
        prompt = _final_evidence_prompt(video_data)
        _legacy_prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

{self._build_metadata_text(video_data)}

=== 你的任务 ===
基于以上数据进行分析，只能分析数据中提供的内容：
- 不要编造视频画面
- 不要逐秒描述画面（用户有眼睛）
- 重点分析：为什么这个视频能爆？它做对了什么？
- 输出结构化深度拆解报告

请用 Markdown 格式输出：

## 🎯 核心卖点

| 卖点层级 | 具体内容 | 呈现方式 |
|---------|---------|---------|
| **痛点解决** | （从标题/评论推断） | （如何呈现） |
| **核心优势** | （最大卖点） | （用了什么词） |
| **价值感知** | （值在哪） | （如何传达） |
| **效果承诺** | （使用结果） | （如何可视化） |
| **购买便利** | （如何引导） | （话术） |
| **信任建立** | （如何让人信） | （背书/展示） |

### 卖点提炼技巧
- （总结2-3个核心表达技巧）

---

## 💬 用户反馈洞察

### 互动数据解读

| 指标 | 数值 | 基准比 | 数据含义 |
| --- | --- | ----- | ----- |
| 点赞 | X | 100% | 基础认可度 |
| 评论 | X | X% | 低/中/高，说明什么 |
| 分享 | X | X% | 超高/正常/低分享率 |

### 用户行为推断

**① 评论反映的真实需求**
```
✓ 需求1
✓ 需求2
```

### 用户潜在关注点

| 关注维度 | 推测热点问题 | 优先级 |
|---------|-------------| ------ |

---

## 🔥 爆款逻辑推断

- 标题：暗示了___痛点/欲望
- 评论：反映___真实需求
- 互动数据：透露___信息

---

## 📝 翻拍框架（基于推断的逻辑）

| 维度 | 内容 |
|-----|-----|
| **核心卖点定位** | |
| **开场模式** | |
| **信任建立路径** | |
| **转化节奏** | |

---
*拆解完毕*"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"temperature": 0.7, "max_output_tokens": 8192}
            )
            return response.text.strip() if hasattr(response, 'text') and response.text else "分析结果为空"
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"


class MiniMaxAnalyzer:
    """MiniMax 纯文本分析器"""

    def __init__(self, api_key: str = "", base_url: str = None, model: str = None):
        config = load_config()
        self.api_key = api_key or config.get('minimax_api_key', '')
        self.base_url = base_url or config.get('minimax_base_url', 'https://api.minimaxi.com/anthropic')
        self.model = model or config.get('minimax_model', 'MiniMax-M2.7')
        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60,
        )

    def _build_prompt(self, video_data: dict) -> str:
        duration = video_data.get('duration', 0)
        comments_text = ""
        has_comments = False
        if video_data.get('comments_data') and len(video_data.get('comments_data', [])) > 0:
            comments_list = [f"- {c['text']} (👍{c['likes']})" for c in video_data['comments_data'][:15]]
            comments_text = "\n".join(comments_list)
            has_comments = True

        if has_comments:
            comments_block = f"高赞用户评论：\n{comments_text}"
        else:
            comments_block = "（无评论数据）"

        return f"""角色设定：你是资深TikTok电商短视频拆解专家，擅长深度结构化分析。

重要规则：
1. 只分析视频资料中提供的数据，禁止编造视频画面、台词、或时长。
2. 不要逐秒描述画面（用户有眼睛），重点分析：为什么能爆？
3. 如果某项数据未提供（如评论为空），请明确说明「数据不足，无法分析」。
4. 输出结构化深度拆解报告。

=== 视频数据 ===
标题: {video_data.get('title', '') or '（无标题）'}
作者: @{video_data.get('author', 'unknown')}
时长: {f"{duration} 秒" if duration > 0 else '未知'}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}
分享: {video_data.get('shares', 0):,}
播放: {video_data.get('views', 0):,}

{comments_block}

=== 输出要求 ===

## 🎯 核心卖点

| 卖点层级 | 具体内容 | 呈现方式 |
|---------|---------|---------|
| **痛点解决** | （从标题/评论推断） | （如何呈现） |
| **核心优势** | （最大卖点） | （用了什么词） |
| **价值感知** | （值在哪） | （如何传达） |
| **效果承诺** | （使用结果） | （如何可视化） |
| **购买便利** | （如何引导） | （话术） |
| **信任建立** | （如何让人信） | （背书/展示） |

### 卖点提炼技巧
- （总结2-3个核心表达技巧）

---

## 💬 用户反馈洞察

### 互动数据解读

| 指标 | 数值 | 基准比 | 数据含义 |
| --- | --- | ----- | ----- |
| 点赞 | X | 100% | 基础认可度 |
| 评论 | X | X% | 低/中/高，说明什么 |
| 分享 | X | X% | 超高/正常/低分享率 |

### 用户行为推断

**① 评论反映的真实需求** {"" if has_comments else "（无评论数据）"}
```
{comments_text if has_comments else "（无评论数据）"}
```

### 用户潜在关注点

| 关注维度 | 推测热点问题 | 优先级 |
|---------|-------------| ------ |

---

## 🔥 爆款逻辑推断

- 标题：暗示了___痛点/欲望
- 评论：反映___真实需求
- 互动数据：透露___信息

---

## 📝 翻拍框架（基于推断的逻辑）

| 维度 | 内容 |
|-----|-----|
| **核心卖点定位** | |
| **开场模式** | |
| **信任建立路径** | |
| **转化节奏** | |

---
*拆解完毕*"""

class AIAnalyzer:
    """Evidence-first analyzer: TK Note -> source video -> grounded synthesis."""

    _cache = None
    MAX_CONCURRENT = 5
    REQUEST_TIMEOUT = 120

    def __init__(
        self,
        api_key: str = "",
        base_url: str = None,
        model: str = None,
        analysis_mode: str = 'pipeline',
        model_provider: str = '',
        model_protocol: str = '',
        model_api_key: str = '',
        model_base_url: str = '',
        model_name: str = '',
        gemini_api_key: str = '',
        gemini_model: str = '',
        openrouter_api_key: str = '',
        openrouter_model: str = '',
        video_collector=None,
        video_cache_dir: str = '',
        tk_note_asr_backend: str = '',
        tk_note_language: str = '',
        tk_note_cookies_from_browser: str = '',
        tk_note_proxy: str = '',
        tk_note_timeout: float = None,
        shot_engine: str = '',
        shot_model_source: str = '',
        shot_model_api_key: str = '',
        shot_model_base_url: str = '',
        shot_model_name: str = '',
        shot_scene_threshold: float = None,
        shot_router=None,
    ):
        config = load_config()

        self.api_key = api_key or config.get('minimax_api_key', '')
        self.base_url = base_url or config.get('minimax_base_url', 'https://api.minimaxi.com/anthropic')
        self.model = model or config.get('minimax_model', 'MiniMax-M2.7')
        requested_mode = analysis_mode or config.get('analysis_mode', 'pipeline')
        model_config = {
            **config,
            'analysis_mode': requested_mode,
            'model_provider': model_provider or config.get('model_provider', ''),
            'model_protocol': model_protocol or config.get('model_protocol', ''),
            'model_api_key': model_api_key or config.get('model_api_key', ''),
            'model_base_url': model_base_url or config.get('model_base_url', ''),
            'model_name': model_name or config.get('model_name', ''),
            'gemini_api_key': gemini_api_key or config.get('gemini_api_key', ''),
            'gemini_model': gemini_model or config.get('gemini_model', ''),
            'openrouter_api_key': openrouter_api_key or config.get('openrouter_api_key', ''),
            'openrouter_model': openrouter_model or config.get('openrouter_model', ''),
            'minimax_api_key': self.api_key,
            'minimax_base_url': self.base_url,
            'minimax_model': self.model,
        }
        model_config = normalize_model_config(
            model_config,
            allow_private_custom=os.environ.get('VIRALX_RUNTIME', '').lower() != 'edgeone',
        )
        self.analysis_mode = model_config['analysis_mode']
        self.model_provider = model_config['model_provider']
        self.model_protocol = model_config['model_protocol']
        self.model_api_key = model_config['model_api_key']
        self.model_base_url = model_config['model_base_url']
        self.model_name = model_config['model_name']
        self.model_supports_vision = bool(model_config.get('model_supports_vision'))
        self.model_config_error = model_config.get('model_config_error', '')
        self.libtv_concurrency = max(1, min(int(config.get('libtv_concurrency', 2)), 5))
        self.video_collector = video_collector or VideoAssetCollector(
            cache_dir=video_cache_dir or config.get('video_cache_dir', './video_cache'),
            tk_note_asr_backend=tk_note_asr_backend or config.get('tk_note_asr_backend', 'auto'),
            tk_note_language=tk_note_language or config.get('tk_note_language', 'auto'),
            tk_note_cookies_from_browser=(
                tk_note_cookies_from_browser
                or config.get('tk_note_cookies_from_browser', '')
            ),
            tk_note_proxy=tk_note_proxy or config.get('tk_note_proxy', ''),
            tk_note_timeout=(
                tk_note_timeout
                if tk_note_timeout is not None
                else config.get('tk_note_timeout', 1800)
            ),
        )

        self.use_pipeline = self.analysis_mode == 'pipeline'
        # Compatibility aliases for older callers. The product no longer
        # treats LibTV and the model API as mutually exclusive destinations.
        self.use_libtv = self.use_pipeline
        self.use_model = self.use_pipeline
        self.libtv = LibTVAnalyzer()
        shot_config = {
            **model_config,
            'shot_engine': shot_engine or config.get('shot_engine', 'direct'),
            'shot_model_source': shot_model_source or config.get('shot_model_source', 'inherit'),
            'shot_model_api_key': shot_model_api_key or config.get('shot_model_api_key', ''),
            'shot_model_base_url': shot_model_base_url or config.get('shot_model_base_url', ''),
            'shot_model_name': shot_model_name or config.get('shot_model_name', ''),
            'shot_scene_threshold': (
                shot_scene_threshold
                if shot_scene_threshold is not None
                else config.get('shot_scene_threshold', 27.0)
            ),
        }
        self.shot_config = normalize_shot_config(shot_config)
        self.shot_router = shot_router or ShotAnalyzerRouter(
            shot_config,
            libtv=LibTVProviderAdapter(self.libtv),
        )
        pipeline_label = (
            "原片视觉模型 -> 证据终审"
            if self.shot_config['engine'] == 'direct'
            else f"{self.shot_config['engine']} 专业镜头证据 -> 原片视觉模型终审"
        )
        print(f"[AIAnalyzer] 串联链路: TK Note -> {pipeline_label}")

        self.model_analyzer = None
        self.gemini = None
        self.openrouter = None
        if self.model_api_key and self.model_name and self.model_base_url and not self.model_config_error:
            preset = MODEL_PROVIDER_PRESETS[self.model_provider]
            provider_label = preset['label']
            if self.model_provider == 'gemini':
                self.model_analyzer = GeminiAnalyzer(
                    api_key=self.model_api_key,
                    model=self.model_name,
                )
                self.gemini = self.model_analyzer
            elif self.model_protocol == 'anthropic':
                self.model_analyzer = AnthropicCompatibleAnalyzer(
                    api_key=self.model_api_key,
                    model=self.model_name,
                    base_url=self.model_base_url,
                    provider_name=provider_label,
                    supports_vision=bool(preset.get('vision', True)),
                )
            else:
                self.model_analyzer = OpenAICompatibleAnalyzer(
                    api_key=self.model_api_key,
                    model=self.model_name,
                    base_url=self.model_base_url,
                    provider_name=provider_label,
                    supports_vision=bool(preset.get('vision', True)),
                )
                if self.model_provider == 'openrouter':
                    self.openrouter = self.model_analyzer
            print(f"[AIAnalyzer] 模型 API: {provider_label} ({self.model_name})")

        # MiniMax remains isolated for the legacy script-variant endpoint only.
        self.client = None
        if self.api_key:
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.REQUEST_TIMEOUT,
            )

        if AIAnalyzer._cache is None:
            AIAnalyzer._cache = AICache()

    @property
    def cache(self) -> AICache:
        return AIAnalyzer._cache

    def _extract_text(self, msg) -> str:
        """从 MiniMax 响应中提取文本"""
        text = ""
        if msg.content:
            for block in msg.content:
                if not hasattr(block, 'type'):
                    continue
                if block.type == "text":
                    text += block.text
                elif block.type == "thinking" and not text:
                    text += block.thinking
        return text.strip()

    def analyze_video_script(self, video_data: dict, video_url: str = None, use_cache: bool = False, force_collect: bool = False) -> str:
        """分析视频并返回报告文本；详细提供方状态由 details 方法返回。"""
        return self.analyze_video_script_details(
            video_data, video_url=video_url, use_cache=use_cache, force_collect=force_collect
        )['analysis']

    def _analyze_legacy_video_script_details(self, video_data: dict, video_url: str = None, use_cache: bool = False, force_collect: bool = False) -> dict:
        """分析视频并返回报告、提供方、会话与画布元数据。"""
        video_id = video_data.get('video_id', '')
        video_file_path = None
        acquisition_details = {}

        if self.use_libtv:
            if not self.libtv.available:
                return {
                    'analysis': 'LibTV 拉片失败：未找到官方 LibTV CLI，请先安装后在设置页连接',
                    'analysis_provider': 'libtv',
                    'libtv_status': 'error',
                }
            if not self.libtv.is_authenticated():
                return {
                    'analysis': 'LibTV 拉片失败：尚未登录，请在设置页点击“连接 LibTV”完成网页授权',
                    'analysis_provider': 'libtv',
                    'libtv_status': 'error',
                }
            if not video_url:
                return {
                    'analysis': 'LibTV 拉片失败：缺少可下载的视频链接',
                    'analysis_provider': 'libtv',
                    'libtv_status': 'error',
                }
            try:
                asset = self.video_collector.prepare(video_url, video_id, force=force_collect)
                video_file_path = asset.video_file
                acquisition_details = asset.analysis_details()
                video_data.update(asset.video_fields())
            except VideoIngestError as exc:
                ingest_error = {
                    'acquisition_provider': 'tk-note' if is_tiktok_url(video_url) else 'yt-dlp',
                    ('tk_note_status' if is_tiktok_url(video_url) else 'video_ingest_status'): 'error',
                }
                return {
                    'analysis': f'LibTV 拉片失败：{exc}',
                    'analysis_provider': 'libtv',
                    'libtv_status': 'error',
                    **ingest_error,
                }
            try:
                result = self.libtv.analyze(video_file_path, user_request='逐帧拉片')
                details = result.to_dict()
                return {
                    'analysis': details.pop('analysis'),
                    'analysis_provider': 'libtv',
                    'libtv_status': details.pop('status'),
                    'libtv_session_id': details.pop('session_id'),
                    'libtv_project_uuid': details.pop('project_uuid'),
                    'libtv_project_url': details.pop('project_url'),
                    'libtv_result_urls': details.pop('result_urls'),
                    **acquisition_details,
                }
            except LibTVError as exc:
                return {
                    'analysis': f'LibTV 拉片失败：{exc}',
                    'analysis_provider': 'libtv',
                    'libtv_status': 'error',
                    **acquisition_details,
                }

        if self.use_model:
            if self.model_config_error:
                return {
                    'analysis': f'模型 API 配置无效：{self.model_config_error}',
                    'analysis_provider': self.model_provider,
                    'model_status': 'error',
                }
            if not self.model_api_key:
                return {
                    'analysis': '模型 API 分析失败：未配置 API Key，请先在设置页填写',
                    'analysis_provider': self.model_provider,
                    'model_status': 'error',
                }
            if not self.model_name:
                return {
                    'analysis': '模型 API 分析失败：未填写模型名称',
                    'analysis_provider': self.model_provider,
                    'model_status': 'error',
                }
            if not self.model_analyzer:
                return {
                    'analysis': '模型 API 分析失败：当前供应商配置无法初始化',
                    'analysis_provider': self.model_provider,
                    'model_status': 'error',
                }
            if video_url:
                try:
                    asset = self.video_collector.prepare(video_url, video_id, force=force_collect)
                    video_file_path = asset.video_file
                    acquisition_details = asset.analysis_details()
                    video_data.update(asset.video_fields())
                except VideoIngestError as exc:
                    acquisition_details = {
                        'acquisition_provider': 'tk-note' if is_tiktok_url(video_url) else 'yt-dlp',
                        ('tk_note_status' if is_tiktok_url(video_url) else 'video_ingest_status'): 'error',
                        'acquisition_note': f'视频采集失败，已改用元数据分析：{str(exc)[:120]}',
                    }
            result = self.model_analyzer.analyze(video_data, video_file_path)
            failed = bool(_model_result_error(result))
            return {
                'analysis': result,
                'analysis_provider': self.model_provider,
                'model_status': 'error' if failed else 'completed',
                **acquisition_details,
            }

        return {
            'analysis': '分析失败：请选择 LibTV 或模型 API 分析模式',
            'analysis_provider': self.analysis_mode,
            'model_status': 'error',
        }

    def analyze_video_script_details(
        self,
        video_data: dict,
        video_url: str = None,
        use_cache: bool = False,
        force_collect: bool = False,
        progress_callback=None,
        media_url: str = None,
    ) -> dict:
        """Run collection, auditable shot evidence, evidence merge, then synthesis."""
        video_id = video_data.get('video_id', '')
        expected_video_id = str(video_id or '')
        acquisition_provider = 'tk-note' if is_tiktok_url(video_url or '') else 'yt-dlp'

        def emit(stage, status, label, progress):
            if progress_callback:
                progress_callback({
                    'status': 'progress',
                    'stage': stage,
                    'stage_status': status,
                    'stage_label': label,
                    'stage_progress': progress,
                })

        collection_only = self.shot_config['engine'] == 'skip'
        direct_video_mode = self.shot_config['engine'] == 'direct'
        if not collection_only and not self.model_api_key:
            return {
                'analysis': '串联分析失败：最终模型 API Key 尚未配置',
                'analysis_provider': self.model_provider,
                'pipeline_stage': 'final-analysis',
                'pipeline_status': 'error',
                'model_status': 'error',
            }
        if not collection_only and self.model_config_error:
            return {
                'analysis': f'串联分析失败：模型 API 配置无效：{self.model_config_error}',
                'analysis_provider': self.model_provider,
                'pipeline_stage': 'final-analysis',
                'pipeline_status': 'error',
                'model_status': 'error',
            }
        if not collection_only and not self.model_analyzer:
            return {
                'analysis': '串联分析失败：最终模型 API 尚未配置或无法初始化',
                'analysis_provider': self.model_provider,
                'pipeline_stage': 'final-analysis',
                'pipeline_status': 'error',
                'model_status': 'error',
            }
        if not video_url:
            return {
                'analysis': '串联分析失败：缺少可采集的视频链接',
                'analysis_provider': 'pipeline',
                'pipeline_stage': 'collection',
                'pipeline_status': 'error',
                'tk_note_status': 'error',
                'shot_status': 'not_run',
                'model_status': 'not_run',
            }

        emit('collection', 'running', 'TK Note 正在采集原片、字幕与元数据', 24)
        try:
            prepare_kwargs = {'force': force_collect}
            if media_url:
                prepare_kwargs['media_url'] = media_url
            asset = self.video_collector.prepare(video_url, video_id, **prepare_kwargs)
            video_file_path = asset.video_file
            acquisition_details = asset.analysis_details()
            video_data.update(asset.video_fields())
        except VideoIngestError as exc:
            emit('collection', 'error', 'TK Note 证据采集失败，后续步骤未运行', 40)
            return {
                'analysis': f'TK Note 证据采集失败：{exc}',
                'analysis_provider': 'pipeline',
                'pipeline_stage': 'collection',
                'pipeline_status': 'error',
                'acquisition_provider': acquisition_provider,
                'acquisition_error_code': getattr(exc, 'code', 'collection_failed'),
                'tk_note_task_log': getattr(exc, 'task_log', ''),
                ('tk_note_status' if acquisition_provider == 'tk-note' else 'video_ingest_status'): 'error',
                'shot_provider': self.shot_config['engine'],
                'shot_status': 'not_run',
                'evidence_status': 'missing',
                'model_status': 'not_run',
            }

        expected_numeric_id = _tiktok_numeric_id(expected_video_id) or _tiktok_numeric_id(video_url)
        actual_numeric_id = (
            _tiktok_numeric_id(getattr(asset, 'video_id', ''))
            or _tiktok_numeric_id((getattr(asset, 'metadata', {}) or {}).get('video_id'))
            or _tiktok_numeric_id(getattr(asset, 'source_url', ''))
        )
        if is_tiktok_url(video_url or '') and expected_numeric_id and actual_numeric_id != expected_numeric_id:
            emit('collection', 'error', '原片身份校验失败，流水线已阻断', 40)
            return {
                'analysis': (
                    'TK Note 下载结果与搜索候选不是同一条 TikTok 视频；'
                    '最终模型未调用，避免分析错误原片。'
                ),
                'analysis_provider': 'pipeline',
                'pipeline_stage': 'collection',
                'pipeline_status': 'error',
                'identity_status': 'mismatch',
                'expected_video_id': expected_numeric_id,
                'actual_video_id': actual_numeric_id or 'missing',
                'model_status': 'blocked',
                **acquisition_details,
            }

        emit('collection', 'complete', 'TK Note 证据包已保存', 40)
        engine_label = {
            'direct': f'{self.model_name or self.model_provider} 原片视觉理解',
            'auto': 'ShotLoom Core（失败时回退 LibTV）',
            'shotloom': 'ShotLoom Core',
            'libtv': 'LibTV',
            'skip': '只采集模式',
        }.get(self.shot_config['engine'], self.shot_config['engine'])
        emit('shot-analysis', 'running', f'{engine_label} 正在准备视觉证据', 48)
        if direct_video_mode:
            source_hash = _sha256_path(video_file_path)
            shot_details = {
                'provider': 'direct-video',
                'model': self.model_name,
                'status': 'not_used',
                'analysis': '',
                'evidence': {},
                'block_reason': '',
                'fallback_used': False,
                'fallback_chain': [],
                'source_sha256': source_hash,
            }
            shot_evidence_error = ''
        else:
            try:
                shot_result = self.shot_router.analyze(
                    video_file_path,
                    user_request='逐镜头记录直接可见事实；不要输出营销结论',
                )
                shot_details = shot_result.to_dict()
            except Exception as exc:
                shot_details = {
                    'provider': self.shot_config['engine'],
                    'model': '',
                    'status': 'blocked',
                    'analysis': '',
                    'evidence': {},
                    'block_reason': f'{type(exc).__name__}: {str(exc)[:180]}',
                    'fallback_used': False,
                    'fallback_chain': [],
                }
            shot_evidence_error = (
                validate_shot_evidence(shot_details)
                if shot_details.get('status') == 'completed'
                else str(shot_details.get('block_reason') or '专业镜头索引没有完成')
            )
        emit(
            'shot-analysis',
            'blocked' if shot_evidence_error else 'complete',
            (
                '视觉模型将直接读取完整原视频'
                if direct_video_mode else
                '只采集模式：镜头分析与最终模型已跳过'
                if collection_only else
                f"镜头证据不可用：{shot_evidence_error[:100]}" if shot_evidence_error else
                f"{shot_details.get('provider')} 镜头证据已生成"
            ),
            68,
        )
        emit('evidence-merge', 'running', '正在合并平台、TK Note 与镜头证据', 72)

        def read_evidence(path_value, limit=60000):
            try:
                path = Path(str(path_value or ''))
                if path.is_file():
                    return path.read_text(encoding='utf-8', errors='replace')[:limit]
            except OSError:
                pass
            return ''

        tk_note_evidence = {
            'provider': acquisition_provider,
            'status': acquisition_details.get('tk_note_status') or acquisition_details.get('video_ingest_status'),
            'metadata': getattr(asset, 'metadata', {}) or {},
            'transcript': read_evidence(getattr(asset, 'transcript_path', '')),
            'transcript_source': getattr(asset, 'transcript_source', ''),
            'warnings': list(getattr(asset, 'warnings', []) or []),
            'blocked_stages': list(getattr(asset, 'blocked_stages', []) or []),
        }
        target_product = str(
            video_data.get('target_product')
            or video_data.get('search_query')
            or ''
        ).strip()
        video_input_hash = (
            shot_details.get('source_sha256')
            or ((shot_details.get('evidence') or {}).get('source') or {}).get('sha256')
            or _sha256_path(video_file_path)
        )
        evidence_bundle = {
            'schema': EVIDENCE_BUNDLE_SCHEMA,
            'visual_mode': 'direct' if direct_video_mode else 'professional',
            'target_product': target_product,
            'video_input': {
                'status': 'ready',
                'transport': 'pending',
                'provider': self.model_provider,
                'model': self.model_name,
                'source_sha256': video_input_hash,
                'file_name': Path(video_file_path).name,
            },
            'platform_evidence': {
                key: video_data.get(key)
                for key in (
                    'title', 'author', 'duration', 'likes', 'comments', 'shares', 'views',
                    'hashtags', 'comments_data',
                )
            },
            'tk_note_evidence': tk_note_evidence,
            'shot_evidence': shot_details.get('evidence') or {
                'schema': 'viralx.shot_evidence.v1',
                'provider': shot_details.get('provider'),
                'model': shot_details.get('model'),
                'status': shot_details.get('status'),
                'block_reason': shot_evidence_error,
                'shots': [],
            },
        }
        evidence_bundle['shot_evidence'].update({
            'provider': shot_details.get('provider'),
            'model': shot_details.get('model'),
            'status': shot_details.get('status'),
            'project_url': shot_details.get('project_url', ''),
        })
        video_data['evidence_bundle'] = evidence_bundle
        shot_analysis = str((evidence_bundle.get('shot_evidence') or {}).get('shot_analysis') or '')
        audit_details = _persist_evidence_audit(
            video_file_path,
            evidence_bundle,
            shot_analysis,
        )
        emit('evidence-merge', 'complete', '统一证据包已就绪', 82)

        if shot_evidence_error:
            return {
                'analysis': (
                    '只采集已完成：平台与 TK Note 证据包已保存；根据设置，未生成镜头证据和最终报告。'
                    if collection_only else
                    f'镜头证据不可用：{shot_evidence_error}。最终模型未调用，避免无证据猜测。'
                ),
                'analysis_provider': 'pipeline',
                'pipeline_stage': 'shot-analysis',
                'pipeline_status': 'blocked',
                'evidence_status': 'partial',
                'evidence_bundle': evidence_bundle,
                'shot_provider': shot_details.get('provider'),
                'shot_model': shot_details.get('model'),
                'shot_status': shot_details.get('status', 'blocked'),
                'shot_evidence_quality': (shot_details.get('evidence') or {}).get('quality', {}),
                'shot_block_reason': shot_evidence_error,
                'fallback_used': bool(shot_details.get('fallback_used')),
                'fallback_chain': shot_details.get('fallback_chain', []),
                'model_status': 'blocked',
                **audit_details,
                **acquisition_details,
            }

        emit('final-analysis', 'running', f'{self.model_provider} 正在读取原视频并进行证据终审', 86)
        try:
            final_analysis = self.model_analyzer.analyze(video_data, video_file_path)
        except Exception as exc:
            emit('final-analysis', 'error', '最终模型连接失败；已保留此前证据', 100)
            return {
                'analysis': f'最终模型连接失败（{type(exc).__name__}）。平台、TK Note 与镜头证据已保存，可稍后直接重试终审。',
                'analysis_provider': self.model_provider,
                'pipeline_stage': 'final-analysis',
                'pipeline_status': 'error',
                'evidence_status': 'merged',
                'evidence_bundle': evidence_bundle,
                'shot_provider': shot_details.get('provider'),
                'shot_model': shot_details.get('model'),
                'shot_status': shot_details.get('status', 'completed'),
                'shot_evidence_quality': (shot_details.get('evidence') or {}).get('quality', {}),
                'shot_block_reason': '',
                'fallback_used': bool(shot_details.get('fallback_used')),
                'fallback_chain': shot_details.get('fallback_chain', []),
                'model_status': 'error',
                'model_error_code': type(exc).__name__,
                **audit_details,
                **acquisition_details,
            }
        if not isinstance(final_analysis, str):
            final_analysis = ''
        audit_details.update(_persist_evidence_audit(
            video_file_path,
            evidence_bundle,
            shot_analysis,
            final_analysis,
        ))
        final_analysis = _normalize_report_citations(final_analysis, video_data)
        model_error = _model_result_error(final_analysis)
        grounding_error = "" if model_error else _grounding_error(final_analysis, video_data)
        model_failed = bool(model_error or grounding_error)
        visible_analysis = final_analysis
        if model_error:
            visible_analysis = (
                f'最终模型调用失败：{model_error}。'
                '平台、TK Note 与镜头证据已保存，可稍后直接重试终审。'
            )
        elif grounding_error:
            visible_analysis = (
                f'最终模型报告已拦截：{grounding_error}。'
                '原始输出已保存到本机审计目录，但不会作为可信分析展示；请重试。'
            )
        emit(
            'final-analysis',
            'error' if model_failed else 'complete',
            ('最终报告缺少证据引用，已拦截' if grounding_error else '最终模型分析失败')
            if model_failed else '最终报告已生成',
            100,
        )
        visual_status = ('error' if model_failed else 'completed') if direct_video_mode else shot_details.get('status', 'completed')
        return {
            'analysis': visible_analysis or '模型 API 没有返回最终分析',
            'analysis_provider': self.model_provider,
            'pipeline_stage': 'final-analysis',
            'pipeline_status': 'error' if model_failed else 'completed',
            'evidence_status': 'merged',
            'evidence_bundle': evidence_bundle,
            'shot_provider': shot_details.get('provider'),
            'shot_model': shot_details.get('model'),
            'shot_status': visual_status,
            'shot_evidence_quality': (shot_details.get('evidence') or {}).get('quality', {}),
            'shot_block_reason': '',
            'fallback_used': bool(shot_details.get('fallback_used')),
            'fallback_chain': shot_details.get('fallback_chain', []),
            'libtv_status': shot_details.get('status') if shot_details.get('provider') == 'libtv' else 'not_used',
            'libtv_session_id': shot_details.get('session_id', ''),
            'libtv_project_uuid': shot_details.get('project_uuid', ''),
            'libtv_project_url': shot_details.get('project_url', ''),
            'libtv_result_urls': shot_details.get('result_urls', []),
            'model_status': 'error' if model_failed else 'completed',
            'model_error_code': 'provider_error' if model_error else '',
            'model_grounding_error': grounding_error,
            **audit_details,
            **acquisition_details,
        }

    def resume_final_analysis(
        self,
        video_data: dict,
        progress_callback=None,
        evidence_bundle_path: str = '',
        raw_model_report_path: str = '',
        source_video_path: str = '',
    ) -> dict:
        """Retry only evidence-grounded synthesis from a server-owned checkpoint."""
        def emit(status, label, progress):
            if progress_callback:
                progress_callback({
                    'status': 'progress',
                    'stage': 'final-analysis',
                    'stage_status': status,
                    'stage_label': label,
                    'stage_progress': progress,
                })

        evidence_bundle = video_data.get('evidence_bundle') or {}
        shot_evidence = evidence_bundle.get('shot_evidence') or {}
        if evidence_bundle.get('schema') != EVIDENCE_BUNDLE_SCHEMA:
            raise ValueError('检查点中的统一证据包版本无效')
        visual_mode = str(evidence_bundle.get('visual_mode') or 'professional').lower()
        if visual_mode != 'direct':
            shot_error = validate_shot_evidence({'status': 'completed', 'evidence': shot_evidence})
            if shot_error:
                raise ValueError(f'检查点中的镜头证据不可用：{shot_error}')
        resolved_source_video_path = None
        bundle_path = Path(str(evidence_bundle_path or ''))
        explicit_source = Path(str(source_video_path or ''))
        if explicit_source.name == 'source.mp4' and explicit_source.is_file():
            expected_hash = str((evidence_bundle.get('video_input') or {}).get('source_sha256') or '')
            actual_hash = _sha256_path(explicit_source)
            if expected_hash and actual_hash != expected_hash:
                raise ValueError('检查点中的原视频与证据包哈希不一致')
            resolved_source_video_path = str(explicit_source)
        elif bundle_path.name == 'evidence-bundle.json' and bundle_path.parent.name == 'viralx-evidence':
            candidate = bundle_path.parent.parent / 'source.mp4'
            if candidate.is_file():
                expected_hash = str((evidence_bundle.get('video_input') or {}).get('source_sha256') or '')
                actual_hash = _sha256_path(candidate)
                if expected_hash and actual_hash != expected_hash:
                    raise ValueError('检查点中的原视频与证据包哈希不一致')
                resolved_source_video_path = str(candidate)
        if visual_mode == 'direct' and not resolved_source_video_path:
            raise ValueError('检查点中的原视频已不存在，不能执行原片视觉终审')

        saved_report = ''
        raw_report_path = Path(str(raw_model_report_path or ''))
        try:
            trusted_raw_report = (
                bundle_path.name == 'evidence-bundle.json'
                and bundle_path.is_file()
                and raw_report_path.name == 'final-model-report.raw.md'
                and raw_report_path.resolve().parent == bundle_path.resolve().parent
                and raw_report_path.is_file()
            )
            if trusted_raw_report:
                saved_report = raw_report_path.read_text(encoding='utf-8').strip()
        except OSError:
            saved_report = ''
        if saved_report:
            normalized_saved_report = _normalize_report_citations(saved_report, video_data)
            saved_model_error = _model_result_error(normalized_saved_report)
            saved_grounding_error = '' if saved_model_error else _grounding_error(normalized_saved_report, video_data)
            if not saved_model_error and not saved_grounding_error:
                emit('complete', '已重新校验保存的模型报告，无需再次调用模型', 100)
                return {
                    **video_data,
                    'ai_analysis': normalized_saved_report,
                    'analysis_provider': video_data.get('analysis_provider') or self.model_provider,
                    'pipeline_stage': 'final-analysis',
                    'pipeline_status': 'completed',
                    'evidence_status': 'merged',
                    'model_status': 'completed',
                    'model_error_code': '',
                    'model_grounding_error': '',
                    'shot_status': 'completed' if visual_mode == 'direct' else video_data.get('shot_status', 'completed'),
                    'retry_scope': '',
                    'evidence_bundle_path': str(bundle_path),
                    'raw_model_report_path': str(raw_report_path),
                }

        if self.model_config_error:
            raise ValueError(f'模型 API 配置无效：{self.model_config_error}')
        if not self.model_api_key or not self.model_name or not self.model_analyzer:
            raise ValueError('最终模型尚未配置完成')

        emit('running', '正在复用已保存原片与证据，仅重试模型终审', 86)
        try:
            final_analysis = self.model_analyzer.analyze(video_data, resolved_source_video_path)
        except Exception as exc:
            emit('error', '模型终审连接失败；检查点仍可继续使用', 100)
            return {
                **video_data,
                'ai_analysis': f'最终模型连接失败（{type(exc).__name__}）。已保存证据未受影响，可再次仅重试终审。',
                'analysis_provider': self.model_provider,
                'pipeline_stage': 'final-analysis',
                'pipeline_status': 'error',
                'evidence_status': 'merged',
                'model_status': 'error',
                'model_error_code': type(exc).__name__,
                'retry_scope': 'model-only',
            }

        final_analysis = final_analysis if isinstance(final_analysis, str) else ''
        audit_details = {}
        try:
            if bundle_path.name == 'evidence-bundle.json' and bundle_path.parent.name == 'viralx-evidence':
                audit_details = _persist_evidence_audit(
                    str(resolved_source_video_path or bundle_path.parent.parent / 'source.mp4'),
                    evidence_bundle,
                    str(shot_evidence.get('shot_analysis') or ''),
                    final_analysis,
                )
        except (OSError, ValueError):
            audit_details = {}

        final_analysis = _normalize_report_citations(final_analysis, video_data)
        model_error = _model_result_error(final_analysis)
        grounding_error = "" if model_error else _grounding_error(final_analysis, video_data)
        model_failed = bool(model_error or grounding_error)
        if model_error:
            visible_analysis = (
                f'最终模型调用失败：{model_error}。'
                '已保存证据未受影响，可再次仅重试终审。'
            )
        elif grounding_error:
            visible_analysis = (
                f'最终模型报告已拦截：{grounding_error}。'
                '原始输出已保存，但不会作为可信分析展示；可再次仅重试终审。'
            )
        else:
            visible_analysis = final_analysis or '模型 API 没有返回最终分析'
        emit(
            'error' if model_failed else 'complete',
            '最终报告缺少证据引用，已拦截' if grounding_error else (
                '模型终审失败；检查点仍可继续使用' if model_failed else '最终报告已生成'
            ),
            100,
        )
        return {
            **video_data,
            'ai_analysis': visible_analysis,
            'analysis_provider': self.model_provider,
            'pipeline_stage': 'final-analysis',
            'pipeline_status': 'error' if model_failed else 'completed',
            'evidence_status': 'merged',
            'model_status': 'error' if model_failed else 'completed',
            'model_error_code': 'provider_error' if model_error else '',
            'model_grounding_error': grounding_error,
            'retry_scope': 'model-only' if model_failed else '',
            **audit_details,
        }

    def _analyze_minimax(self, video_data: dict) -> str:
        """MiniMax 纯文本分析"""
        if not self.client:
            return "分析失败：未配置可用的 MiniMax API Key"
        analyzer = MiniMaxAnalyzer(self.api_key, self.base_url, self.model)
        prompt = analyzer._build_prompt(video_data)

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}]
            )
            text = self._extract_text(msg)
            result = text if text else "分析结果为空"
            return result
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"

    def batch_analyze_streaming(
        self,
        videos: list,
        max_videos: int = 5,
        video_urls: dict = None,
        product_name: str = '',
        product_info: str = '',
        force_collect: bool = False,
        progress_callback=None,
        media_urls: dict = None,
    ):
        """Analyze videos one at a time through the five-stage evidence pipeline."""
        def hot_score(v):
            return v.get('likes', 0) * 1 + v.get('comments', 0) * 5 + v.get('shares', 0) * 2

        sorted_videos = sorted(videos, key=hot_score, reverse=True)[:max_videos]
        urls = video_urls or {}
        transport_urls = media_urls or {}

        # The five evidence stages are intentionally serial per task. This keeps
        # one source file, one evidence bundle, and one final report in lockstep.
        workers = 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_video = {
                executor.submit(
                    self._analyze_video_only,
                    v,
                    urls.get(v['video_id']),
                    force_collect,
                    progress_callback,
                    transport_urls.get(v['video_id']),
                ): v
                for v in sorted_videos
            }
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    result = future.result()
                    analysis = result['analysis']
                    provider_details = {
                        key: value for key, value in result.items() if key != 'analysis'
                    }
                    remake_script = ''

                    can_remake = (
                        self.client
                        and product_name
                        and product_info
                        and analysis
                        and '分析异常' not in analysis
                        and result.get('pipeline_status') == 'completed'
                    )
                    if can_remake:
                        remake_script = self._generate_remake_with_retry(video, analysis, product_name, product_info)

                    yield {
                        **video,
                        'ai_analysis': analysis,
                        'remake_script': remake_script,
                        **provider_details,
                    }
                except Exception as e:
                    yield {**video, 'ai_analysis': f"分析异常: {str(e)[:50]}", 'remake_script': ''}

    def _analyze_video_only(
        self,
        video: dict,
        video_url: str = None,
        force_collect: bool = False,
        progress_callback=None,
        media_url: str = None,
    ) -> dict:
        """仅分析视频，不生成复刻脚本"""
        return self.analyze_video_script_details(
            video,
            video_url=video_url,
            use_cache=False,
            force_collect=force_collect,
            progress_callback=progress_callback,
            media_url=media_url,
        )

    def _generate_remake_with_retry(self, video: dict, analysis: str, product_name: str, product_info: str, max_retries: int = 3) -> str:
        """带重试的复刻脚本生成"""
        for attempt in range(max_retries):
            result = self.generate_remake_script(video, analysis, product_name, product_info)
            if '429' not in result and 'RESOURCE_EXHAUSTED' not in result:
                return result
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"[限速等待] {wait_time}秒后重试...")
                time.sleep(wait_time)
        return result

    def batch_analyze(self, videos: list, max_videos: int = 5) -> list:
        return list(self.batch_analyze_streaming(videos, max_videos))

    def generate_viral_variants(self, video_data: dict, original_analysis: str) -> str:
        """用 MiniMax 生成裂变变体"""
        if not self.client:
            return "裂变脚本生成失败：未配置 MiniMax API Key"
        prompt = f"""角色设定：你是资深 TikTok 电商短视频裂变策划专家。

=== 原始视频信息 ===
标题: {video_data.get('title', '')}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}
分享: {video_data.get('shares', 0):,}

=== 原始视频 AI 拆解 ===
{original_analysis}

请生成 4 种裂变变体，每种包含：标题、目标人群、核心修改点、完整分镜脚本。"""

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                temperature=0.8,
                messages=[{"role": "user", "content": prompt}]
            )
            text = self._extract_text(msg)
            result = text.strip() if text else "裂变脚本生成结果为空"
            return result
        except Exception as e:
            return f"裂变脚本生成失败: {str(e)[:100]}"

    def generate_remake_script(self, video_data: dict, original_analysis: str, product_name: str, product_info: str) -> str:
        """Generate an evidence-bounded, high-fidelity structure transfer script."""
        if not self.client:
            return "复刻脚本生成失败：未配置 MiniMax API Key"
        duration = video_data.get('duration', 0)
        prompt = f"""角色设定：你是资深 TikTok 电商短视频导演。你的任务不是自由发挥，而是把已经验证的爆款原片结构高保真迁移到目标产品。

=== 爆款视频分析 ===
{original_analysis}

=== 目标产品 ===
产品名称: {product_name}
产品卖点:
{product_info}

=== 任务 ===
1. 先从上方报告提取原片时间轴，逐段确认段落顺序、时长比例、镜头功能、景别、机位/运镜、动作节奏、字幕/声音功能、光线与视觉效果、转场和 CTA 位置。
2. 目标片段顺序与总时长应尽量贴近原片。只替换目标产品、品牌、人物和无法合法复用的素材；不得擅自发明原片或产品资料未支持的功能、场景、控制方式、价格、效果或用户反馈。
3. 原片证据或产品资料缺失时明确写“未采集”或“待补充产品资料”，不能用常识补全。
4. 每个目标片段必须写明对应的原片时间段或镜头引用；任何结构或时长调整必须说明原因。

请严格按照以下格式输出 Markdown：

## 迁移边界
用“必须保留 / 可以替换 / 禁止新增”三栏列出执行边界。

## 原片结构母版
按时间顺序列出原片段落、证据引用、叙事功能与关键视听效果。

## 高保真复刻执行脚本
目标总时长：尽量贴近原片 {duration} 秒。

逐段表格必须包含：原片时间段与引用、目标片时间段、镜头景别与机位/运镜、画面动作、目标产品替换、台词/字幕、声音、光线/视觉效果、转场、CTA、执行备注。

## 执行检查
列出拍摄前必须补齐的产品资料，以及与原片相比的所有必要偏差。"""

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            )
            text = self._extract_text(msg)
            result = text.strip() if text else "生成结果为空"
            return result
        except Exception as e:
            return f"复刻脚本生成失败: {str(e)[:100]}"
