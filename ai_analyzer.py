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
import requests
import anthropic
import google.genai as genai
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from libtv_analyzer import LibTVAnalyzer, LibTVError
from model_providers import MODEL_PROVIDER_PRESETS, normalize_model_config
from shot_analyzers import (
    EVIDENCE_BUNDLE_SCHEMA,
    LibTVProviderAdapter,
    ShotAnalyzerRouter,
    normalize_shot_config,
    validate_shot_evidence,
)
from video_ingest import VideoAssetCollector, VideoIngestError, is_tiktok_url

def load_config():
    config_path = Path(__file__).parent / "config.json"
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


def _evidence_bundle_text(video_data: dict, limit: int = 80000) -> str:
    """Serialize the merged platform, TK Note, and shot evidence."""
    bundle = video_data.get('evidence_bundle')
    if not bundle:
        return '（尚无合并证据包）'
    try:
        return json.dumps(bundle, ensure_ascii=False, default=str, indent=2)[:limit]
    except (TypeError, ValueError):
        return str(bundle)[:limit]


def _grounded_sources_text(video_data: dict, limit: int = 80000) -> str:
    """Render the merged bundle as named sources the final model must cite."""
    bundle = video_data.get('evidence_bundle') or {}
    platform = bundle.get('platform_evidence') or {}
    tk_note = bundle.get('tk_note_evidence') or {}
    shot = bundle.get('shot_evidence') or bundle.get('libtv_evidence') or {}
    comments = platform.get('comments_data') or []
    hashtags = platform.get('hashtags') or []
    transcript = str(tk_note.get('transcript') or '').strip()
    shot_analysis = str(shot.get('shot_analysis') or '').strip()

    sources = f"""[META:title]
标题：{platform.get('title') or '未采集'}
作者：{platform.get('author') or '未采集'}
时长：{platform.get('duration') if platform.get('duration') is not None else '未采集'} 秒

[META:metrics]
点赞：{platform.get('likes', 0)}；评论数：{platform.get('comments', 0)}；分享数：{platform.get('shares', 0)}；播放量：{platform.get('views', 0)}

[META:comments]
评论正文：{json.dumps(comments, ensure_ascii=False, default=str) if comments else '未采集；不得推断真实用户反馈'}

[META:hashtags]
标签：{json.dumps(hashtags, ensure_ascii=False, default=str) if hashtags else '未采集；不得虚构标签策略'}

[TK:metadata]
{json.dumps(tk_note.get('metadata') or {}, ensure_ascii=False, default=str, indent=2)}

[TK:transcript]
{transcript or '未获得有效转写；不得据此补写台词'}
转写来源：{tk_note.get('transcript_source') or '未知'}
警告：{json.dumps(tk_note.get('warnings') or [], ensure_ascii=False, default=str)}

[SHOT:evidence]
下列每行都带有唯一镜头引用；引用画面事实时必须保留对应的 [SHOT:Sxxx]：
{shot_analysis or '未获得镜头证据；必须停止分析'}

[SHOT:project]
镜头引擎：{shot.get('provider') or '未返回'}；模型：{shot.get('model') or '未返回'}；画布：{shot.get('project_url') or '不适用'}
"""
    return sources[:limit]


def _final_evidence_prompt(video_data: dict) -> str:
    """One evidence-only final prompt shared by every model protocol."""
    return f"""你是 ViralX 的最终证据综合模型。你不能直接观看原视频，也不能补全缺失信息；只能使用下列命名证据源。

=== 可引用证据源 ===
{_grounded_sources_text(video_data)}

=== 不可违反的规则 ===
1. 每条关于原视频的具体事实必须在句末引用来源标签。平台数据使用 [META:title]、[META:metrics]、[META:comments]、[META:hashtags]；转写使用 [TK:transcript]。
2. 每条画面、动作、镜头、屏幕文字事实必须引用它实际来自的镜头 ID，例如 [SHOT:S001]。不得只引用汇总标签 [SHOT:evidence]。
3. 声音和台词只能来自 [TK:transcript]；关键帧不能证明音频。没有评论正文、标签、价格或 CTA 证据时不得补写。
4. 所有营销机制、受众和因果解释必须明确标为“推断”，并同时引用支撑它的事实。
5. 翻拍内容必须标为“创意提案”，不能伪装成原片复原；缺少产品资料时只给结构。
6. 证据不足就写“未采集”或“无法判断”，不要为了完整而填空。

=== 输出格式 ===
## 证据覆盖
用表格列出平台元数据、评论正文、TK Note 转写、镜头证据是否可用和局限，每行附来源。

## 原视频事实
按时间顺序列出可核验事实，每条引用对应 [SHOT:Sxxx]；平台数字另加 [META:metrics]。

## 爆款机制
分为“观察事实”和“推断”两栏，每项都带来源；没有足够证据时明确无法判断。

## 用户反馈与受众
没有评论正文就明确写“评论正文未采集，无法判断真实用户诉求” [META:comments]。

## 可复用结构
只抽象证据支持的结构，说明适用边界并附来源。

## 创意提案：翻拍框架
这是新创作，不是原片复原。逐段注明借用了哪些已引用结构。"""


def _tiktok_numeric_id(value: object) -> str:
    """Return only TikTok's auditable numeric post id, never an opaque media id."""
    match = re.search(r"(?<!\d)(\d{10,24})(?!\d)", str(value or ""))
    return match.group(1) if match else ""


def _libtv_evidence_error(details: dict) -> str:
    """Reject nominally completed LibTV runs that contain no auditable shot evidence."""
    evidence = (details or {}).get('evidence') or {}
    shot_analysis = str(evidence.get('shot_analysis') or (details or {}).get('analysis') or '').strip()
    status = str((details or {}).get('status') or '').lower()
    if status != 'completed':
        return f"LibTV 返回状态 {status or 'unknown'}，未形成可用拉片证据"
    if len(shot_analysis) < 80:
        return "LibTV 拉片文本过短，无法作为最终模型的视觉事实来源"
    if not re.search(r"\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b", shot_analysis):
        return "LibTV 拉片缺少时间码，无法核验镜头事实"
    return ''


def _grounding_error(report: str, video_data: dict | None = None) -> str:
    """Require traceable citations before a model report can be shown as completed."""
    text = str(report or '').strip()
    if not text:
        return "模型没有返回报告"
    citations = re.findall(r"\[(?:META|TK|SHOT):[^\]]+\]", text)
    unique = set(citations)
    if not any(item.startswith('[META:') for item in unique):
        return "报告没有引用平台元数据"
    shot_citations = {item for item in unique if re.fullmatch(r"\[SHOT:S\d{3}\]", item)}
    evidence = (((video_data or {}).get('evidence_bundle') or {}).get('shot_evidence') or {})
    required_shots = min(2, max(int(evidence.get('shot_count') or 1), 1))
    if len(shot_citations) < required_shots:
        return f"报告没有引用足够的具体镜头证据（需要至少 {required_shots} 个镜头 ID）"
    if len(unique) < 3 or len(citations) < 4:
        return "报告的证据引用不足，无法区分事实与推断"
    platform = ((video_data or {}).get('evidence_bundle') or {}).get('platform_evidence') or {}
    if not (platform.get('comments_data') or []):
        if re.search(r"评论(?:显示|反映|指出|认为)|用户(?:表示|认为|反馈)", text):
            return "未采集评论正文，但报告仍声称存在真实用户反馈"
        if not re.search(r"评论.{0,16}未采集|未采集.{0,16}评论", text):
            return "报告没有披露评论正文未采集"
    if not (platform.get('hashtags') or []):
        if re.search(r"#[A-Za-z0-9_\-]+", text):
            return "未采集标签，但报告生成了具体标签"
    return ''


def _persist_evidence_audit(video_file_path: str, evidence_bundle: dict, shot_text: str, report: str = '') -> dict:
    """Keep a local, secret-free audit copy beside the downloaded evidence package."""
    try:
        audit_dir = Path(video_file_path).resolve().parent / 'viralx-evidence'
        audit_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = audit_dir / 'evidence-bundle.json'
        shot_path = audit_dir / 'shot-evidence.md'
        report_path = audit_dir / 'final-model-report.raw.md'
        bundle_path.write_text(
            json.dumps(evidence_bundle, ensure_ascii=False, default=str, indent=2),
            encoding='utf-8',
        )
        shot_path.write_text(str(shot_text or '').strip(), encoding='utf-8')
        if report:
            report_path.write_text(str(report).strip(), encoding='utf-8')
        return {
            'evidence_bundle_path': str(bundle_path),
            'shot_evidence_path': str(shot_path),
            'raw_model_report_path': str(report_path) if report else '',
        }
    except OSError as exc:
        print(f"[证据审计文件写入失败] {exc}")
        return {}


class AICache:
    """AI 分析结果缓存"""
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.environ.get('VIRALX_CACHE_DIR')
        if cache_dir is None:
            cache_dir = (
                Path('/tmp/viralx/cache')
                if os.environ.get('VIRALX_RUNTIME', '').lower() == 'edgeone'
                else Path(__file__).parent / "cache"
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
        self.video_dir = Path(config.get('video_cache_dir', Path(__file__).parent / "video_cache"))
        self.video_dir.mkdir(exist_ok=True, parents=True)

    def extract_frames(self, video_path: str, output_dir: str = None) -> list:
        """从视频每1秒提取1帧，返回帧文件路径列表"""
        if output_dir is None:
            output_dir = self.video_dir / "frames"
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True, parents=True)

        for f in output_dir.glob("frame_*.jpg"):
            f.unlink()

        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", "fps=1/2,scale='min(960,iw)':-2",
                "-q:v", "5",
                str(output_dir / "frame_%04d.jpg"),
                "-y"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                print(f"[帧提取失败] {result.stderr[:100]}")
                return []

            frames = sorted(output_dir.glob("frame_*.jpg"))
            print(f"[帧提取完成] {len(frames)} 帧")
            return [str(f) for f in frames]
        except Exception as e:
            print(f"[帧提取异常] {e}")
            return []

    def analyze(self, video_data: dict, video_file_path: str = None) -> str:
        """用 OpenRouter 模型分析视频帧 + 文本数据"""
        video_id = video_data.get('video_id', '')
        metadata_text = self._build_metadata_text(video_data)

        try:
            if self.supports_vision and video_file_path and os.path.exists(video_file_path):
                print(f"[{self.provider_name} 分析] {video_id}...")
                frames = self.extract_frames(video_file_path)
                if not frames:
                    return self._analyze_text_only(video_data)

                prompt = self._build_analysis_prompt(video_data, metadata_text, len(frames))

                content_parts = [{"type": "text", "text": prompt}]
                for frame in frames[:12]:
                    encoded = base64.b64encode(Path(frame).read_bytes()).decode("ascii")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                    })

                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://viralx.metrolabs.mobi",
                    "X-Title": "ViralX",
                }
                payload = {
                    "model": self.model_name,
                    "messages": [{"role": "user", "content": content_parts}],
                    "max_tokens": 8192,
                    "temperature": 0.1
                }

                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120
                )

                if resp.status_code == 200:
                    result = resp.json()["choices"][0]["message"]["content"].strip()
                    return result
                else:
                    return f"{self.provider_name} 分析失败：HTTP {resp.status_code}"

            return self._analyze_text_only(video_data)

        except Exception as e:
            print(f"[{self.provider_name} 分析异常] {type(e).__name__}")
            return f"{self.provider_name} 分析失败：{str(e)[:100]}"

    def _build_analysis_prompt(self, video_data: dict, metadata_text: str, frame_count: int) -> str:
        return f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

=== 证据协议（最高优先级） ===
你正在做证据综合，不是在补全一篇营销文章。每条关于原视频的具体事实必须在句末标注来源：
- 平台标题、作者和互动数据用 [META:title] 或 [META:metrics]
- 评论正文和标签只能分别来自 [META:comments]、[META:hashtags]；标为“未采集”时禁止推断
- 字幕或 ASR 只能引用 [TK:transcript]；歌词不得冒充商品台词
- 画面、动作、镜头、字幕和声音只允许引用 [LIBTV:shot] 或本次直接看到的 [FRAME:sample]
- 营销解释必须明确写“推断”，并同时引用支撑它的事实来源
- 翻拍脚本必须标为“创意提案”，不得伪装成原视频复原
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

## 📝 创意提案：翻拍脚本

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
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://viralx.metrolabs.mobi",
                "X-Title": "ViralX",
            }
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8192,
                "temperature": 0.1
            }
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120
            )
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
        metadata = self.prompt_helper._build_metadata_text(video_data)
        frames = []
        if self.supports_vision and video_file_path and os.path.exists(video_file_path):
            frames = self.prompt_helper.extract_frames(video_file_path)
        prompt = (
            self.prompt_helper._build_analysis_prompt(video_data, metadata, len(frames))
            if frames
            else self.prompt_helper._analyze_text_prompt(video_data)
        )
        content = [{"type": "text", "text": prompt}]
        for frame in frames[:12]:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(Path(frame).read_bytes()).decode("ascii"),
                },
            })
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
        self.video_dir = Path(config.get('video_cache_dir', Path(__file__).parent / "video_cache"))
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

                prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

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
    """Evidence-first analyzer: TK Note -> shot evidence -> final model synthesis."""

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
            'shot_engine': shot_engine or config.get('shot_engine', 'auto'),
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
        print(
            "[AIAnalyzer] 串联链路: TK Note -> "
            f"{self.shot_config['engine']} 镜头证据 -> 模型终审"
        )

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
            failed = '失败' in result
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

    def analyze_video_script_details(self, video_data: dict, video_url: str = None, use_cache: bool = False, force_collect: bool = False, progress_callback=None) -> dict:
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
            }

        emit('collection', 'running', 'TK Note 正在采集原片、字幕与元数据', 24)
        try:
            asset = self.video_collector.prepare(video_url, video_id, force=force_collect)
            video_file_path = asset.video_file
            acquisition_details = asset.analysis_details()
            video_data.update(asset.video_fields())
        except VideoIngestError as exc:
            return {
                'analysis': f'TK Note 证据采集失败：{exc}',
                'analysis_provider': 'pipeline',
                'pipeline_stage': 'collection',
                'pipeline_status': 'error',
                'acquisition_provider': acquisition_provider,
                'acquisition_error_code': getattr(exc, 'code', 'collection_failed'),
                'tk_note_task_log': getattr(exc, 'task_log', ''),
                ('tk_note_status' if acquisition_provider == 'tk-note' else 'video_ingest_status'): 'error',
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
            'auto': 'ShotLoom Core（失败时回退 LibTV）',
            'shotloom': 'ShotLoom Core',
            'libtv': 'LibTV',
            'skip': '只采集模式',
        }.get(self.shot_config['engine'], self.shot_config['engine'])
        emit('shot-analysis', 'running', f'{engine_label} 正在生成镜头证据', 48)
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
            else str(shot_details.get('block_reason') or '镜头证据没有完成')
        )
        emit(
            'shot-analysis',
            'blocked' if shot_evidence_error else 'complete',
            (
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
        evidence_bundle = {
            'schema': EVIDENCE_BUNDLE_SCHEMA,
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

        emit('final-analysis', 'running', f'{self.model_provider} 正在进行最终综合分析', 86)
        # The final model is evidence-only. It never receives the original file
        # and therefore cannot silently re-interpret frames outside the shot log.
        final_analysis = self.model_analyzer.analyze(video_data, None)
        audit_details.update(_persist_evidence_audit(
            video_file_path,
            evidence_bundle,
            shot_analysis,
            final_analysis,
        ))
        grounding_error = _grounding_error(final_analysis, video_data)
        model_failed = '失败' in final_analysis or not final_analysis.strip() or bool(grounding_error)
        visible_analysis = final_analysis
        if grounding_error:
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
        return {
            'analysis': visible_analysis or '模型 API 没有返回最终分析',
            'analysis_provider': self.model_provider,
            'pipeline_stage': 'final-analysis',
            'pipeline_status': 'error' if model_failed else 'completed',
            'evidence_status': 'merged',
            'evidence_bundle': evidence_bundle,
            'shot_provider': shot_details.get('provider'),
            'shot_model': shot_details.get('model'),
            'shot_status': shot_details.get('status', 'completed'),
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
            'model_grounding_error': grounding_error,
            **audit_details,
            **acquisition_details,
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

    def batch_analyze_streaming(self, videos: list, max_videos: int = 5, video_urls: list = None, product_name: str = '', product_info: str = '', force_collect: bool = False, progress_callback=None):
        """Analyze videos one at a time through the five-stage evidence pipeline."""
        def hot_score(v):
            return v.get('likes', 0) * 1 + v.get('comments', 0) * 5 + v.get('shares', 0) * 2

        sorted_videos = sorted(videos, key=hot_score, reverse=True)[:max_videos]
        urls = video_urls or {}

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

    def _analyze_video_only(self, video: dict, video_url: str = None, force_collect: bool = False, progress_callback=None) -> dict:
        """仅分析视频，不生成复刻脚本"""
        return self.analyze_video_script_details(
            video,
            video_url=video_url,
            use_cache=False,
            force_collect=force_collect,
            progress_callback=progress_callback,
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
        """基于爆款视频分析和产品信息，生成复刻脚本（不使用缓存）"""
        if not self.client:
            return "复刻脚本生成失败：未配置 MiniMax API Key"
        duration = video_data.get('duration', 0)
        prompt = f"""角色设定：你是资深TikTok电商短视频编剧，擅长将爆款视频的成功逻辑应用到不同产品上。

=== 爆款视频分析 ===
{original_analysis}

=== 目标产品 ===
产品名称: {product_name}
产品卖点:
{product_info}

=== 任务 ===
1. 分析这个产品的核心卖点，找出与爆款视频成功逻辑的结合点
2. 保留爆款视频的结构框架（开场方式、信任建立方式、转化节奏），但替换成你的产品
3. 写出一个完整的复刻脚本

请严格按照以下格式输出 Markdown：

## 🎯 产品适配分析
（分析爆款逻辑如何应用到你的产品，有哪些优势可以放大，哪些需要调整）

## 📹 复刻脚本
【时长】{duration}秒

【开场】（前3秒：如何抓住注意力，与原视频开场逻辑类似但换成本产品）
- 画面：
- 台词：

【信任建立】（中间部分，如何让人相信你的产品）
- 画面：
- 台词：

【转化收割】（最后部分，如何推动购买决策）
- 画面：
- 台词：

## 💡 注意事项
（翻拍时需要注意的要点、可能踩的坑）"""

        try:
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}]
            )
            text = self._extract_text(msg)
            result = text.strip() if text else "生成结果为空"
            return result
        except Exception as e:
            return f"复刻脚本生成失败: {str(e)[:100]}"
