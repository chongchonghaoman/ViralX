#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TikTok 分析工具 - Web 可视化界面"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from flask import Flask, render_template, request, jsonify, Response
import json
import hashlib
import os
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import threading
import queue
from tiktok_viral_analyzer import TikTokViralAnalyzer
from ai_analyzer import AIAnalyzer
from model_providers import model_is_ready, normalize_model_config

app = Flask(__name__)
CONFIG_PATH = Path(__file__).parent / "config.json"
IS_EDGE_RUNTIME = os.environ.get('VIRALX_RUNTIME', '').lower() == 'edgeone'


def _env_number(name, fallback, cast):
    value = os.environ.get(name)
    if value in (None, ''):
        return fallback
    try:
        return cast(value)
    except (TypeError, ValueError):
        return fallback


MAX_ANALYZE_VIDEOS = max(
    1,
    min(_env_number('VIRALX_MAX_ANALYZE_VIDEOS', 5, int), 5),
)

DEFAULT_CONFIG = {
    'rapidapi_key': '',
    'analysis_mode': 'libtv',
    'libtv_access_key': '',
    'libtv_im_base': 'https://im.liblib.tv',
    'libtv_poll_interval': 8,
    'libtv_timeout': 180,
    'libtv_concurrency': 2,
    'tk_note_asr_backend': 'auto',
    'tk_note_language': 'auto',
    'tk_note_cookies_from_browser': '',
    'tk_note_proxy': '',
    'tk_note_timeout': 1800,
    'video_cache_dir': './video_cache',
    'model_provider': '',
    'model_protocol': '',
    'model_api_key': '',
    'model_base_url': '',
    'model_name': '',
    'gemini_api_key': '',
    'gemini_model': 'gemini-3.7-flash',
    'openrouter_api_key': '',
    'openrouter_model': 'openrouter/auto',
    'minimax_api_key': '',
    'minimax_base_url': 'https://api.minimaxi.com/anthropic',
    'minimax_model': 'MiniMax-M2.7',
    'search_keywords': [],
    'min_likes': 5000,
    'output_dir': './data',
}

def load_config():
    """从本地配置和环境变量加载配置；环境变量始终优先。"""
    loaded = {}
    if CONFIG_PATH.exists():
        loaded = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    merged = {**DEFAULT_CONFIG, **loaded}

    env_map = {
        'RAPIDAPI_KEY': ('rapidapi_key', str),
        'ANALYSIS_MODE': ('analysis_mode', str),
        'LIBTV_ACCESS_KEY': ('libtv_access_key', str),
        'OPENAPI_IM_BASE': ('libtv_im_base', str),
        'LIBTV_POLL_INTERVAL': ('libtv_poll_interval', float),
        'LIBTV_TIMEOUT': ('libtv_timeout', float),
        'LIBTV_CONCURRENCY': ('libtv_concurrency', int),
        'TK_NOTE_ASR_BACKEND': ('tk_note_asr_backend', str),
        'TK_NOTE_LANGUAGE': ('tk_note_language', str),
        'TK_NOTE_COOKIES_FROM_BROWSER': ('tk_note_cookies_from_browser', str),
        'TK_NOTE_PROXY': ('tk_note_proxy', str),
        'TK_NOTE_TIMEOUT': ('tk_note_timeout', float),
        'MODEL_PROVIDER': ('model_provider', str),
        'MODEL_PROTOCOL': ('model_protocol', str),
        'MODEL_API_KEY': ('model_api_key', str),
        'MODEL_BASE_URL': ('model_base_url', str),
        'MODEL_NAME': ('model_name', str),
        'GEMINI_API_KEY': ('gemini_api_key', str),
        'GEMINI_MODEL': ('gemini_model', str),
        'OPENROUTER_API_KEY': ('openrouter_api_key', str),
        'OPENROUTER_MODEL': ('openrouter_model', str),
        'MINIMAX_API_KEY': ('minimax_api_key', str),
        'MINIMAX_BASE_URL': ('minimax_base_url', str),
        'MINIMAX_MODEL': ('minimax_model', str),
        'MIN_LIKES': ('min_likes', int),
        'VIRALX_OUTPUT_DIR': ('output_dir', str),
        'VIRALX_VIDEO_CACHE_DIR': ('video_cache_dir', str),
    }
    for env_name, (config_name, cast) in env_map.items():
        value = os.environ.get(env_name)
        if value in (None, ''):
            continue
        try:
            merged[config_name] = cast(value)
        except (TypeError, ValueError):
            continue

    keyword_value = os.environ.get('VIRALX_SEARCH_KEYWORDS', '')
    if keyword_value:
        merged['search_keywords'] = [
            item.strip() for item in keyword_value.split(',') if item.strip()
        ]

    if IS_EDGE_RUNTIME:
        merged['output_dir'] = os.environ.get('VIRALX_OUTPUT_DIR', '/tmp/viralx/data')
        merged['video_cache_dir'] = os.environ.get('VIRALX_VIDEO_CACHE_DIR', '/tmp/viralx/video_cache')
        merged['libtv_timeout'] = min(float(merged.get('libtv_timeout', 100)), 100)
        merged['tk_note_timeout'] = min(float(merged.get('tk_note_timeout', 90)), 90)
    return normalize_model_config(merged, allow_private_custom=not IS_EDGE_RUNTIME)

def save_config(data):
    """保存配置到 config.json"""
    if IS_EDGE_RUNTIME:
        raise RuntimeError('云端设置由 EdgeOne 环境变量管理，不能从网页写入')
    merged = {**DEFAULT_CONFIG, **(data or {})}
    CONFIG_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding='utf-8')


def is_video_url(value):
    """判断输入是否为可交给 yt-dlp 的 HTTP(S) 视频链接。"""
    try:
        parsed = urlparse((value or '').strip())
        return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)
    except ValueError:
        return False


def direct_video_data(video_url):
    """为抖音/TikTok 直链构建统一的视频数据结构。"""
    video_id = hashlib.sha256(video_url.encode('utf-8')).hexdigest()[:20]
    host = urlparse(video_url).netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    return {
        'video_id': video_id,
        'title': f'视频链接 · {host}',
        'author': host,
        'likes': 0,
        'comments': 0,
        'shares': 0,
        'views': 0,
        'cover': '',
        'duration': 0,
        'source_url': video_url,
    }

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
        config = load_config()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """返回不含密钥的运行状态，供本地与 EdgeOne 前端探活。"""
    current_config = load_config()
    runtime = 'edgeone' if IS_EDGE_RUNTIME else 'local'
    mode = str(current_config.get('analysis_mode', 'libtv')).lower()
    provider = current_config.get('model_provider', 'openai') if mode == 'model' else 'libtv'
    readiness = {
        'libtv': bool(current_config.get('libtv_access_key')),
        'model': model_is_ready(current_config),
    }
    return jsonify({
        'status': 'ok',
        'runtime': runtime,
        'keyword_search_provider': TikTokViralAnalyzer.SEARCH_PROVIDER,
        'analysis_provider': provider,
        'analysis_ready': readiness.get(mode, False),
        'configured': {
            **readiness,
            'keyword_search': bool(current_config.get('rapidapi_key')),
        },
        'limits': {
            'max_videos': MAX_ANALYZE_VIDEOS,
            'request_seconds': 120 if IS_EDGE_RUNTIME else None,
        },
        'exports': {
            'obsidian': 'browser' if IS_EDGE_RUNTIME else 'filesystem',
        },
    })

@app.route('/api/analyze', methods=['POST'])
def analyze():
    """
    执行分析 — 流式响应。
    边并发分析视频边返回结果，前端逐个看到分析完成。
    """
    data = request.json
    keyword = (data.get('keyword') or '').strip()
    refresh = data.get('refresh', False)
    product_name = data.get('product_name', '')
    product_info = data.get('product_info', '')

    def generate():
        try:
            current_config = load_config()

            if not keyword:
                yield json.dumps({'status': 'error', 'message': '请输入关键词或抖音/TikTok 视频链接', 'done': True}, ensure_ascii=False) + '\n'
                return

            # 支持直接粘贴抖音/TikTok 链接；关键词则保留原有榜单搜索。
            tiktok = None
            if is_video_url(keyword):
                video_data = [direct_video_data(keyword)]
                video_urls = {video_data[0]['video_id']: keyword}
            else:
                if not current_config.get('rapidapi_key'):
                    yield json.dumps({
                        'status': 'error',
                        'message': 'API23 关键词搜索尚未配置 RAPIDAPI_KEY；也可以直接粘贴 TikTok / 抖音视频链接',
                        'done': True,
                    }, ensure_ascii=False) + '\n'
                    return
                tiktok = TikTokViralAnalyzer(current_config['output_dir'])
                tiktok.api_key = current_config['rapidapi_key']
                videos = tiktok.search_viral_videos(keyword, current_config['min_likes'], count=30)
                video_data = [tiktok.extract_video_info(v) for v in videos]
                video_urls = {
                    v['video_id']: f"https://www.tiktok.com/@{v['author']}/video/{v['video_id']}"
                    for v in video_data
                }

            if not video_data:
                yield json.dumps({'status': 'error', 'message': '未找到相关视频', 'done': True}, ensure_ascii=False) + '\n'
                return

            # 创建 AI 分析器
            ai = AIAnalyzer(
                api_key=current_config.get('minimax_api_key'),
                base_url=current_config.get('minimax_base_url'),
                model=current_config.get('minimax_model'),
                analysis_mode=current_config.get('analysis_mode', 'libtv'),
                model_provider=current_config.get('model_provider', 'openai'),
                model_protocol=current_config.get('model_protocol', 'openai'),
                model_api_key=current_config.get('model_api_key', ''),
                model_base_url=current_config.get('model_base_url', ''),
                model_name=current_config.get('model_name', ''),
                libtv_access_key=current_config.get('libtv_access_key', ''),
                libtv_im_base=current_config.get('libtv_im_base', 'https://im.liblib.tv'),
                libtv_poll_interval=current_config.get('libtv_poll_interval', 8),
                libtv_timeout=current_config.get('libtv_timeout', 180),
                video_cache_dir=current_config.get('video_cache_dir', './video_cache'),
                tk_note_asr_backend=current_config.get('tk_note_asr_backend', 'auto'),
                tk_note_language=current_config.get('tk_note_language', 'auto'),
                tk_note_cookies_from_browser=current_config.get('tk_note_cookies_from_browser', ''),
                tk_note_proxy=current_config.get('tk_note_proxy', ''),
                tk_note_timeout=current_config.get('tk_note_timeout', 1800),
            )

            # 流式并发分析，结果边完成边推送
            results = []
            for result in ai.batch_analyze_streaming(
                video_data,
                max_videos=MAX_ANALYZE_VIDEOS,
                video_urls=video_urls,
                product_name=product_name,
                product_info=product_info,
                force_collect=bool(refresh),
            ):
                # 抓取评论（在主线程串行执行，不影响并发分析）
                if tiktok:
                    try:
                        comments = tiktok.get_video_comments(result['video_id'])
                        result['comments_data'] = comments
                    except Exception as e:
                        print(f"[评论抓取失败] {e}")
                        result['comments_data'] = []
                else:
                    result['comments_data'] = []

                results.append(result)

                # 每完成一个就推送一个，前端可以立即显示
                yield json.dumps({
                    'status': 'progress',
                    'done': False,
                    'current': len(results),
                    'total': min(len(video_data), MAX_ANALYZE_VIDEOS),
                    'video': result
                }, ensure_ascii=False) + '\n'

            # 推送完成信号
            failed_videos = sum(
                1 for item in results if item.get('libtv_status') == 'error'
            )
            pending_videos = sum(
                1 for item in results if item.get('libtv_status') == 'timeout'
            )
            yield json.dumps({
                'status': 'success',
                'total_videos': len(results),
                'failed_videos': failed_videos,
                'pending_videos': pending_videos,
                'videos': results,
                'source': 'live',
                'done': True
            }, ensure_ascii=False) + '\n'

        except Exception as e:
            yield json.dumps({'status': 'error', 'message': str(e), 'done': True}, ensure_ascii=False) + '\n'

    return Response(generate(), mimetype='application/x-ndjson', headers={
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
