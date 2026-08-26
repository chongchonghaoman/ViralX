#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security boundary between the hosted ViralX UI and this computer.

The connector intentionally exposes a very small API. It never serves the local
settings, cache-management, or filesystem export routes from ``web_app.py``.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from flask import Flask, jsonify, make_response, request

import web_app


CONNECTOR_VERSION = "1.0.0"
CONNECTOR_HOST = "127.0.0.1"
CONNECTOR_PORT = 57231
CONNECTOR_ORIGIN = f"http://{CONNECTOR_HOST}:{CONNECTOR_PORT}"
PRODUCTION_ORIGIN = "https://viralx.metrolabs.mobi"
LOCAL_PAIRING_PATH = "/connector/v1/pairing/new"
PAIRING_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 12 * 60 * 60
MAX_REQUEST_BYTES = 512 * 1024

DEFAULT_ALLOWED_ORIGINS = {
    PRODUCTION_ORIGIN,
    "http://127.0.0.1:4173",
    "http://localhost:4173",
    "http://127.0.0.1:5001",
    "http://localhost:5001",
}

ALLOWED_REQUEST_HEADERS = {
    "content-type",
    "x-viralx-connector-token",
    "x-viralx-analysis-mode",
    "x-viralx-min-likes",
    "x-viralx-rapidapi-key",
    "x-viralx-tk-asr",
    "x-viralx-tk-language",
    "x-viralx-tk-timeout",
    "x-viralx-model-provider",
    "x-viralx-model-protocol",
    "x-viralx-model-key",
    "x-viralx-model-base-url",
    "x-viralx-model-name",
}


def allowed_origins() -> set[str]:
    """Return the exact hosted/dev origins allowed to call loopback."""
    configured = {
        value.strip().rstrip("/")
        for value in os.environ.get("VIRALX_CONNECTOR_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    return DEFAULT_ALLOWED_ORIGINS | configured


@dataclass
class PairingBroker:
    """One-use bootstrap secrets and short-lived in-memory browser sessions."""

    pairing_ttl: int = PAIRING_TTL_SECONDS
    session_ttl: int = SESSION_TTL_SECONDS
    _pairing: dict[str, float] = field(default_factory=dict)
    _sessions: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _purge(self, now: float) -> None:
        self._pairing = {token: expiry for token, expiry in self._pairing.items() if expiry > now}
        self._sessions = {token: expiry for token, expiry in self._sessions.items() if expiry > now}

    def issue_pairing_secret(self) -> str:
        secret = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._pairing[secret] = now + self.pairing_ttl
        return secret

    def pair(self, pairing_secret: str) -> tuple[str, int] | None:
        candidate = str(pairing_secret or "")
        if not candidate:
            return None
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            matched = next(
                (token for token in self._pairing if hmac.compare_digest(token, candidate)),
                None,
            )
            if not matched:
                return None
            del self._pairing[matched]
            session = secrets.token_urlsafe(32)
            self._sessions[session] = now + self.session_ttl
            return session, self.session_ttl

    def authorized(self, session_token: str) -> bool:
        candidate = str(session_token or "")
        if not candidate:
            return False
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            return any(hmac.compare_digest(token, candidate) for token in self._sessions)

    def revoke(self, session_token: str) -> None:
        candidate = str(session_token or "")
        with self._lock:
            matched = next(
                (token for token in self._sessions if hmac.compare_digest(token, candidate)),
                None,
            )
            if matched:
                del self._sessions[matched]


def _connector_token() -> str:
    return request.headers.get("X-ViralX-Connector-Token", "")


def _request_config() -> dict[str, Any]:
    """Overlay the current tab's settings for the trusted local pipeline."""
    config = dict(web_app.load_config())
    config["analysis_mode"] = "pipeline"

    rapidapi_key = request.headers.get("X-ViralX-RapidAPI-Key", "").strip()
    if rapidapi_key:
        config["rapidapi_key"] = rapidapi_key

    asr = request.headers.get("X-ViralX-TK-ASR", "").strip().lower()
    if asr in {"auto", "none", "qwen3-asr", "whisper"}:
        config["tk_note_asr_backend"] = asr

    language = request.headers.get("X-ViralX-TK-Language", "").strip()
    if language:
        config["tk_note_language"] = language[:40]

    model_fields = {
        "model_provider": "X-ViralX-Model-Provider",
        "model_protocol": "X-ViralX-Model-Protocol",
        "model_api_key": "X-ViralX-Model-Key",
        "model_base_url": "X-ViralX-Model-Base-URL",
        "model_name": "X-ViralX-Model-Name",
    }
    for field, header in model_fields.items():
        value = request.headers.get(header, "").strip()
        if value:
            config[field] = value

    try:
        min_likes = int(request.headers.get("X-ViralX-Min-Likes", ""))
        config["min_likes"] = min(max(min_likes, 0), 100_000_000)
    except (TypeError, ValueError):
        pass

    try:
        timeout = int(request.headers.get("X-ViralX-TK-Timeout", ""))
        config["tk_note_timeout"] = min(max(timeout, 30), 7200)
    except (TypeError, ValueError):
        pass
    return config


def create_connector_app(
    broker: PairingBroker | None = None,
    origin_allowlist: set[str] | None = None,
) -> tuple[Flask, PairingBroker]:
    broker = broker or PairingBroker()
    origins = set(origin_allowlist or allowed_origins())
    app = Flask("viralx_local_connector")
    app.config.update(MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES)

    @app.before_request
    def enforce_origin_and_preflight():
        origin = request.headers.get("Origin", "").rstrip("/")
        if request.path == LOCAL_PAIRING_PATH:
            remote_address = request.remote_addr or ""
            if request.method == "POST" and not origin and remote_address in {"127.0.0.1", "::1"}:
                return None
            return jsonify({"status": "error", "message": "Local pairing control is not allowed"}), 403
        if origin not in origins:
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
    def add_connector_headers(response):
        origin = request.headers.get("Origin", "").rstrip("/")
        if origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = ", ".join(
                sorted(ALLOWED_REQUEST_HEADERS)
            )
            if request.headers.get("Access-Control-Request-Private-Network") == "true":
                response.headers["Access-Control-Allow-Private-Network"] = "true"
            response.headers.add("Vary", "Origin")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def require_session():
        if broker.authorized(_connector_token()):
            return None
        return jsonify({
            "status": "error",
            "state": "pairing_required",
            "message": "请从本机 Connector 打开的 ViralX 页面重新完成配对。",
        }), 401

    @app.get("/connector/v1/status")
    def connector_status():
        paired = broker.authorized(_connector_token())
        payload: dict[str, Any] = {
            "status": "ok",
            "connector": "viralx-local",
            "version": CONNECTOR_VERSION,
            "paired": paired,
            "session_scope": "memory",
        }
        if paired:
            payload["libtv"] = web_app.libtv_auth.status(
                force=request.args.get("refresh") == "1"
            )
        else:
            payload["state"] = "pairing_required"
            payload["message"] = "Connector 已启动；请使用它自动打开的网页完成一次性配对。"
        return jsonify(payload)

    @app.post("/connector/v1/pair")
    def pair_browser():
        body = request.get_json(silent=True) or {}
        paired = broker.pair(body.get("pairing_secret", ""))
        if not paired:
            return jsonify({
                "status": "error",
                "state": "pairing_failed",
                "message": "一次性配对链接无效或已过期，请重启 Connector。",
            }), 401
        session, expires_in = paired
        return jsonify({
            "status": "ok",
            "paired": True,
            "session_token": session,
            "expires_in": expires_in,
        })

    @app.post(LOCAL_PAIRING_PATH)
    def issue_pairing_link():
        body = request.get_json(silent=True) or {}
        site = str(body.get("site", PRODUCTION_ORIGIN)).strip().rstrip("/")
        if site not in origins:
            return jsonify({"status": "error", "message": "Pairing site is not allowed"}), 400
        pairing_secret = broker.issue_pairing_secret()
        pairing_url = (
            f"{site}/settings.html"
            f"#viralx-connector={quote(pairing_secret, safe='')}"
        )
        return jsonify({"status": "ok", "pairing_url": pairing_url})

    @app.post("/connector/v1/session/logout")
    def unpair_browser():
        denied = require_session()
        if denied:
            return denied
        broker.revoke(_connector_token())
        return jsonify({"status": "ok", "paired": False})

    @app.get("/connector/v1/libtv/status")
    def libtv_status():
        denied = require_session()
        if denied:
            return denied
        return jsonify(web_app.libtv_auth.status(force=request.args.get("refresh") == "1"))

    @app.post("/connector/v1/libtv/login/start")
    def libtv_login_start():
        denied = require_session()
        if denied:
            return denied
        state = web_app.libtv_auth.start_login()
        return jsonify(state), 200 if state.get("state") != "unavailable" else 503

    @app.post("/connector/v1/libtv/logout")
    def libtv_logout():
        denied = require_session()
        if denied:
            return denied
        return jsonify(web_app.libtv_auth.logout())

    @app.post("/connector/v1/analyze")
    def analyze_with_libtv():
        denied = require_session()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        keyword = str(body.get("keyword", "")).strip()
        if not keyword or len(keyword) > 4096:
            return jsonify({
                "status": "error",
                "message": "请输入不超过 4096 字符的视频链接或搜索主题。",
            }), 400
        if len(str(body.get("product_name", ""))) > 200 or len(str(body.get("product_info", ""))) > 8000:
            return jsonify({"status": "error", "message": "产品信息超过 Connector 限制。"}), 400
        return web_app.build_analyze_response(
            config_override=_request_config(),
            max_videos=web_app.MAX_ANALYZE_VIDEOS,
        )

    return app, broker
