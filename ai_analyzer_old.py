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
import requests
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


class OpenRouterAnalyzer:
    """OpenRouter 免费模型分析器（每1秒取1帧图片）"""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str = None, model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"):
        config = load_config()
        self.api_key = api_key or config.get('openrouter_api_key', '')
        self.model_name = model
        self.video_dir = Path(config.get('video_cache_dir', Path(__file__).parent / "video_cache"))
        self.video_dir.mkdir(exist_ok=True)
        self.downloader = VideoDownloader(str(self.video_dir))

    def extract_frames(self, video_path: str, output_dir: str = None) -> list:
        """从视频每1秒提取1帧，返回帧文件路径列表"""
        if output_dir is None:
            output_dir = self.video_dir / "frames"
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True, parents=True)

        # 清理旧帧
        for f in output_dir.glob("frame_*.jpg"):
            f.unlink()

        try:
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", "fps=1",  # 每秒1帧
                "-q:v", "3",  # JPEG 质量
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
            if video_file_path and os.path.exists(video_file_path):
                print(f"[OpenRouter 分析] {video_id}...")

                # 提取帧
                frames = self.extract_frames(video_file_path)
                if not frames:
                    return self._analyze_text_only(video_data)

                # 构建提示词
                prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

=== 视频数据 ===
{metadata_text}

=== 视频帧 ===
视频共提取了 {len(frames)} 帧图片，代表每秒的画面。

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

                # 发送请求
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://viralx.local",
                    "X-Title": "ViralX"
                }
                payload = {
                    "model": self.model_name,
                    "messages": [
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt}
                        ] + [{"type": "image_url", "image_url": {"url": f"file://{frame}}" for frame in frames[:30]}]}  # 最多30帧
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.7
                }

                resp = requests.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=120
                )

                if resp.status_code == 200:
                    result = resp.json()["choices"][0]["message"]["content"].strip()
                    return result
                else:
                    return f"OpenRouter 分析失败: {resp.status_code} {resp.text[:100]}"

            return self._analyze_text_only(video_data)

        except Exception as e:
            print(f"[OpenRouter 分析异常] {e}")
            return f"OpenRouter 分析失败: {str(e)[:100]}"

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
        prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

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
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://viralx.local",
                "X-Title": "ViralX"
            }
            payload = {
                "model": self.model_name,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 8192,
                "temperature": 0.7
            }
            resp = requests.post(
                f"{self.BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            else:
                return f"分析失败: {resp.status_code} {resp.text[:100]}"
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"


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

**① 低评论原因分析**
```
✓ 原因1
✓ 原因2
```

**② 高分享驱动因素**（如果有高分享率）
```
📌 驱动1
📌 驱动2
```

### 用户潜在关注点（基于评论和内容推断）

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
        prompt = f"""你是一位资深TikTok电商短视频拆解专家，擅长深度结构化分析。

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

**② 分享驱动因素**（如果有高分享率）
```
📌 驱动1
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
    """统一分析器：支持 Gemini 多模态 / OpenRouter 免费模型"""

    _cache = None
    MAX_CONCURRENT = 5
    REQUEST_TIMEOUT = 120

    def __init__(self, api_key: str = "", base_url: str = None, model: str = None, analysis_mode: str = 'gemini', openrouter_api_key: str = ''):
        config = load_config()

        self.api_key = api_key or config.get('minimax_api_key', '')
        self.base_url = base_url or config.get('minimax_base_url', 'https://api.minimaxi.com/anthropic')
        self.model = model or config.get('minimax_model', 'MiniMax-M2.7')
        self.analysis_mode = analysis_mode or config.get('analysis_mode', 'gemini')
        self.openrouter_api_key = openrouter_api_key or config.get('openrouter_api_key', '')

        self.gemini_key = config.get('gemini_api_key', '')
        self.gemini_model = config.get('gemini_model', 'gemini-2.5-flash')
        self.use_gemini = self.analysis_mode == 'gemini' and bool(self.gemini_key)
        self.use_openrouter = self.analysis_mode == 'openrouter' and bool(self.openrouter_api_key)

        if self.use_gemini:
            self.gemini = GeminiAnalyzer(api_key=self.gemini_key, model=self.gemini_model)
            print(f"[AIAnalyzer] 模式1: Gemini 多模态分析 ({self.gemini_model})")
        else:
            self.gemini = None

        if self.use_openrouter:
            self.openrouter = OpenRouterAnalyzer(api_key=self.openrouter_api_key)
            print(f"[AIAnalyzer] 模式2: OpenRouter 免费模型")
        else:
            self.openrouter = None

        # MiniMax 客户端始终初始化（复刻脚本需要用到）
        os.environ["ANTHROPIC_BASE_URL"] = self.base_url
        os.environ["ANTHROPIC_API_KEY"] = self.api_key
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

    def analyze_video_script(self, video_data: dict, video_url: str = None, use_cache: bool = False) -> str:
        """分析视频：根据模式选择 Gemini 或 OpenRouter"""
        video_id = video_data.get('video_id', '')

        video_file_path = None

        if self.use_gemini and video_url:
            video_file_path = self.gemini.downloader.download(video_url, video_id)
            if video_file_path:
                result = self.gemini.analyze(video_data, video_file_path)
                if "失败" not in result:
                    return result
                print(f"[Gemini 失败，fallback] {result[:100]}")

        elif self.use_openrouter and video_url:
            video_file_path = self.openrouter.downloader.download(video_url, video_id)
            if video_file_path:
                result = self.openrouter.analyze(video_data, video_file_path)
                if "失败" not in result:
                    return result
                print(f"[OpenRouter 失败，fallback] {result[:100]}")

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
            return result
        except Exception as e:
            return f"分析失败: {str(e)[:100]}"

    def batch_analyze_streaming(self, videos: list, max_videos: int = 5, video_urls: list = None, product_name: str = '', product_info: str = ''):
        """并发分析多个视频，视频分析并发，复刻脚本串行生成"""
        def hot_score(v):
            return v.get('likes', 0) * 1 + v.get('comments', 0) * 5 + v.get('shares', 0) * 2

        sorted_videos = sorted(videos, key=hot_score, reverse=True)[:max_videos]
        urls = video_urls or {}

        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
            future_to_video = {
                executor.submit(self._analyze_video_only, v, urls.get(v['video_id'])): v
                for v in sorted_videos
            }
            for future in as_completed(future_to_video):
                video = future_to_video[future]
                try:
                    result = future.result()
                    analysis = result['analysis']
                    remake_script = ''

                    # 串行生成复刻脚本（避免 API 限速）
                    if product_name and product_info and analysis and '分析异常' not in analysis:
                        remake_script = self._generate_remake_with_retry(video, analysis, product_name, product_info)

                    yield {**video, 'ai_analysis': analysis, 'remake_script': remake_script}
                except Exception as e:
                    yield {**video, 'ai_analysis': f"分析异常: {str(e)[:50]}", 'remake_script': ''}

    def _analyze_video_only(self, video: dict, video_url: str = None) -> dict:
        """仅分析视频，不生成复刻脚本"""
        analysis = self.analyze_video_script(video, video_url=video_url, use_cache=False)
        return {'analysis': analysis}

    def _generate_remake_with_retry(self, video: dict, analysis: str, product_name: str, product_info: str, max_retries: int = 3) -> str:
        """带重试的复刻脚本生成（处理 429 限速）"""
        for attempt in range(max_retries):
            result = self.generate_remake_script(video, analysis, product_name, product_info)
            if '429' not in result and 'RESOURCE_EXHAUSTED' not in result:
                return result
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 5, 10, 15 秒
                print(f"[限速等待] {wait_time}秒后重试...")
                time.sleep(wait_time)
        return result  # 返回最后一次结果（可能是错误）

    def batch_analyze(self, videos: list, max_videos: int = 5) -> list:
        return list(self.batch_analyze_streaming(videos, max_videos))

    def generate_viral_variants(self, video_data: dict, original_analysis: str) -> str:
        """用 MiniMax 生成裂变变体"""
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
        video_id = video_data.get('video_id', '')
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
            # 始终使用 MiniMax 生成复刻脚本（避免 Gemini 配额问题）
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