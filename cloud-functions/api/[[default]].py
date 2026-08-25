"""EdgeOne Cloud Functions entrypoint for ViralX's public-safe API surface."""

from __future__ import annotations

import os
import re
import sys
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import Flask, Response, has_request_context, jsonify, request


FUNCTIONS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = FUNCTIONS_DIR.parent
for module_dir in (FUNCTIONS_DIR, PROJECT_ROOT):
    module_value = str(module_dir)
    if module_value not in sys.path:
        sys.path.insert(0, module_value)

os.environ.setdefault("VIRALX_RUNTIME", "edgeone")
os.environ.setdefault("VIRALX_MAX_ANALYZE_VIDEOS", "1")
os.environ.setdefault("VIRALX_CACHE_DIR", "/tmp/viralx/cache")
os.environ.setdefault("VIRALX_OUTPUT_DIR", "/tmp/viralx/data")
os.environ.setdefault("VIRALX_VIDEO_CACHE_DIR", "/tmp/viralx/video_cache")
os.environ.setdefault("LIBTV_TIMEOUT", "100")
os.environ.setdefault("TK_NOTE_TIMEOUT", "90")

staged_tk_note = FUNCTIONS_DIR / "vendor" / "tk_note" / "extract_tiktok_text.py"
source_tk_note = PROJECT_ROOT / ".agents" / "skills" / "tk-note" / "scripts" / "extract_tiktok_text.py"
tk_note_script = staged_tk_note if staged_tk_note.is_file() else source_tk_note
if tk_note_script.is_file():
    os.environ.setdefault("VIRALX_TK_NOTE_SCRIPT", str(tk_note_script))

staged_libtv = FUNCTIONS_DIR / "vendor" / "libtv"
source_libtv = PROJECT_ROOT / ".agents" / "skills" / "libtv-skill" / "scripts"
libtv_scripts = staged_libtv if staged_libtv.is_dir() else source_libtv
if libtv_scripts.is_dir():
    os.environ.setdefault("VIRALX_LIBTV_SCRIPTS_DIR", str(libtv_scripts))

from ai_analyzer import AIAnalyzer  # noqa: E402
from model_providers import model_is_ready, normalize_model_config  # noqa: E402
from tiktok_viral_analyzer import TikTokViralAnalyzer  # noqa: E402


MAX_ANALYZE_VIDEOS = max(1, min(int(os.environ.get("VIRALX_MAX_ANALYZE_VIDEOS", "1")), 5))


def _number(name, fallback, cast):
    try:
        return cast(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


def load_config():
    """Build cloud config from server env plus session-only BYOK headers."""
    config = {
        "rapidapi_key": os.environ.get("RAPIDAPI_KEY", ""),
        "analysis_mode": os.environ.get("ANALYSIS_MODE", "libtv"),
        "libtv_access_key": os.environ.get("LIBTV_ACCESS_KEY", ""),
        "libtv_im_base": os.environ.get("OPENAPI_IM_BASE", "https://im.liblib.tv"),
        "libtv_poll_interval": _number("LIBTV_POLL_INTERVAL", 8, float),
        "libtv_timeout": min(_number("LIBTV_TIMEOUT", 100, float), 100),
        "tk_note_asr_backend": os.environ.get("TK_NOTE_ASR_BACKEND", "auto"),
        "tk_note_language": os.environ.get("TK_NOTE_LANGUAGE", "auto"),
        "tk_note_cookies_from_browser": "",
        "tk_note_proxy": os.environ.get("TK_NOTE_PROXY", ""),
        "tk_note_timeout": min(_number("TK_NOTE_TIMEOUT", 90, float), 90),
        "video_cache_dir": os.environ.get("VIRALX_VIDEO_CACHE_DIR", "/tmp/viralx/video_cache"),
        "model_provider": os.environ.get("MODEL_PROVIDER", ""),
        "model_protocol": os.environ.get("MODEL_PROTOCOL", ""),
        "model_api_key": os.environ.get("MODEL_API_KEY", ""),
        "model_base_url": os.environ.get("MODEL_BASE_URL", ""),
        "model_name": os.environ.get("MODEL_NAME", ""),
        "gemini_api_key": os.environ.get("GEMINI_API_KEY", ""),
        "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-3.7-flash"),
        "openrouter_api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "openrouter_model": os.environ.get(
            "OPENROUTER_MODEL",
            "openrouter/auto",
        ),
        "minimax_api_key": os.environ.get("MINIMAX_API_KEY", ""),
        "minimax_base_url": os.environ.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/anthropic"),
        "minimax_model": os.environ.get("MINIMAX_MODEL", "MiniMax-M2.7"),
        "search_keywords": [
            value.strip()
            for value in os.environ.get("VIRALX_SEARCH_KEYWORDS", "").split(",")
            if value.strip()
        ],
        "min_likes": _number("MIN_LIKES", 5000, int),
        "output_dir": os.environ.get("VIRALX_OUTPUT_DIR", "/tmp/viralx/data"),
    }
    if not has_request_context():
        return normalize_model_config(config, allow_private_custom=False)

    string_headers = {
        "X-ViralX-Analysis-Mode": "analysis_mode",
        "X-ViralX-RapidAPI-Key": "rapidapi_key",
        "X-ViralX-LibTV-Key": "libtv_access_key",
        "X-ViralX-Model-Provider": "model_provider",
        "X-ViralX-Model-Protocol": "model_protocol",
        "X-ViralX-Model-Key": "model_api_key",
        "X-ViralX-Model-Base-URL": "model_base_url",
        "X-ViralX-Model-Name": "model_name",
        "X-ViralX-Gemini-Key": "gemini_api_key",
        "X-ViralX-Gemini-Model": "gemini_model",
        "X-ViralX-OpenRouter-Key": "openrouter_api_key",
        "X-ViralX-OpenRouter-Model": "openrouter_model",
        "X-ViralX-MiniMax-Key": "minimax_api_key",
        "X-ViralX-MiniMax-Model": "minimax_model",
        "X-ViralX-TK-ASR": "tk_note_asr_backend",
        "X-ViralX-TK-Language": "tk_note_language",
    }
    for header_name, config_name in string_headers.items():
        value = str(request.headers.get(header_name) or "").strip()
        if value:
            config[config_name] = value[:4096]

    asr_mode = str(config.get("tk_note_asr_backend") or "auto").lower()
    config["tk_note_asr_backend"] = asr_mode if asr_mode in {"auto", "none", "qwen3-asr", "whisper"} else "auto"

    numeric_headers = {
        "X-ViralX-Min-Likes": ("min_likes", 0, 1_000_000_000, int),
        "X-ViralX-LibTV-Poll": ("libtv_poll_interval", 1, 30, float),
        "X-ViralX-LibTV-Timeout": ("libtv_timeout", 30, 100, float),
        "X-ViralX-TK-Timeout": ("tk_note_timeout", 30, 90, float),
    }
    for header_name, (config_name, minimum, maximum, cast) in numeric_headers.items():
        value = request.headers.get(header_name)
        if value in (None, ""):
            continue
        try:
            config[config_name] = max(minimum, min(cast(value), maximum))
        except (TypeError, ValueError):
            continue
    return normalize_model_config(config, allow_private_custom=False)


def is_video_url(value):
    try:
        parsed = urlparse((value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


def direct_video_data(video_url):
    video_id = hashlib.sha256(video_url.encode("utf-8")).hexdigest()[:20]
    host = urlparse(video_url).netloc.lower().removeprefix("www.")
    return {
        "video_id": video_id,
        "title": f"视频链接 · {host}",
        "author": host,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "views": 0,
        "cover": "",
        "duration": 0,
        "source_url": video_url,
    }


app = Flask(__name__)


def _configured_state():
    config = load_config()
    mode = str(config.get("analysis_mode") or "libtv").lower()
    provider_ready = {
        "libtv": bool(config.get("libtv_access_key")),
        "model": model_is_ready(config),
    }
    return config, mode, provider_ready


@app.get("/health")
def health():
    """Readiness without returning any credential values."""
    config, mode, provider_ready = _configured_state()
    provider = config.get("model_provider", "openai") if mode == "model" else "libtv"
    return jsonify({
        "status": "ok",
        "runtime": "edgeone",
        "keyword_search_provider": TikTokViralAnalyzer.SEARCH_PROVIDER,
        "analysis_provider": provider,
        "analysis_ready": provider_ready.get(mode, False),
        "configured": {
            **provider_ready,
            "keyword_search": bool(config.get("rapidapi_key")),
        },
        "limits": {
            "max_videos": MAX_ANALYZE_VIDEOS,
            "request_seconds": 120,
            "response_megabytes": 6,
        },
        "exports": {"obsidian": "browser"},
    })


@app.get("/capabilities")
def capabilities():
    return health()


@app.post("/analyze")
def analyze():
    data = request.get_json(silent=True) or {}
    keyword = str(data.get("keyword") or "").strip()
    refresh = bool(data.get("refresh", False))
    product_name = str(data.get("product_name") or "")
    product_info = str(data.get("product_info") or "")
    config = load_config()

    def generate():
        try:
            if not keyword:
                yield json.dumps({
                    "status": "error",
                    "message": "请输入关键词或抖音/TikTok 视频链接",
                    "done": True,
                }, ensure_ascii=False) + "\n"
                return

            tiktok = None
            if is_video_url(keyword):
                video_data = [direct_video_data(keyword)]
                video_urls = {video_data[0]["video_id"]: keyword}
            else:
                if not config["rapidapi_key"]:
                    yield json.dumps({
                        "status": "error",
                        "message": "API23 关键词搜索尚未配置 RAPIDAPI_KEY；也可以直接粘贴 TikTok / 抖音视频链接",
                        "done": True,
                    }, ensure_ascii=False) + "\n"
                    return
                tiktok = TikTokViralAnalyzer(config["output_dir"])
                tiktok.api_key = config["rapidapi_key"]
                videos = tiktok.search_viral_videos(keyword, config["min_likes"], count=30)
                video_data = [tiktok.extract_video_info(video) for video in videos]
                video_urls = {
                    video["video_id"]: f"https://www.tiktok.com/@{video['author']}/video/{video['video_id']}"
                    for video in video_data
                }

            if not video_data:
                yield json.dumps({"status": "error", "message": "未找到相关视频", "done": True}, ensure_ascii=False) + "\n"
                return

            ai = AIAnalyzer(
                api_key=config["minimax_api_key"],
                base_url=config["minimax_base_url"],
                model=config["minimax_model"],
                analysis_mode=config["analysis_mode"],
                model_provider=config["model_provider"],
                model_protocol=config["model_protocol"],
                model_api_key=config["model_api_key"],
                model_base_url=config["model_base_url"],
                model_name=config["model_name"],
                libtv_access_key=config["libtv_access_key"],
                libtv_im_base=config["libtv_im_base"],
                libtv_poll_interval=config["libtv_poll_interval"],
                libtv_timeout=config["libtv_timeout"],
                video_cache_dir=config["video_cache_dir"],
                tk_note_asr_backend=config["tk_note_asr_backend"],
                tk_note_language=config["tk_note_language"],
                tk_note_cookies_from_browser="",
                tk_note_proxy=config["tk_note_proxy"],
                tk_note_timeout=config["tk_note_timeout"],
            )

            results = []
            for result in ai.batch_analyze_streaming(
                video_data,
                max_videos=MAX_ANALYZE_VIDEOS,
                video_urls=video_urls,
                product_name=product_name,
                product_info=product_info,
                force_collect=refresh,
            ):
                if tiktok:
                    try:
                        result["comments_data"] = tiktok.get_video_comments(result["video_id"])
                    except Exception:
                        result["comments_data"] = []
                else:
                    result["comments_data"] = []
                results.append(result)
                yield json.dumps({
                    "status": "progress",
                    "done": False,
                    "current": len(results),
                    "total": min(len(video_data), MAX_ANALYZE_VIDEOS),
                    "video": result,
                }, ensure_ascii=False) + "\n"

            failed = sum(1 for item in results if item.get("libtv_status") == "error")
            pending = sum(1 for item in results if item.get("libtv_status") == "timeout")
            yield json.dumps({
                "status": "success",
                "total_videos": len(results),
                "failed_videos": failed,
                "pending_videos": pending,
                "videos": results,
                "source": "live",
                "done": True,
            }, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"status": "error", "message": str(exc), "done": True}, ensure_ascii=False) + "\n"

    return Response(generate(), mimetype="application/x-ndjson", headers={
        "X-Accel-Buffering": "no",
        "Cache-Control": "no-cache",
    })


@app.get("/keywords")
def keywords():
    config = load_config()
    values = []
    for keyword in config["search_keywords"]:
        cache_file = Path(config["output_dir"]) / f"{keyword.replace(' ', '_')}_analysis.json"
        if cache_file.exists():
            values.append({"keyword": keyword, "cached": True})
    return jsonify({"keywords": values})


@app.post("/generate_variants")
def generate_variants():
    data = request.get_json(silent=True) or {}
    analysis = str(data.get("analysis") or "")
    if not analysis:
        return jsonify({"status": "error", "message": "缺少原始视频分析内容"}), 400
    try:
        config = load_config()
        analyzer = AIAnalyzer(
            api_key=config["minimax_api_key"],
            base_url=config["minimax_base_url"],
            model=config["minimax_model"],
        )
        variants = analyzer.generate_viral_variants(data.get("video") or {}, analysis)
        return jsonify({"status": "success", "variants": variants})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.post("/export-obsidian")
def export_obsidian():
    """Return a browser-safe Markdown export instead of writing server files."""
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "AI 深度拆解").strip()[:80]
    content = str(data.get("content") or "")
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title).strip(" .-") or "AI 深度拆解"
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_title}.md"
    note_path = f"抖音爆款视频分析/{filename[:-3]}"
    obsidian_uri = None
    if len(content) <= 12000:
        obsidian_uri = (
            "obsidian://new?file="
            f"{quote(note_path, safe='')}&content={quote(content, safe='')}"
        )
    return jsonify({
        "status": "success",
        "mode": "browser",
        "filename": filename,
        "content": content,
        "obsidian_uri": obsidian_uri,
        "message": "已准备 Obsidian URI" if obsidian_uri else "内容较长，已准备 Markdown 下载",
    })


def handler(event, context=None):
    """Compatibility export used by EdgeOne's Python runtime."""
    return app
