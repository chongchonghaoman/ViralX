#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TikTok 分析工具 - Web 可视化界面"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from flask import Flask, render_template, request, jsonify
import json
from pathlib import Path
from datetime import datetime
from tiktok_viral_analyzer import TikTokViralAnalyzer
from ai_analyzer import AIAnalyzer

app = Flask(__name__)
config = json.loads(Path("config.json").read_text())

def load_cached_analysis(keyword):
    """从缓存加载分析结果"""
    cache_file = Path(config['output_dir']) / f"{keyword.replace(' ', '_')}_analysis.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding='utf-8'))
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """执行分析"""
    data = request.json
    keyword = data.get('keyword', 'outdoor lighting lamp')
    refresh = data.get('refresh', False)

    try:
        # 如果不是刷新，先尝试从缓存加载
        if not refresh:
            cached = load_cached_analysis(keyword)
            if cached:
                return jsonify({
                    'status': 'success',
                    'total_videos': len(cached),
                    'videos': cached,
                    'source': 'cache'
                })

        # 执行实时分析
        tiktok = TikTokViralAnalyzer(config['output_dir'])
        tiktok.api_key = config['rapidapi_key']
        ai = AIAnalyzer(api_key=config.get('minimax_api_key'))

        videos = tiktok.search_viral_videos(keyword, config['min_likes'], count=30)
        video_data = [tiktok.extract_video_info(v) for v in videos]

        # 实时调用 MiniMax 分析
        results = []
        for i, video in enumerate(video_data[:10], 1):
            try:
                # 抓取评论
                comments = tiktok.get_video_comments(video['video_id'])
                video['comments_data'] = [{'text': c.get('text', ''), 'likes': c.get('digg_count', 0)} for c in comments]

                analysis = ai.analyze_video_script(video)
                results.append({**video, 'ai_analysis': analysis})
            except Exception as e:
                print(f"[分析失败] {e}")
                results.append({**video, 'ai_analysis': f"分析失败: {str(e)[:50]}"})

        return jsonify({
            'status': 'success',
            'total_videos': len(results),
            'videos': results,
            'source': 'live'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/keywords', methods=['GET'])
def get_keywords():
    """获取可用的关键词列表"""
    keywords = []
    for kw in config['search_keywords']:
        cache_file = Path(config['output_dir']) / f"{kw.replace(' ', '_')}_analysis.json"
        if cache_file.exists():
            keywords.append({'keyword': kw, 'cached': True})
    return jsonify({'keywords': keywords})

@app.route('/api/export-obsidian', methods=['POST'])
def export_obsidian():
    """导出分析结果到 Obsidian"""
    try:
        data = request.json
        title = data.get('title', 'AI 深度拆解')
        content = data.get('content', '')

        # Obsidian 知识库路径
        obsidian_path = Path('E:/我的知识库/07-对话记录')
        folder_path = obsidian_path / '抖音爆款视频分析'

        # 创建文件夹
        folder_path.mkdir(parents=True, exist_ok=True)

        # 生成文件名（带时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{timestamp}_{title}.md"
        file_path = folder_path / filename

        # 写入文件
        file_path.write_text(content, encoding='utf-8')

        return jsonify({
            'status': 'success',
            'file_path': str(file_path)
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, port=5000)
