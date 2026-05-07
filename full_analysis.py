#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整分析流程 + 导出到 Obsidian"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path
from datetime import datetime
from tiktok_viral_analyzer import TikTokViralAnalyzer
from ai_analyzer import AIAnalyzer
from report_generator import generate_report

def export_to_markdown(analysis_data: list, keyword: str):
    """导出为 Markdown"""
    md = f"# TikTok 爆款视频分析 - {keyword}\n\n"
    md += f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    if analysis_data:
        total_likes = sum(v.get('likes', 0) for v in analysis_data)
        avg_likes = total_likes / len(analysis_data)
        md += f"## 📊 统计\n- 视频数：{len(analysis_data)}\n- 平均点赞：{avg_likes:,.0f}\n\n"

    md += "## 🎯 详细分析\n\n"
    for i, video in enumerate(analysis_data, 1):
        md += f"### {i}. {video.get('title', '')[:80]}\n\n"
        md += f"**作者：** {video.get('author', 'N/A')}\n"
        md += f"**点赞：** {video.get('likes', 0):,} | **评论：** {video.get('comments', 0):,}\n\n"

        analysis = video.get('ai_analysis', {})
        if analysis:
            if analysis.get('核心卖点'):
                md += f"**卖点：** {', '.join(analysis['核心卖点'])}\n"
            if analysis.get('复刻建议'):
                md += f"**建议：** {analysis['复刻建议']}\n"
        md += "\n---\n\n"

    obsidian_dir = Path("E:/我的知识库/07-对话记录")
    obsidian_dir.mkdir(parents=True, exist_ok=True)
    md_file = obsidian_dir / f"TikTok-{keyword}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    md_file.write_text(md, encoding='utf-8')
    print(f"✓ Markdown: {md_file}")

def main():
    config = json.loads(Path("config.json").read_text())
    tiktok = TikTokViralAnalyzer(config['output_dir'])
    tiktok.api_key = config['rapidapi_key']
    ai = AIAnalyzer(api_key=config.get('minimax_api_key'))

    for keyword in config['search_keywords']:
        print(f"\n{'='*60}\n[1/4] 搜索: {keyword}\n{'='*60}")

        videos = tiktok.search_viral_videos(keyword, config['min_likes'], count=30)
        if not videos:
            continue

        print(f"[2/4] 提取信息...")
        video_data = [tiktok.extract_video_info(v) for v in videos]

        print(f"[3/4] 生成报告...")
        report = generate_report(video_data, keyword)
        report_file = Path(config['output_dir']) / f"{keyword.replace(' ', '_')}_report.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f"[4/4] AI 分析...")
        analysis_results = ai.batch_analyze(video_data[:5])
        analysis_file = Path(config['output_dir']) / f"{keyword.replace(' ', '_')}_analysis.json"
        analysis_file.write_text(json.dumps(analysis_results, ensure_ascii=False, indent=2), encoding='utf-8')

        print(f"[5/5] 导出 Markdown...")
        export_to_markdown(analysis_results, keyword)

if __name__ == "__main__":
    main()







