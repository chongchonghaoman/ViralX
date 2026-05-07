#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将分析结果导出为 Markdown 到 Obsidian"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path
from datetime import datetime

def generate_markdown(analysis_file: Path, keyword: str) -> str:
    """生成详细的 Markdown 报告"""
    with open(analysis_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    md = f"# TikTok 爆款视频分析 - {keyword}\n\n"
    md += f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # 统计数据
    if data:
        total_likes = sum(v.get('likes', 0) for v in data)
        avg_likes = total_likes / len(data)
        max_likes = max(v.get('likes', 0) for v in data)

        md += "## 📊 数据统计\n\n"
        md += f"- 分析视频数：{len(data)}\n"
        md += f"- 总点赞数：{total_likes:,}\n"
        md += f"- 平均点赞：{avg_likes:,.0f}\n"
        md += f"- 最高点赞：{max_likes:,}\n\n"

    md += "## 🎯 爆款视频详细分析\n\n"

    for i, video in enumerate(data, 1):
        md += f"### {i}. {video.get('title', '')[:80]}\n\n"

        md += f"**作者：** {video.get('author', 'N/A')}\n\n"

        md += "**互动数据：**\n"
        md += f"- 点赞：{video.get('likes', 0):,}\n"
        md += f"- 评论：{video.get('comments', 0):,}\n"
        md += f"- 分享：{video.get('shares', 0):,}\n"
        md += f"- 播放：{video.get('views', 0):,}\n\n"

        analysis = video.get('ai_analysis', {})
        if analysis:
            md += "**AI 分析结果：**\n\n"

            if analysis.get('核心卖点'):
                md += f"**核心卖点：** {', '.join(analysis['核心卖点'])}\n\n"

            if analysis.get('情绪钩子'):
                md += f"**情绪钩子：** {analysis['情绪钩子']}\n\n"

            if analysis.get('脚本结构'):
                md += f"**脚本结构：** {analysis['脚本结构']}\n\n"

            if analysis.get('目标人群'):
                md += f"**目标人群：** {analysis['目标人群']}\n\n"

            if analysis.get('复刻建议'):
                md += f"**复刻建议：** {analysis['复刻建议']}\n\n"

        md += "---\n\n"

    return md

def main():
    data_dir = Path("E:/tiktok_analyzer/data")
    obsidian_dir = Path("E:/我的知识库/07-对话记录")
    obsidian_dir.mkdir(parents=True, exist_ok=True)

    for analysis_file in data_dir.glob("*_analysis.json"):
        keyword = analysis_file.stem.replace("_analysis", "").replace("_", " ")
        print(f"[转换] {keyword}...")

        md_content = generate_markdown(analysis_file, keyword)

        md_file = obsidian_dir / f"TikTok-{keyword}-{datetime.now().strftime('%Y%m%d')}.md"
        md_file.write_text(md_content, encoding='utf-8')
        print(f"✓ 已保存: {md_file}")

if __name__ == "__main__":
    main()
