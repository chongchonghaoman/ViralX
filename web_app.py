#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TikTok 分析工具 - Web 可视化界面"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from flask import Flask, render_template, request, jsonify, Response
import json
from pathlib import Path
from datetime import datetime
import threading
import queue
from tiktok_viral_analyzer import TikTokViralAnalyzer
from ai_analyzer import AIAnalyzer

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent / "config.json"
MAX_ANALYZE_VIDEOS = 5  # 最多分析 5 个视频

def load_config():
    """从 config.json 加载配置"""
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))

def save_config(data):
    """保存配置到 config.json"""
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

# 全局配置
config = load_config()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/settings')
def settings_page():
    return render_template('settings.html')

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """获取当前配置"""
    return jsonify(config)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    """保存配置"""
    try:
        data = request.json
        save_config(data)
        global config
        config = data
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    执行分析 — 流式响应。
    边并发分析视频边返回结果，前端逐个看到分析完成。
    """
    data = request.json
    keyword = data.get('keyword', 'outdoor lighting lamp')
    refresh = data.get('refresh', False)

    def generate():
        try:
            current_config = load_config()

            # 非刷新模式先查缓存
            if not refresh:
                cache_file = Path(current_config['output_dir']) / f"{keyword.replace(' ', '_')}_analysis.json"
                if cache_file.exists():
                    cached = json.loads(cache_file.read_text(encoding='utf-8'))
                    yield json.dumps({
                        'status': 'success',
                        'total_videos': len(cached),
                        'videos': cached,
                        'source': 'cache',
                        'done': True
                    }, ensure_ascii=False) + '\n'
                    return

            # 搜索视频
            tiktok = TikTokViralAnalyzer(current_config['output_dir'])
            tiktok.api_key = current_config['rapidapi_key']

            videos = tiktok.search_viral_videos(keyword, current_config['min_likes'], count=30)
            video_data = [tiktok.extract_video_info(v) for v in videos]

            if not video_data:
                yield json.dumps({'status': 'error', 'message': '未找到相关视频', 'done': True}, ensure_ascii=False) + '\n'
                return

            # 创建 AI 分析器
            ai = AIAnalyzer(
                api_key=current_config.get('minimax_api_key'),
                base_url=current_config.get('minimax_base_url'),
                model=current_config.get('minimax_model')
            )

            # 构建视频 URL 映射
            video_urls = {
                v['video_id']: f"https://www.tiktok.com/@{v['author']}/video/{v['video_id']}"
                for v in video_data
            }

            # 流式并发分析，结果边完成边推送
            results = []
            for result in ai.batch_analyze_streaming(video_data, max_videos=MAX_ANALYZE_VIDEOS, video_urls=video_urls):
                # 抓取评论（在主线程串行执行，不影响并发分析）
                try:
                    comments = tiktok.get_video_comments(result['video_id'])
                    result['comments_data'] = comments
                except Exception as e:
                    print(f"[评论抓取失败] {e}")
                    result['comments_data'] = []

                results.append(result)

                # 每完成一个就推送一个，前端可以立即显示
                yield json.dumps({
                    'status': 'progress',
                    'done': False,
                    'current': len(results),
                    'total': MAX_ANALYZE_VIDEOS,
                    'video': result
                }, ensure_ascii=False) + '\n'

            # 保存到缓存
            try:
                cache_file = Path(current_config['output_dir']) / f"{keyword.replace(' ', '_')}_analysis.json"
                cache_file.write_text(json.dumps(results, ensure_ascii=False), encoding='utf-8')
            except Exception as e:
                print(f"[缓存保存失败] {e}")

            # 推送完成信号
            yield json.dumps({
                'status': 'success',
                'total_videos': len(results),
                'videos': results,
                'source': 'live',
                'done': True
            }, ensure_ascii=False) + '\n'

        except Exception as e:
            yield json.dumps({'status': 'error', 'message': str(e), 'done': True}, ensure_ascii=False) + '\n'

    return Response(generate(), mimetype='application/json', headers={
        'X-Accel-Buffering': 'no',
        'Cache-Control': 'no-cache'
    })

@app.route('/api/keywords', methods=['GET'])
def get_keywords():
    """获取可用的关键词列表"""
    current_config = load_config()
    keywords = []
    for kw in current_config['search_keywords']:
        cache_file = Path(current_config['output_dir']) / f"{kw.replace(' ', '_')}_analysis.json"
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

@app.route('/api/generate_variants', methods=['POST'])
def generate_variants():
    """基于爆款分析生成 4 种裂变变体脚本"""
    try:
        current_config = load_config()
        data = request.json
        video = data.get('video', {})
        analysis = data.get('analysis', '')

        if not analysis:
            return jsonify({'status': 'error', 'message': '缺少原始视频分析内容'}), 400

        ai = AIAnalyzer(
            api_key=current_config.get('minimax_api_key'),
            base_url=current_config.get('minimax_base_url'),
            model=current_config.get('minimax_model')
        )
        variants = ai.generate_viral_variants(video, analysis)

        return jsonify({
            'status': 'success',
            'variants': variants
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """清除 AI 分析缓存"""
    try:
        from ai_analyzer import AICache
        cache = AICache()
        for f in cache.cache_dir.glob("*.json"):
            f.unlink()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, port=5001)