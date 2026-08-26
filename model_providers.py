"""Shared model-provider presets, migration, and custom endpoint validation."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


MODEL_PROVIDER_PRESETS = {
    "openai": {
        "label": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
        "vision": True,
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "model": "claude-sonnet-5",
        "vision": True,
    },
    "gemini": {
        "label": "Google Gemini",
        "protocol": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": "gemini-3.7-flash",
        "vision": True,
    },
    "deepseek": {
        "label": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "vision": False,
    },
    "openrouter": {
        "label": "OpenRouter",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/auto",
        "vision": True,
    },
    "custom": {
        "label": "自定义 API",
        "protocol": "openai",
        "base_url": "",
        "model": "",
        "vision": True,
    },
}

SUPPORTED_MODEL_PROVIDERS = frozenset(MODEL_PROVIDER_PRESETS)
SUPPORTED_MODEL_PROTOCOLS = frozenset({"openai", "anthropic"})
LEGACY_PROVIDER_FIELDS = {
    "gemini": ("gemini_api_key", "", "gemini_model", "gemini"),
    "openrouter": ("openrouter_api_key", "", "openrouter_model", "openai"),
    "minimax": ("minimax_api_key", "minimax_base_url", "minimax_model", "anthropic"),
}


def _is_public_address(hostname: str) -> bool:
    """Reject literal or DNS-resolved loopback/private/link-local destinations."""
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            }
        except (OSError, ValueError):
            return False
    return bool(addresses) and all(address.is_global for address in addresses)


def validate_custom_base_url(value: str, *, allow_private: bool = False) -> str:
    """Return a normalized API root or raise an actionable validation error."""
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        raise ValueError("自定义 API 需要填写 Base URL")
    try:
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").strip().lower()
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Base URL 格式无效，请填写完整接口地址") from exc
    allowed_schemes = {"https"} | ({"http"} if allow_private else set())
    if parsed.scheme not in allowed_schemes or not hostname or parsed.username or parsed.password:
        scheme_hint = "HTTP(S)" if allow_private else "HTTPS"
        raise ValueError(f"Base URL 必须是无账号信息的完整 {scheme_hint} 地址")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL 不能包含查询参数或锚点")
    if not allow_private:
        if port not in (None, 443):
            raise ValueError("云端自定义 Base URL 仅允许标准 HTTPS 端口")
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
            raise ValueError("云端自定义 Base URL 不能指向本机或内网地址")
        if not _is_public_address(hostname):
            raise ValueError("云端自定义 Base URL 必须解析到公网地址")
    return raw


def normalize_model_config(config: dict, *, allow_private_custom: bool = False) -> dict:
    """Migrate legacy provider fields into one provider-neutral model contract."""
    normalized = dict(config or {})
    mode = str(normalized.get("analysis_mode") or "pipeline").strip().lower()
    legacy_provider = mode if mode in LEGACY_PROVIDER_FIELDS else ""
    if legacy_provider:
        mode = "model"
    # ViralX now has one serial pipeline. Legacy values remain readable, but
    # they no longer skip either LibTV shot analysis or the final model pass.
    normalized["analysis_mode"] = "pipeline"

    provider = str(normalized.get("model_provider") or "").strip().lower()
    if not provider and legacy_provider:
        provider = "custom" if legacy_provider == "minimax" else legacy_provider
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        provider = "openai"
    preset = MODEL_PROVIDER_PRESETS[provider]

    legacy_key = legacy_base = legacy_model = ""
    legacy_protocol = ""
    source_provider = legacy_provider or provider
    if source_provider in LEGACY_PROVIDER_FIELDS:
        key_field, base_field, model_field, legacy_protocol = LEGACY_PROVIDER_FIELDS[source_provider]
        legacy_key = str(normalized.get(key_field) or "").strip()
        legacy_base = str(normalized.get(base_field) or "").strip() if base_field else ""
        legacy_model = str(normalized.get(model_field) or "").strip()

    protocol = str(normalized.get("model_protocol") or legacy_protocol or preset["protocol"]).strip().lower()
    if provider != "custom":
        protocol = preset["protocol"]
    elif protocol not in SUPPORTED_MODEL_PROTOCOLS:
        protocol = "openai"

    model_base_url = str(normalized.get("model_base_url") or legacy_base or preset["base_url"]).strip()
    normalized.pop("model_config_error", None)
    if provider == "custom":
        try:
            model_base_url = validate_custom_base_url(
                model_base_url,
                allow_private=allow_private_custom,
            )
        except ValueError as exc:
            normalized["model_config_error"] = str(exc)
            model_base_url = ""
    else:
        model_base_url = preset["base_url"]

    normalized.update({
        "model_provider": provider,
        "model_protocol": protocol,
        "model_supports_vision": bool(preset.get("vision", True)),
        "model_api_key": str(normalized.get("model_api_key") or legacy_key or "").strip(),
        "model_base_url": model_base_url,
        "model_name": str(normalized.get("model_name") or legacy_model or preset["model"]).strip(),
    })
    return normalized


def model_is_ready(config: dict) -> bool:
    """Credential-safe readiness check for the selected model provider."""
    if config.get("model_config_error"):
        return False
    return bool(
        str(config.get("model_api_key") or "").strip()
        and str(config.get("model_name") or "").strip()
        and str(config.get("model_base_url") or "").strip()
    )
