#!/usr/bin/env python3
"""Dependency-free Codex client for the ViralX web API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://viralx.metrolabs.mobi"
DEFAULT_TIMEOUT = 140

ENV_HEADER_MAP = {
    "ANALYSIS_MODE": "X-ViralX-Analysis-Mode",
    "MIN_LIKES": "X-ViralX-Min-Likes",
    "RAPIDAPI_KEY": "X-ViralX-RapidAPI-Key",
    "TK_NOTE_ASR_BACKEND": "X-ViralX-TK-ASR",
    "TK_NOTE_LANGUAGE": "X-ViralX-TK-Language",
    "TK_NOTE_TIMEOUT": "X-ViralX-TK-Timeout",
    "MODEL_PROVIDER": "X-ViralX-Model-Provider",
    "MODEL_PROTOCOL": "X-ViralX-Model-Protocol",
    "MODEL_API_KEY": "X-ViralX-Model-Key",
    "MODEL_BASE_URL": "X-ViralX-Model-Base-URL",
    "MODEL_NAME": "X-ViralX-Model-Name",
    "GEMINI_API_KEY": "X-ViralX-Gemini-Key",
    "GEMINI_MODEL": "X-ViralX-Gemini-Model",
    "OPENROUTER_API_KEY": "X-ViralX-OpenRouter-Key",
    "OPENROUTER_MODEL": "X-ViralX-OpenRouter-Model",
    "MINIMAX_API_KEY": "X-ViralX-MiniMax-Key",
    "MINIMAX_MODEL": "X-ViralX-MiniMax-Model",
}


def api_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    path = "/" + endpoint.lstrip("/")
    return f"{base}{path}" if base.endswith("/api") else f"{base}/api{path}"


def credential_headers(environ: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    values = os.environ if environ is None else environ
    headers = {"Accept": "application/json"}
    for env_name, header_name in ENV_HEADER_MAP.items():
        value = str(values.get(env_name) or "").strip()
        if value:
            headers[header_name] = value
    return headers


def _error_message(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    suffix = f": {body[:500]}" if body else ""
    return f"ViralX HTTP {exc.code}{suffix}"


def fetch_json(base_url: str, endpoint: str, timeout: int) -> object:
    request = Request(api_url(base_url, endpoint), headers=credential_headers(), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(_error_message(exc)) from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"ViralX network error: {exc}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ViralX returned invalid JSON") from exc


def stream_analyze(
    base_url: str,
    payload: Mapping[str, object],
    timeout: int,
    extra_headers: Optional[Mapping[str, str]] = None,
    output_path: Optional[Path] = None,
) -> int:
    headers = credential_headers()
    headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update({key: str(value) for key, value in extra_headers.items() if value is not None})
    request = Request(
        api_url(base_url, "analyze"),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    output_handle = None
    saw_event = False
    application_error = False
    try:
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_handle = output_path.open("w", encoding="utf-8")
        try:
            response_context = urlopen(request, timeout=timeout)
        except HTTPError as exc:
            raise RuntimeError(_error_message(exc)) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"ViralX network error: {exc}") from exc

        with response_context as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                saw_event = True
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("ViralX returned invalid NDJSON") from exc
                normalized = json.dumps(event, ensure_ascii=False)
                print(normalized, flush=True)
                if output_handle:
                    output_handle.write(normalized + "\n")
                    output_handle.flush()
                if isinstance(event, dict) and event.get("status") == "error":
                    application_error = True
    finally:
        if output_handle:
            output_handle.close()

    if not saw_event:
        raise RuntimeError("ViralX returned an empty analysis stream")
    return 2 if application_error else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call the ViralX web API from Codex")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VIRALX_BASE_URL", DEFAULT_BASE_URL),
        help="ViralX site URL; defaults to production or VIRALX_BASE_URL",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="Show credential-safe readiness")
    commands.add_parser("keywords", help="List available topics")

    analyze = commands.add_parser("analyze", help="Analyze a video URL or search topic")
    analyze.add_argument("source", help="TikTok/Douyin URL or search topic")
    analyze.add_argument("--product-name", default="", help="Product name for remake guidance")
    analyze.add_argument("--product-info", default="", help="Product selling points and constraints")
    analyze.add_argument("--refresh", action="store_true", help="Refresh evidence before analysis")
    analyze.add_argument("--min-likes", type=int, help="Override API23 minimum likes")
    analyze.add_argument(
        "--analysis-mode",
        choices=("libtv", "model", "gemini", "openrouter", "minimax"),
        help="Override the configured analysis provider",
    )
    analyze.add_argument(
        "--model-provider",
        choices=("openai", "anthropic", "gemini", "deepseek", "openrouter", "custom"),
        help="Select the provider used when analysis mode is model",
    )
    analyze.add_argument("--model-protocol", choices=("openai", "anthropic"), help="Protocol for a custom provider")
    analyze.add_argument("--model-base-url", help="Base URL for a custom provider")
    analyze.add_argument("--model-name", help="Provider model ID")
    analyze.add_argument("--output", type=Path, help="Also save the NDJSON stream to this path")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"health", "keywords"}:
            result = fetch_json(args.base_url, args.command, args.timeout)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        payload = {
            "keyword": args.source.strip(),
            "refresh": bool(args.refresh),
            "product_name": args.product_name,
            "product_info": args.product_info,
        }
        headers = {}
        if args.min_likes is not None:
            headers["X-ViralX-Min-Likes"] = str(max(0, args.min_likes))
        if args.analysis_mode:
            headers["X-ViralX-Analysis-Mode"] = args.analysis_mode
        if args.model_provider:
            headers["X-ViralX-Model-Provider"] = args.model_provider
            headers.setdefault("X-ViralX-Analysis-Mode", "model")
        if args.model_protocol:
            headers["X-ViralX-Model-Protocol"] = args.model_protocol
        if args.model_base_url:
            headers["X-ViralX-Model-Base-URL"] = args.model_base_url
        if args.model_name:
            headers["X-ViralX-Model-Name"] = args.model_name
        return stream_analyze(
            args.base_url,
            payload,
            args.timeout,
            extra_headers=headers,
            output_path=args.output,
        )
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
