#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public-safe ViralX worker intended to run on the project owner's computer.

The static EdgeOne site calls this small API through an HTTPS tunnel.  Local
settings, cache management, filesystem export, and LibTV account controls are
intentionally not mounted here.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any

from flask import Flask, jsonify, make_response, request

from model_providers import normalize_model_config
import web_app


WORKER_VERSION = "1.1.0"
WORKER_ID = "viralx-home-worker"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MAX_REQUEST_BYTES = 96 * 1024
DEFAULT_ALLOWED_ORIGINS = {
    "https://viralx.metrolabs.mobi",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5001",
    "http://localhost:5001",
}
ALLOWED_REQUEST_HEADERS = {
    "content-type",
    "x-viralx-min-likes",
    "x-viralx-rapidapi-key",
    "x-viralx-model-provider",
    "x-viralx-model-protocol",
    "x-viralx-model-key",
    "x-viralx-model-base-url",
    "x-viralx-model-name",
    "x-viralx-shot-threshold",
}


def _env_int(name: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        value = fallback
    return min(max(value, minimum), maximum)


def allowed_origins() -> set[str]:
    configured = {
        value.strip().rstrip("/")
        for value in os.environ.get("VIRALX_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    return DEFAULT_ALLOWED_ORIGINS | configured


class SlidingWindowLimiter:
    """Small in-memory limiter suitable for a single-machine portfolio demo."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def admit(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - events[0])))
                return False, retry_after
            events.append(now)
            return True, 0


def _client_key() -> str:
    if os.environ.get("VIRALX_TRUST_PROXY_HEADERS", "1") == "1":
        forwarded = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded:
            return forwarded[:96]
    return (request.remote_addr or "unknown")[:96]


def _request_config() -> dict[str, Any]:
    """Overlay safe BYOK fields while keeping machine capabilities owner-managed."""
    config = dict(web_app.load_config())
    config["analysis_mode"] = "pipeline"
    if os.environ.get("VIRALX_ALLOW_BROWSER_OVERRIDES", "1") != "1":
        return normalize_model_config(config, allow_private_custom=False)

    string_headers = {
        "rapidapi_key": "X-ViralX-RapidAPI-Key",
        "model_provider": "X-ViralX-Model-Provider",
        "model_protocol": "X-ViralX-Model-Protocol",
        "model_api_key": "X-ViralX-Model-Key",
        "model_base_url": "X-ViralX-Model-Base-URL",
        "model_name": "X-ViralX-Model-Name",
    }
    for field, header in string_headers.items():
        value = request.headers.get(header, "").strip()
        if value:
            config[field] = value[:4096]

    try:
        config["min_likes"] = min(
            max(int(request.headers.get("X-ViralX-Min-Likes", "")), 0),
            100_000_000,
        )
    except (TypeError, ValueError):
        pass
    try:
        config["shot_scene_threshold"] = min(
            max(float(request.headers.get("X-ViralX-Shot-Threshold", "")), 5.0),
            80.0,
        )
    except (TypeError, ValueError):
        pass

    # Public visitors cannot select a local browser cookie store, proxy, LibTV
    # account, filesystem path, or pipeline implementation on the owner's PC.
    return normalize_model_config(config, allow_private_custom=False)


def _cleanup_expired_cache(config: dict[str, Any]) -> None:
    retention_hours = _env_int("VIRALX_RETENTION_HOURS", 24, 1, 24 * 30)
    cutoff = time.time() - retention_hours * 3600
    cache_root = Path(config.get("video_cache_dir") or "./video_cache").expanduser().resolve()
    if not cache_root.is_dir() or cache_root == cache_root.parent:
        return
    for child in cache_root.iterdir():
        try:
            resolved = child.resolve()
            if resolved.parent != cache_root or child.stat().st_mtime > cutoff:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        except OSError:
            continue


def create_worker_app(origin_allowlist: set[str] | None = None) -> Flask:
    origins = set(origin_allowlist or allowed_origins())
    max_concurrent = _env_int("VIRALX_MAX_CONCURRENT", 1, 1, 2)
    analysis_slots = threading.BoundedSemaphore(max_concurrent)
    limiter = SlidingWindowLimiter(
        _env_int("VIRALX_RATE_LIMIT_ANALYSES", 6, 1, 100),
        _env_int("VIRALX_RATE_WINDOW_SECONDS", 3600, 60, 86_400),
    )
    cleanup_lock = threading.Lock()
    app = Flask("viralx_public_worker")
    app.config.update(MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES)

    @app.before_request
    def enforce_origin_and_preflight():
        origin = request.headers.get("Origin", "").rstrip("/")
        local_probe = not origin and (request.remote_addr or "") in {"127.0.0.1", "::1"}
        if not local_probe and origin not in origins:
            return jsonify({"status": "error", "message": "Origin is not allowed"}), 403
        if request.method == "OPTIONS":
            requested_headers = {
                value.strip().lower()
                for value in request.headers.get("Access-Control-Request-Headers", "").split(",")
                if value.strip()
            }
            if not requested_headers.issubset(ALLOWED_REQUEST_HEADERS):
                return jsonify({"status": "error", "message": "Requested headers are not allowed"}), 403
            return make_response("", 204)
        return None

    @app.after_request
    def add_security_headers(response):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = ", ".join(sorted(ALLOWED_REQUEST_HEADERS))
            # Tailscale Funnel hostnames resolve inside 100.64.0.0/10. Chromium
            # therefore performs a Private Network Access preflight even though
            # the Funnel itself is public HTTPS. Only the existing origin
            # allowlist may receive this opt-in response.
            if response.status_code < 400:
                response.headers["Access-Control-Allow-Private-Network"] = "true"
            response.headers.add("Vary", "Origin")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/")
    @app.get("/api/health")
    def health():
        current_config = _request_config()
        payload = web_app.build_health_payload(current_config, runtime_override="worker")
        payload.update({
            "release": WORKER_VERSION,
            "service": {
                "id": WORKER_ID,
                "mode": "home-server",
                "managed_credentials": True,
                "browser_overrides": os.environ.get("VIRALX_ALLOW_BROWSER_OVERRIDES", "1") == "1",
                "max_concurrent": max_concurrent,
                "retention_hours": _env_int("VIRALX_RETENTION_HOURS", 24, 1, 24 * 30),
            },
        })
        payload["exports"] = {"obsidian": "browser"}
        return jsonify(payload)

    @app.post("/api/analyze")
    def analyze():
        body = request.get_json(silent=True) or {}
        keyword = str(body.get("keyword", "")).strip()
        if not keyword or len(keyword) > 4096:
            return jsonify({
                "status": "error",
                "message": "请输入不超过 4096 字符的视频链接或搜索主题。",
            }), 400
        if len(str(body.get("product_name", ""))) > 200 or len(str(body.get("product_info", ""))) > 8000:
            return jsonify({"status": "error", "message": "产品信息超过公开分析服务限制。"}), 400

        if not analysis_slots.acquire(blocking=False):
            response = jsonify({
                "status": "error",
                "message": "ViralX 正在处理另一条视频，请等待当前任务完成后再试。",
            })
            response.status_code = 409
            response.headers["Retry-After"] = "30"
            return response

        admitted, retry_after = limiter.admit(_client_key())
        if not admitted:
            analysis_slots.release()
            response = jsonify({
                "status": "error",
                "message": "当前体验次数已用完，请稍后再试。",
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response

        current_config = _request_config()
        if cleanup_lock.acquire(blocking=False):
            def clean_then_release():
                try:
                    _cleanup_expired_cache(current_config)
                finally:
                    cleanup_lock.release()
            threading.Thread(target=clean_then_release, name="viralx-cache-cleanup", daemon=True).start()

        try:
            response = web_app.build_analyze_response(
                config_override=current_config,
                max_videos=web_app.MAX_ANALYZE_VIDEOS,
            )
        except Exception:
            analysis_slots.release()
            raise
        original_iterable = response.response

        def guarded_stream():
            try:
                yield from original_iterable
            finally:
                analysis_slots.release()

        response.response = guarded_stream()
        return response

    @app.get("/api/keywords")
    def keywords():
        return web_app.get_keywords()

    @app.post("/api/generate_variants")
    def variants():
        return web_app.generate_variants(config_override=_request_config())

    return app


app = create_worker_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the public-safe ViralX home worker")
    parser.add_argument("--host", default=os.environ.get("VIRALX_WORKER_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("VIRALX_WORKER_PORT", DEFAULT_PORT)))
    args = parser.parse_args()
    print(f"[ViralX Worker] http://{args.host}:{args.port}")
    print("[ViralX Worker] Only the restricted analysis API is mounted. Press Ctrl+C to stop.")
    try:
        from waitress import serve
    except ImportError as exc:
        raise SystemExit("缺少 waitress，请执行 python -m pip install -r requirements.txt") from exc
    serve(app, host=args.host, port=args.port, threads=4, channel_timeout=7200)


if __name__ == "__main__":
    main()
