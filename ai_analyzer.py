#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""使用 MiniMax M2.7 进行深度分析"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import anthropic

class AIAnalyzer:
    def __init__(self, api_key: str = ""):
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.minimaxi.com/anthropic"
        os.environ["ANTHROPIC_API_KEY"] = api_key
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url="https://api.minimaxi.com/anthropic"
        )

    def analyze_video_script(self, video_data: dict) -> str:
        """用 MiniMax M2.7 进行深度电商拆解，返回 Markdown 格式"""

        # 处理评论数据
        comments_text = ""
        has_comments = False
        if video_data.get('comments_data') and len(video_data.get('comments_data', [])) > 0:
            comments_list = [f"- {c['text']} (👍{c['likes']})" for c in video_data['comments_data'][:15]]
            comments_text = "\n".join(comments_list)
            has_comments = True

        if has_comments:
            analysis_type = "基于真实评论分析：用户关注点、痛点、转化信号"
        else:
            analysis_type = "基于互动数据推断：用户可能关注的点、潜在痛点"

        prompt = f"""角色设定：你是资深TikTok电商短视频拆解专家，熟悉平台算法推荐机制和用户心理路径。

任务：深度拆解以下视频，按9段叙事结构输出可执行的翻拍脚本。

视频信息：
标题: {video_data.get('title', '')}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}
分享: {video_data.get('shares', 0):,}

{'高赞用户评论：\n' + comments_text if has_comments else ''}

请用 Markdown 格式输出分析结果，必须包含：

## 🎯 核心卖点
## 🎬 视听语言（逐秒分析）
## 💬 用户反馈洞察
（{analysis_type}）
## 📝 翻拍脚本（9段叙事结构）

【9段叙事结构说明】：
| 段 | 名称 | 功能 | 用户心理 |
| 1 | Hook | 前1-2秒制造停留 | 「等等，什么？」 |
| 2 | Pain | 戳中痛点 | 「对，我也有这个问题」 |
| 3 | Fear | 放大不解决的后果 | 「不处理真不行」 |
| 4 | Solution | 亮出产品 | 「原来有这个东西」 |
| 5 | Demo | 展示使用过程 | 「看起来确实好用」 |
| 6 | Trust | 提供信任证据 | 「不是在骗我」 |
| 7 | Price | 价格锚定 | 「这个价格值了」 |
| 8 | CTA | 引导点购物车 | 「现在就买」 |
| 9 | Closure | 情绪收尾 | 「没白花时间」 |

【4大转化钩子】(出现频率>70%，优先识别并推荐)：
1. 复购声明：「这是我第三次买了」— 行为比语言有说服力
2. 口语自我纠正：说到一半纠正自己 — 制造「不是在念稿」的真实感，AI视频尤其需要
3. 价格悬念：Demo和Trust之后才亮价格，用高价参照锚定 — ROAS能高1.8倍
4. 身份标签：「As a busy mom」「For us gym people」— 精准筛选打透，人群越小算法越推

脚本输出格式（示例）：
```
[0-2s] Hook
  画面：描述
  画外音/字幕：「情绪点」

[2-5s] Pain
  画面：描述
  画外音/字幕：「痛点」

[推荐钩子] 本视频使用了「复购声明」钩子，建议裂变版本使用「身份标签」钩子
```"""

        try:
            msg = self.client.messages.create(
                model="MiniMax-M2.7",
                max_tokens=2048,
                temperature=0.7,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}]
            )

            text = ""
            if msg.content:
                for block in msg.content:
                    if hasattr(block, 'type') and block.type == "text":
                        text += block.text

            return text if text else "分析结果为空"
        except Exception as e:
            print(f"[错误] {e}")
            return f"分析失败: {str(e)[:100]}"

    def batch_analyze(self, videos: list) -> list:
        """批量分析"""
        results = []
        for i, video in enumerate(videos, 1):
            print(f"[AI 分析] {i}/{len(videos)}")
            analysis = self.analyze_video_script(video)
            results.append({**video, 'ai_analysis': analysis})
        return results
