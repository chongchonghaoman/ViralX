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
        if video_data.get('comments_data'):
            comments_list = [f"- {c['text']} (👍{c['likes']})" for c in video_data['comments_data'][:15]]
            comments_text = "\n".join(comments_list)

        prompt = f"""角色设定：你是资深TikTok电商短视频拆解专家。

任务：深度拆解以下视频，包含用户评论洞察。

视频信息：
标题: {video_data.get('title', '')}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}

高赞用户评论：
{comments_text if comments_text else "暂无评论数据"}

请用 Markdown 格式输出分析结果，必须包含以下章节：

## 🎯 核心卖点
## 🎬 视听语言
## 💬 用户反馈洞察
（基于评论分析：用户关注点、痛点、转化信号）
## 📝 翻拍脚本"""

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
