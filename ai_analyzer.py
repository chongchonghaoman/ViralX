#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用 MiniMax M2.7 + Gemini 多模态进行深度分析"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import time
import hashlib
import subprocess
import pathlib
import anthropic
import google.genai as genai
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_config():
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding='utf-8'))
    return {}


class VideoDownloader:
    """使用 yt-dlp 下载 TikTok 视频"""

    def __init__(self, output_dir: str = None):
        if output_dir is None:
            output_dir = Path(__file__).parent / "video_cache"
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def download(self, video_url: str, video_id: str) -> str | None:
        """下载 TikTok 视频到本地，返回文件路径"""
        output_path = self.output_dir / f"{video_id}.mp4"
        if output_path.exists():
            print(f"[视频缓存] {video_id} 已存在")
            return str(output_path)

        print(f"[视频下载] {video_id}...")
        try:
            # yt-dlp 下载 TikTok 视频
            cmd = [
                sys.executable, "-m", "yt_dlp",
                "--no-playlist",
                "--quiet",
                "--no-warnings",
                "-o", str(output_path),
                "--merge-output-format", "mp4",
                video_url
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0 and output_path.exists():
                size = output_path.stat().st_size
                print(f"[视频下载成功] {video_id} ({size/1024/1024:.1f}MB)")
                return str(output_path)
            else:
                print(f"[视频下载失败] {video_id}: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print(f"[视频下载超时] {video_id}")
        except Exception as e:
            print(f"[视频下载异常] {video_id}: {e}")
        return None


class AICache:
    """AI 分析结果缓存"""
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = Path(__file__).parent / "cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)

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


class GeminiAnalyzer:
    """Gemini 多模态分析器（支持视频 + 文本）"""

    def __init__(self, api_key: str = None, model: str = "gemini-2.5-flash"):
        config = load_config()
        self.api_key = api_key or config.get('gemini_api_key', '')
        self.model_name = model or config.get('gemini_model', 'gemini-2.5-flash')
        self.video_dir = Path(config.get('video_cache_dir', Path(__file__).parent / "video_cache"))
        self.video_dir.mkdir(exist_ok=True)
        self.downloader = VideoDownloader(str(self.video_dir))
        self.client = genai.Client(api_key=self.api_key)

    def analyze(self, video_data: dict, video_file_path: str = None) -> str:
        """用 Gemini 分析视频 + 文本数据"""
        video_id = video_data.get('video_id', '')

        # 构建文本 metadata
        metadata_text = self._build_metadata_text(video_data)

        try:
            if video_file_path and os.path.exists(video_file_path):
                # 视频 + 文本多模态分析
                print(f"[Gemini 多模态分析] {video_id}...")
                uploaded_file = self.client.files.upload(file=video_file_path)
                # 等待上传完成
                while uploaded_file.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded_file = self.client.files.get(name=uploaded_file.name)

                prompt = f"""你是一位资深TikTok电商短视频拆解专家。

=== 视频数据 ===
{metadata_text}

=== 任务 ===
1. 仔细观看这个TikTok视频
2. 结合视频画面内容和上述数据，进行深度电商拆解
3. 输出可执行的翻拍脚本

请严格按照以下格式输出 Markdown：

## 🎯 核心卖点
（基于视频实际画面提炼，禁止编造）

## 🎬 视听语言分析
（逐秒描述视频实际内容：画面、声音、字幕、节奏等）

## 💬 用户反馈洞察
（结合评论数据分析用户关注点）

## 📝 翻拍脚本（时间轴必须与视频实际时长一致）
（根据实际视频时长设计对应的叙事结构，不要超出视频实际长度）

【4大转化钩子】（根据视频实际情况判断）：
1. 复购声明
2. 口语自我纠正
3. 价格悬念
4. 身份标签

【推荐钩子】：本视频使用了哪种钩子？裂变版本建议用哪种？"""

                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=[uploaded_file, prompt],
                    config={
                        "temperature": 0.7,
                        "max_output_tokens": 4096,
                    }
                )
                result = response.text.strip() if hasattr(response, 'text') and response.text else "分析结果为空"

                # 清理上传的文件
                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

                return result
            else:
                # 纯文本分析（fallback）
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
{comments_text or '（无评论数据）'}"""

    def _analyze_text_only(self, video_data: dict) -> str:
        """纯文本分析（无视频文件时）"""
        prompt = f"""你是一位资深TikTok电商短视频拆解专家。

{self._build_metadata_text(video_data)}

=== 任务 ===
基于以上数据进行分析，只能分析数据中提供的内容，不要编造视频画面。

请用 Markdown 格式输出：

## 🎯 核心卖点
（基于标题和评论关键词提炼）

## 🎬 拆解分析
（基于互动数据分析）

## 📝 翻拍脚本
（根据视频时长设计对应叙事结构）

【4大转化钩子】：从「复购声明」「口语自我纠正」「价格悬念」「身份标签」中选择适用的。

【推荐钩子】"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={"temperature": 0.7, "max_output_tokens": 2048}
            )
            return response.text.strip() if hasattr(response, 'text') and response.text else "分析结果为空"
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"


class MiniMaxAnalyzer:
    """MiniMax 纯文本分析器（原有逻辑）"""

    def __init__(self, api_key: str = "", base_url: str = None, model: str = None):
        config = load_config()
        self.api_key = api_key or config.get('minimax_api_key', '')
        self.base_url = base_url or config.get('minimax_base_url', 'https://api.minimaxi.com/anthropic')
        self.model = model or config.get('minimax_model', 'MiniMax-M2.7')
        os.environ["ANTHROPIC_BASE_URL"] = self.base_url
        os.environ["ANTHROPIC_API_KEY"] = self.api_key
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
            analysis_type_label = "基于真实评论分析：用户关注点、痛点、转化信号"
            comments_block = f"高赞用户评论：\n{comments_text}"
        else:
            analysis_type_label = "基于互动数据推断：用户可能关注的点、潜在痛点"
            comments_block = ""

        if duration > 0:
            if duration <= 15:
                segment_hint = f"【视频时长 {duration} 秒】极短视频，只需分析：Hook（前{duration}s）+ Demo（展示产品/效果）+ CTA（引导行动）。"
            elif duration <= 30:
                segment_hint = f"【视频时长 {duration} 秒】短视频，建议分析：Hook + Pain/Solution + Demo + CTA。"
            elif duration <= 60:
                segment_hint = f"【视频时长 {duration} 秒】中等视频，分析：Hook + Pain + Solution + Demo + Trust + CTA。"
            else:
                segment_hint = f"【视频时长 {duration} 秒】长视频，可完整分析9段叙事。"
        else:
            segment_hint = "【视频时长未知】请根据视频内容推断时长。"

        return f"""角色设定：你是资深TikTok电商短视频拆解专家，熟悉平台算法推荐机制和用户心理路径。

重要规则：
1. 只分析视频资料中提供的数据，禁止编造视频画面、台词、或时长。
2. 如果某项数据未提供（如评论为空），请明确说明「数据不足，无法分析」。
3. 脚本时间轴必须与视频实际时长一致，不得超出。

=== 视频数据 ===
标题: {video_data.get('title', '') or '（无标题）'}
作者: @{video_data.get('author', 'unknown')}
时长: {f"{duration} 秒" if duration > 0 else '未知'}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}
分享: {video_data.get('shares', 0):,}
播放: {video_data.get('views', 0):,}

{comments_block}

{segment_hint}

=== 输出要求 ===

## 🎯 核心卖点
（仅基于标题和评论中反复出现的关键词提炼）

## 🎬 拆解分析
（{analysis_type_label}）

## 📝 翻拍脚本（动态时间轴）

{segment_hint}

【4大转化钩子】（出现频率>70%）：
1. 复购声明：「这是我第三次买了」
2. 口语自我纠正：说到一半纠正自己
3. 价格悬念：Demo和Trust之后才亮价格
4. 身份标签：「As a busy mom」

【推荐钩子】：本视频使用了哪种钩子？裂变版本建议用哪种？

**注意**：脚本表格的时间轴总长不得超过视频实际时长。"""


class AIAnalyzer:
    """统一分析器：优先 Gemini（多模态），fallback MiniMax（纯文本）"""

    _cache = None
    MAX_CONCURRENT = 5
    REQUEST_TIMEOUT = 120
    USE_GEMINI = True  # 是否优先使用 Gemini

    def __init__(self, api_key: str = "", base_url: str = None, model: str = None):
        config = load_config()

        self.api_key = api_key or config.get('minimax_api_key', '')
        self.base_url = base_url or config.get('minimax_base_url', 'https://api.minimaxi.com/anthropic')
        self.model = model or config.get('minimax_model', 'MiniMax-M2.7')

        self.gemini_key = config.get('gemini_api_key', '')
        self.gemini_model = config.get('gemini_model', 'gemini-2.5-flash')
        self.use_gemini = self.USE_GEMINI and bool(self.gemini_key)

        if self.use_gemini:
            self.gemini = GeminiAnalyzer(api_key=self.gemini_key, model=self.gemini_model)
            print(f"[AIAnalyzer] 使用 Gemini 多模态分析 ({self.gemini_model})")
        else:
            self.gemini = None
            os.environ["ANTHROPIC_BASE_URL"] = self.base_url
            os.environ["ANTHROPIC_API_KEY"] = self.api_key
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.REQUEST_TIMEOUT,
            )
            print(f"[AIAnalyzer] 使用 MiniMax 纯文本分析 ({self.model})")

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

    def analyze_video_script(self, video_data: dict, video_url: str = None, use_cache: bool = True) -> str:
        """分析视频：优先下载视频用 Gemini 分析，否则用 MiniMax"""
        video_id = video_data.get('video_id', '')

        if use_cache:
            cached = self.cache.get(video_id, "video_script")
            if cached:
                print(f"[缓存命中] {video_id[:20]}...")
                return f"[缓存] {cached}"

        video_file_path = None

        if self.use_gemini and video_url:
            # 下载视频
            video_file_path = self.gemini.downloader.download(video_url, video_id)
            if video_file_path:
                # Gemini 多模态分析
                result = self.gemini.analyze(video_data, video_file_path)
                if "失败" not in result:
                    self.cache.set(video_id, result, "video_script")
                    return result
                print(f"[Gemini 失败，fallback] {result[:100]}")

        # MiniMax fallback
        return self._analyze_minimax(video_data)

    def _analyze_minimax(self, video_data: dict) -> str:
        """MiniMax 纯文本分析"""
        video_id = video_data.get('video_id', '')
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
            if result != "分析结果为空":
                self.cache.set(video_id, result, "video_script")
            return result
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"

    def batch_analyze_streaming(self, videos: list, max_videos: int = 5, video_urls: list = None):
        """并发分析多个视频，流式返回"""
        def hot_score(v):
            return v.get('likes', 0) * 1 + v.get('comments', 0) * 5 + v.get('shares', 0) * 2

        sorted_videos = sorted(videos, key=hot_score, reverse=True)[:max_videos]
        urls = video_urls or {}

        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
            future_to_video = {
                executor.submit(self._analyze_safe, v, urls.get(v['video_id'])): v
                for v in sorted_videos
            }
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    result = future.result()
                    yield {**video, 'ai_analysis': result}
                except Exception as e:
                    yield {**video, 'ai_analysis': f"分析异常: {str(e)[:50]}"}

    def _analyze_safe(self, video: dict, video_url: str = None) -> str:
        return self.analyze_video_script(video, video_url=video_url, use_cache=True)

    def batch_analyze(self, videos: list, max_videos: int = 5) -> list:
        return list(self.batch_analyze_streaming(videos, max_videos))

    def generate_viral_variants(self, video_data: dict, original_analysis: str) -> str:
        """用 MiniMax 生成裂变变体"""
        video_id = video_data.get('video_id', '')
        cached = self.cache.get(video_id, "variants")
        if cached:
            return f"[缓存] {cached}"

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
            if "失败" not in result:
                self.cache.set(video_id, result, "variants")
            return result
        except Exception as e:
            return f"裂变脚本生成失败: {str(e)[:100]}"