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

脚本输出格式（必须严格按以下表格格式，时间轴列必须标注「第几秒」）：

**## 📝 翻拍脚本（9段叙事结构 + 时间轴标注）**

```
| 时间轴 | 叙事段 | 画面描述 | 画外音 / 字幕 | 情绪目标 |
|--------|--------|---------|-------------|----------|
| 0-2s   | Hook   |          |              | 「等等，什么？」 |
| 2-5s   | Pain   |          |              | 「对，我也有这个问题」 |
| 5-8s   | Fear   |          |              | 「不处理真不行」 |
| 8-12s  | Solution |        |              | 「原来有这个东西」 |
| 12-40s | Demo   |          |              | 「看起来确实好用」 |
| 40-50s | Trust  |          |              | 「不是在骗我」 |
| 50-55s | Price  |          |              | 「这个价格值了」 |
| 55-58s | CTA    |          |              | 「现在就买」 |
| 58-60s | Closure |         |              | 「没白花时间」 |
```

**【推荐钩子】**
本视频使用了 _______ 钩子，建议裂变版本使用 _______ 钩子（从「复购声明」「口语自我纠正」「价格悬念」「身份标签」中选择）

**【时间轴说明】**：
- 表格中「时间轴」列必须标注清楚「第几秒到第几秒」
- 「叙事段」列对应9段中的哪一段（15秒视频只用 Hook + Demo + CTA 即可，其余段留空）
- 「画面描述」：拍摄角度、道具、在哪拍（让创作者能照着拍）
- 「画外音 / 字幕」：具体说的话或字幕文案（可直接用）
- 「情绪目标」：用户此刻的心理状态（对应9段的功能）"""

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

    def generate_viral_variants(self, video_data: dict, original_analysis: str) -> str:
        """
        基于原始爆款分析，自动生成 4 种裂变变体脚本。
        变体策略：换身份标签、换使用场景、换价格锚定参照物、换语言。
        """

        prompt = f"""角色设定：你是资深 TikTok 电商短视频裂变策划专家。

任务：基于以下已验证的爆款视频分析，生成 4 条裂变变体脚本。

=== 原始视频信息 ===
标题: {video_data.get('title', '')}
点赞: {video_data.get('likes', 0):,}
评论: {video_data.get('comments', 0):,}
分享: {video_data.get('shares', 0):,}

=== 原始视频 AI 拆解 ===
{original_analysis}

=== 裂变变体生成要求 ===

请生成以下 4 种裂变变体，每种变体包含：
1. **变体标题**（一句话概括差异点）
2. **目标人群**（谁会看这条变体）
3. **核心修改点**（相比原版改了什么）
4. **完整分镜脚本**（按【时间轴-画面-画外音/字幕-情绪目标】四列格式）

【4种裂变策略】：

**变体 1 — 换身份标签**
改变目标人群（如：原版是「租房党」→ 变体「民宿房东」「合租室友」）
原理：TikTok 算法先打透精准人群，人群越精准越容易破圈

**变体 2 — 换使用场景**
同一产品，放在不同场景里展示（如：原版「家用」→ 变体「户外露营」「车载」「厨房」「办公桌」）
原理：同一个痛点有无数种场景，测出最优场景

**变体 3 — 换价格锚定参照物**
改变价格对比对象（如：原版「比专业版便宜 $50」→ 变体「一张电影票的钱」「少喝两杯奶茶」）
原理：不同参照物触发不同的心理账户，转化率差异巨大

**变体 4 — 换语言/文化背景**
用不同语言或文化表达方式（如：英语 → 西班牙语，或「美式幽默」→「英式幽默」→「中东表达风格」）
原理：同一条视频换语言可以打另一个国家，且制作成本为零

【时间轴标注格式】（必须逐秒标注）：
```
| 时间轴 | 画面描述 | 画外音 / 字幕 | 情绪目标 |
|--------|---------|-------------|----------|
| 0-2s   |         |              |          |
| 2-5s   |         |              |          |
| ...    |         |              |          |
```

【裂变质量标准】：
- 每条变体必须有明确的「人群差异化」和「场景差异化」
- 不得照搬原版文案，必须有新的钩子设计
- 脚本总时长控制在 15-60 秒（可选）
- 结尾必须有 CTA（引导购物车）
"""

        try:
            msg = self.client.messages.create(
                model="MiniMax-M2.7",
                max_tokens=2048,
                temperature=0.8,
                thinking={"type": "disabled"},
                messages=[{"role": "user", "content": prompt}]
            )

            text = ""
            if msg.content:
                for block in msg.content:
                    if hasattr(block, 'type') and block.type == "text":
                        text += block.text

            return text if text else "裂变脚本生成结果为空"
        except Exception as e:
            print(f"[错误] {e}")
            return f"裂变脚本生成失败: {str(e)[:100]}"
