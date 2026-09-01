#!/usr/bin/env python3
"""TikTok viral-video discovery and stable metadata normalization for ViralX."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
from urllib.parse import quote, urlparse

import requests


def safe_error_message(value: Any, secrets: Iterable[Any] = ()) -> str:
    """Keep diagnostics useful while removing credentials and token-shaped text."""
    text = str(value or "").strip().replace("\n", " ")
    for secret in secrets:
        secret_value = str(secret or "")
        if secret_value:
            text = text.replace(secret_value, "[redacted]")
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    text = re.sub(
        r"(?i)(authorization|access[_ -]?token|refresh[_ -]?token|api[_ -]?key)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    return text[:600]


class RapidAPISearchError(RuntimeError):
    """A provider request or business-response failure in the search chain."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class API23SearchError(RapidAPISearchError):
    """A TikTok API23 request or business-response failure."""


class Scraper7SearchError(RapidAPISearchError):
    """A TikTok Scraper7 request or business-response failure."""


class TikTokSearchChainError(Scraper7SearchError):
    """All attempted providers failed; remains catchable as the legacy fallback error."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "search_chain_failed",
        provider_errors: List[Dict[str, Any]] | None = None,
        subscription_links: List[Dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.provider_errors = list(provider_errors or [])
        self.subscription_links = list(subscription_links or [])


class TikTokViralAnalyzer:
    """Discover TikTok videos through a quota-aware multi-provider search chain."""

    SEARCH_PROVIDER = "rapidapi-multisource"
    SEARCH_STRATEGY = "api6-scraptik-scraper7-download5-tokapi-download1-api15"
    PRIMARY_SEARCH_PROVIDER = "api6"
    FALLBACK_SEARCH_PROVIDER = "scraper7"
    DEFAULT_SEARCH_PROVIDER_CHAIN = (
        "api6",
        "scraptik",
        "scraper7",
        "download5",
        "tokapi",
        "download1",
        "api15",
    )
    SEARCH_PROVIDERS = {
        "api6": {
            "label": "TikTok API6",
            "host": "tiktok-api6.p.rapidapi.com",
            "url": "https://tiktok-api6.p.rapidapi.com/search/general/query",
            "subscription_url": "https://rapidapi.com/omarmhaimdat/api/tiktok-api6/pricing",
            "subscription_note": "推荐优先订阅；关键词相关性表现更稳定",
            "params": "api6",
            "items": "root_videos",
            "page_size": 20,
        },
        "scraptik": {
            "label": "ScrapTik",
            "host": "scraptik.p.rapidapi.com",
            "url": "https://scraptik.p.rapidapi.com/search-posts",
            "subscription_url": "https://rapidapi.com/scraptik-api-scraptik-api-default/api/scraptik/pricing",
            "subscription_note": "成熟的 TikTok 搜索与数据来源",
            "params": "mobile",
            "items": "search_items",
            "page_size": 10,
        },
        "scraper7": {
            "label": "TikTok Scraper7",
            "host": "tiktok-scraper7.p.rapidapi.com",
            "url": "https://tiktok-scraper7.p.rapidapi.com/feed/search",
            "subscription_url": "https://rapidapi.com/tikwm-tikwm-default/api/tiktok-scraper7/pricing",
            "subscription_note": "ViralX 的稳定补充搜索源",
            "params": "feed",
            "items": "data_videos",
            "page_size": 30,
        },
        "download5": {
            "label": "TikTok Download5 Search",
            "host": "tiktok-download5.p.rapidapi.com",
            "url": "https://tiktok-download5.p.rapidapi.com/feedSearch",
            "subscription_url": "https://rapidapi.com/llbbmm/api/tiktok-download5/pricing",
            "subscription_note": "包含关键词搜索能力，不只用于下载",
            "params": "feed",
            "items": "data_videos",
            "page_size": 10,
        },
        "tokapi": {
            "label": "TokApi Mobile",
            "host": "tokapi-mobile-version.p.rapidapi.com",
            "url": "https://tokapi-mobile-version.p.rapidapi.com/v1/search/post",
            "subscription_url": "https://rapidapi.com/Sonjik/api/tokapi-mobile-version/pricing",
            "subscription_note": "移动端数据结构的补充来源",
            "params": "mobile",
            "items": "search_items",
            "page_size": 10,
        },
        "download1": {
            "label": "TikTok Download Video1 Search",
            "host": "tiktok-download-video1.p.rapidapi.com",
            "url": "https://tiktok-download-video1.p.rapidapi.com/feedSearch",
            "subscription_url": "https://rapidapi.com/llbbmm/api/tiktok-download-video1/pricing",
            "subscription_note": "包含 Search 套件的补充来源",
            "params": "feed",
            "items": "data_videos",
            "page_size": 10,
        },
        "api15": {
            "label": "TikTok API15",
            "host": "tiktok-api15.p.rapidapi.com",
            "url": "https://tiktok-api15.p.rapidapi.com/index/Tiktok/searchVideoListByKeywords",
            "subscription_url": "https://rapidapi.com/search?term=TikTok%20API&sortBy=ByRelevance",
            "subscription_note": "当前没有公开定价页；在市场中查找可用替代",
            "params": "api15",
            "items": "data_videos",
            "page_size": 10,
        },
    }
    API23_SEARCH_HOST = "tiktok-api23.p.rapidapi.com"
    API23_SEARCH_URL = f"https://{API23_SEARCH_HOST}/api/search/video"
    SCRAPER7_SEARCH_HOST = "tiktok-scraper7.p.rapidapi.com"
    SCRAPER7_SEARCH_URL = f"https://{SCRAPER7_SEARCH_HOST}/feed/search"
    # Backwards-compatible aliases for integrations that imported the old constants.
    SEARCH_HOST = SCRAPER7_SEARCH_HOST
    SEARCH_URL = SCRAPER7_SEARCH_URL
    SEARCH_TIMEOUT_SECONDS = 20
    VIDEO_LIST_KEYS = ("videos", "items", "video_list", "videoList")
    API23_VIDEO_LIST_KEYS = ("item_list", "itemList", "aweme_list", "awemeList", "videos")
    POST_ID_PATTERN = re.compile(r"^\d{15,25}$")
    POST_URL_PATTERN = re.compile(r"/video/(\d{15,25})(?:[/?#]|$)", re.IGNORECASE)
    SOURCE_URL_KEYS = ("share_url", "shareUrl", "web_url", "webUrl", "source_url", "sourceUrl", "url")
    MEDIA_URL_KEYS = (
        "play", "play_url", "playUrl", "play_addr", "playAddr",
        "download", "download_url", "downloadUrl", "download_addr", "downloadAddr",
        "hdplay", "wmplay", "nowm", "no_watermark",
    )

    @classmethod
    def provider_subscription_links(cls, provider_ids: Iterable[str]) -> List[Dict[str, Any]]:
        """Return safe, user-facing RapidAPI subscription destinations in chain order."""
        links: List[Dict[str, Any]] = []
        for provider_id in provider_ids:
            provider = cls.SEARCH_PROVIDERS.get(str(provider_id))
            if not isinstance(provider, Mapping):
                continue
            url = str(provider.get("subscription_url") or "").strip()
            try:
                parsed = urlparse(url)
                safe_port = parsed.port in {None, 443}
            except ValueError:
                continue
            if not (
                parsed.scheme == "https"
                and parsed.hostname == "rapidapi.com"
                and not parsed.username
                and not parsed.password
                and safe_port
            ):
                continue
            links.append({
                "provider": str(provider_id),
                "label": str(provider.get("label") or provider_id),
                "url": url,
                "note": str(provider.get("subscription_note") or "查看 RapidAPI 订阅方案"),
                "recommended": str(provider_id) == cls.PRIMARY_SEARCH_PROVIDER,
                "direct": "/pricing" in url,
            })
        return links
    MEDIA_HOST_SUFFIXES = (
        "tiktok.com", "tiktokcdn.com", "tiktokv.com", "byteoversea.com",
        "ibytedtos.com", "musical.ly", "tikwm.com",
    )
    PICTURE_LIGHT_INTENT = re.compile(
        r"(?i)\bpicture\s+lights?\b|\bpainting\s+lights?\b|照画灯|壁画灯|画框灯"
    )
    PICTURE_LIGHT_QUERY = "picture light wall mounted artwork lamp"
    PICTURE_LIGHT_NEGATIVE = re.compile(
        r"(?i)\blight\s+paintings?\b|\blight\s+pictures?\b|\bglowing\s+(?:art|pictures?|paintings?|canvas)\b|"
        r"\bluminous\s+(?:art|pictures?|paintings?|canvas)\b|\bbacklit\s+(?:art|pictures?|paintings?|canvas)\b|"
        r"\bled\s+(?:art|pictures?|paintings?|canvas)\b|световая\s+картина|发光画|灯光画|光影画"
    )

    def __init__(self, output_dir="E:/tiktok_analyzer/data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = ""  # RapidAPI key; only used for keyword discovery.
        self.search_provider_chain = tuple(self.DEFAULT_SEARCH_PROVIDER_CHAIN)
        self.last_search_diagnostics: Dict[str, Any] = {}

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _integer(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _post_id_from_value(cls, value: Any) -> str:
        """Return only a real TikTok post ID, never a CDN/media resource ID."""
        candidate = str(value or "").strip()
        return candidate if cls.POST_ID_PATTERN.fullmatch(candidate) else ""

    @classmethod
    def _post_identity(cls, item: Mapping[str, Any]) -> tuple[str, str]:
        """Resolve the canonical numeric post ID and a usable TikTok page URL."""
        video = cls._mapping(item.get("video"))

        # Provider responses may expose a canonical page URL. It is the most
        # reliable source because it binds the post ID to the original author.
        for container in (item, video):
            for key in cls.SOURCE_URL_KEYS:
                source_url = str(container.get(key) or "").strip()
                if "tiktok.com/" not in source_url.lower():
                    continue
                match = cls.POST_URL_PATTERN.search(source_url)
                if match:
                    return match.group(1), source_url

        # A provider may put an opaque `v260...` media resource ID in aweme_id or
        # video_id. TikTok page IDs are decimal int64 values, so reject opaque
        # identifiers instead of fabricating a URL that can never open.
        for value in (
            item.get("id"),
            item.get("aweme_id"),
            item.get("item_id"),
            item.get("itemId"),
            item.get("video_id"),
            video.get("id"),
        ):
            post_id = cls._post_id_from_value(value)
            if post_id:
                author_value = item.get("author")
                author = cls._mapping(author_value)
                unique_id = str(
                    author.get("unique_id")
                    or author.get("uniqueId")
                    or author.get("sec_uid")
                    or (author_value if isinstance(author_value, str) else "")
                    or item.get("author_name")
                    or item.get("unique_id")
                    or "tiktok"
                ).strip().lstrip("@")
                safe_author = quote(unique_id or "tiktok", safe="._-")
                return post_id, f"https://www.tiktok.com/@{safe_author}/video/{post_id}"

        return "", ""

    @classmethod
    def _safe_media_transport_url(cls, item: Mapping[str, Any]) -> str:
        """Return one short-lived media URL for in-memory handoff only.

        Provider response variants use several wrappers. The selected URL is
        never serialized into ViralX results or evidence files; TK Note consumes
        it as an optional transport hint and still verifies the canonical post ID.
        """
        def values(value: Any) -> Iterable[str]:
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, str):
                        yield child
            elif isinstance(value, Mapping):
                for key in ("url_list", "urlList", "urls", "url", "src"):
                    yield from values(value.get(key))

        video = cls._mapping(item.get("video"))
        for container in (item, video):
            for key in cls.MEDIA_URL_KEYS:
                for candidate in values(container.get(key)):
                    candidate = candidate.strip()
                    try:
                        parsed = urlparse(candidate)
                    except ValueError:
                        continue
                    host = (parsed.hostname or "").lower()
                    if (
                        parsed.scheme in {"http", "https"}
                        and host
                        and not parsed.username
                        and not parsed.password
                        and any(host == suffix or host.endswith(f".{suffix}") for suffix in cls.MEDIA_HOST_SUFFIXES)
                    ):
                        return candidate
        return ""

    @classmethod
    def _search_plan(cls, keyword: str) -> Dict[str, Any]:
        """Resolve ambiguous product language before sending it to TikTok search."""
        clean_keyword = str(keyword or "").strip()
        if cls.PICTURE_LIGHT_INTENT.search(clean_keyword):
            return {
                "intent": "picture-light-fixture",
                "query": cls.PICTURE_LIGHT_QUERY,
                "label": "照画灯（安装在画作上方的灯具）",
            }
        return {"intent": "generic", "query": clean_keyword, "label": clean_keyword}

    @classmethod
    def _search_relevance(cls, video: Mapping[str, Any], intent: str) -> tuple[int, str]:
        """Score product relevance before engagement so popularity cannot hide a category mismatch."""
        if intent != "picture-light-fixture":
            return 0, ""

        title = str(video.get("title") or video.get("desc") or "")
        hashtags = " ".join(str(value) for value in (video.get("hashtags") or []))
        text = f"{title} {hashtags}".lower().strip()
        if cls.PICTURE_LIGHT_NEGATIVE.search(text):
            return 0, "opposite-light-art"

        score = 0
        if re.search(r"(?i)\bpicture\s+lights?\b|照画灯|壁画灯|画框灯", text):
            score += 6
        if re.search(r"(?i)\bpainting\s+lights?\b|\bgallery\s+lights?\b", text):
            score += 4

        art_context = bool(re.search(r"(?i)\bpicture|painting|artwork|portrait|frame|gallery|canvas\b|画作|画框|壁画", text))
        fixture_context = bool(re.search(
            r"(?i)\blamp|sconce|fixture|rechargeable|battery|wireless|mounted|lighting\b|灯具|壁灯|照明",
            text,
        ))
        placement_context = bool(re.search(r"(?i)\bwall|above|over|mount|frame\b|墙面|上方|画框", text))
        if art_context and fixture_context:
            score += 3
        if placement_context:
            score += 2

        return (score, "") if score >= 4 else (0, "insufficient-fixture-context")

    @classmethod
    def _new_provider_diagnostics(
        cls,
        provider: str,
        clean_keyword: str,
        search_plan: Mapping[str, Any],
        threshold: int,
    ) -> Dict[str, Any]:
        return {
            "provider": provider,
            "keyword": clean_keyword,
            "search_query": str(search_plan.get("query") or ""),
            "search_intent": str(search_plan.get("intent") or "generic"),
            "search_intent_label": str(search_plan.get("label") or clean_keyword),
            "threshold": threshold,
            "raw_items": 0,
            "valid_post_ids": 0,
            "normalized_items": 0,
            "filtered_by_likes": 0,
            "invalid_post_ids": 0,
            "rejected_irrelevant": 0,
            "max_likes": 0,
            "responses": 0,
            "recognized_lists": 0,
            "requests": 0,
            "response_shapes": [],
            "error": "",
        }

    def _set_chain_diagnostics(
        self,
        providers: Mapping[str, Dict[str, Any]],
        *,
        selected_provider: str = "",
        fallback_used: bool = False,
        fallback_reason: str = "",
        attempted_providers: Iterable[str] = (),
        result_providers: Iterable[str] = (),
        selected_items: int = 0,
    ) -> None:
        provider_values = [value for value in providers.values() if isinstance(value, Mapping)]
        active = providers.get(selected_provider) or (provider_values[0] if provider_values else {})
        self.last_search_diagnostics = {
            **active,
            "provider": self.SEARCH_PROVIDER,
            "selected_provider": selected_provider,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "strategy": self.SEARCH_STRATEGY,
            "attempted_providers": list(attempted_providers),
            "result_providers": list(dict.fromkeys(result_providers)),
            "selected_items": selected_items,
            "raw_items": sum(self._integer(item.get("raw_items")) for item in provider_values),
            "valid_post_ids": sum(self._integer(item.get("valid_post_ids")) for item in provider_values),
            "normalized_items": sum(self._integer(item.get("normalized_items")) for item in provider_values),
            "filtered_by_likes": sum(self._integer(item.get("filtered_by_likes")) for item in provider_values),
            "invalid_post_ids": sum(self._integer(item.get("invalid_post_ids")) for item in provider_values),
            "rejected_irrelevant": sum(self._integer(item.get("rejected_irrelevant")) for item in provider_values),
            "max_likes": max((self._integer(item.get("max_likes")) for item in provider_values), default=0),
            "responses": sum(self._integer(item.get("responses")) for item in provider_values),
            "recognized_lists": sum(self._integer(item.get("recognized_lists")) for item in provider_values),
            "requests": sum(self._integer(item.get("requests")) for item in provider_values),
            "providers": dict(providers),
        }

    @staticmethod
    def _first_url(value: Any) -> str:
        """Read a representative URL from common TikTok URL wrappers."""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            for child in value:
                result = TikTokViralAnalyzer._first_url(child)
                if result:
                    return result
        if isinstance(value, Mapping):
            for key in ("url_list", "urlList", "urls", "url", "src"):
                result = TikTokViralAnalyzer._first_url(value.get(key))
                if result:
                    return result
        return ""

    @classmethod
    def _normalize_video(cls, item: Dict, provider: str) -> Dict:
        """Normalize provider variants into the stable ViralX discovery schema."""
        author_value = item.get("author")
        author = cls._mapping(author_value)
        stats = cls._mapping(item.get("stats"))
        stats_v2 = cls._mapping(item.get("statsV2") or item.get("stats_v2"))
        statistics = cls._mapping(item.get("statistics") or item.get("statistics_v2"))
        video = cls._mapping(item.get("video"))
        video_id, source_url = cls._post_identity(item)
        media_transport_url = cls._safe_media_transport_url(item)

        def text_value(value: Any) -> str:
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                return " ".join(filter(None, (text_value(child) for child in value))).strip()
            if isinstance(value, Mapping):
                for key in ("text", "title", "desc", "description"):
                    result = text_value(value.get(key))
                    if result:
                        return result
            return ""

        title = ""
        for value in (item.get("title"), item.get("desc"), item.get("description"), item.get("content_desc")):
            title = text_value(value)
            if title:
                break

        challenges = item.get("challenges") if isinstance(item.get("challenges"), list) else []
        hashtags = [
            str(cls._mapping(challenge).get("title") or "").strip()
            for challenge in challenges
            if str(cls._mapping(challenge).get("title") or "").strip()
        ]
        text_extra = item.get("text_extra") or item.get("textExtra")
        if not hashtags and isinstance(text_extra, list):
            hashtags = [
                str(
                    cls._mapping(extra).get("hashtag_name")
                    or cls._mapping(extra).get("hashtagName")
                    or ""
                ).strip()
                for extra in text_extra
                if str(
                    cls._mapping(extra).get("hashtag_name")
                    or cls._mapping(extra).get("hashtagName")
                    or ""
                ).strip()
            ]
        if not hashtags:
            hashtags = list(dict.fromkeys(re.findall(r"(?<!\w)#([\w-]+)", title)))

        def metric(*keys: str) -> int:
            for container in (item, stats, stats_v2, statistics):
                for key in keys:
                    if key in container and container.get(key) not in (None, ""):
                        return cls._integer(container.get(key))
            return 0

        cover = ""
        for value in (
            item.get("cover"), item.get("origin_cover"), item.get("originCover"),
            video.get("cover"), video.get("origin_cover"), video.get("originCover"),
            video.get("dynamic_cover"), video.get("dynamicCover"),
        ):
            cover = cls._first_url(value)
            if cover:
                break

        unique_id = str(
            author.get("unique_id")
            or author.get("uniqueId")
            or author.get("sec_uid")
            or author.get("id")
            or (author_value if isinstance(author_value, str) else "")
            or item.get("author_name")
            or item.get("unique_id")
            or ""
        )
        return {
            "video_id": str(video_id or ""),
            "source_url": source_url,
            "title": title,
            "author": {"unique_id": unique_id},
            "digg_count": metric("digg_count", "diggCount", "like_count", "likes", "number_of_hearts"),
            "comment_count": metric("comment_count", "commentCount", "comments", "number_of_comments"),
            "share_count": metric("share_count", "shareCount", "shares", "number_of_reposts"),
            "play_count": metric("play_count", "playCount", "view_count", "views", "number_of_plays"),
            "collect_count": metric("collect_count", "collectCount", "saves", "number_of_saves"),
            "cover": cover,
            "duration": cls._integer(item.get("duration", video.get("duration"))),
            "hashtags": list(dict.fromkeys(hashtags)),
            "create_time": cls._integer(item.get("create_time", item.get("createTime"))),
            "is_ad": bool(item.get("is_ad", item.get("isAd", False))),
            "search_provider": provider,
            # Private, short-lived pipeline field. extract_video_info deliberately
            # omits it so signed media addresses never reach API/UI output.
            "_media_transport_url": media_transport_url,
        }

    @classmethod
    def _select_provider_items(
        cls,
        items: Iterable[Dict],
        provider: str,
        search_plan: Mapping[str, Any],
        threshold: int,
        limit: int,
        diagnostics: Dict[str, Any],
        seen_video_ids: set,
        videos: List[Dict],
    ) -> None:
        materialized = list(items)
        diagnostics["raw_items"] += len(materialized)
        for item in materialized:
            video = cls._normalize_video(item, provider)
            video_id = video["video_id"]
            if not video_id:
                diagnostics["invalid_post_ids"] += 1
                continue
            diagnostics["valid_post_ids"] += 1
            relevance, rejection_reason = cls._search_relevance(video, str(search_plan.get("intent") or "generic"))
            if rejection_reason:
                diagnostics["rejected_irrelevant"] += 1
                continue
            video["search_relevance"] = relevance
            video["search_intent"] = str(search_plan.get("intent") or "generic")
            diagnostics["normalized_items"] += 1
            diagnostics["max_likes"] = max(diagnostics["max_likes"], video["digg_count"])
            if video["digg_count"] < threshold:
                diagnostics["filtered_by_likes"] += 1
                continue
            if video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)
            videos.append(video)
            if len(videos) >= limit:
                break

    @classmethod
    def _scraper7_items(cls, payload: Any) -> List[Dict]:
        """Read the documented data.videos list and a few safe legacy wrappers."""
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        for container in (nested, root):
            for key in cls.VIDEO_LIST_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        if isinstance(root.get("data"), list):
            return [item for item in root["data"] if isinstance(item, dict)]
        return []

    @classmethod
    def _scraper7_has_video_list(cls, payload: Any) -> bool:
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        return any(
            isinstance(container.get(key), list)
            for container in (nested, root)
            for key in cls.VIDEO_LIST_KEYS
        ) or isinstance(root.get("data"), list)

    @classmethod
    def _scraper7_response_shape(cls, payload: Any) -> Dict[str, Any]:
        """Summarize structure without retaining videos, text, URLs, or credentials."""
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        lists: List[str] = []
        for prefix, container in (("", root), ("data.", nested)):
            for key in cls.VIDEO_LIST_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    lists.append(f"{prefix}{key}={len(value)}")
        if isinstance(root.get("data"), list):
            lists.append(f"data={len(root['data'])}")
        return {
            "keys": sorted(str(key) for key in root.keys())[:12],
            "data_keys": sorted(str(key) for key in nested.keys())[:12],
            "lists": lists,
        }

    @classmethod
    def _scraper7_business_error(cls, payload: Any) -> str:
        """Return a safe message for RapidAPI responses whose HTTP status is 200."""
        root = cls._mapping(payload)
        code = root.get("code")
        success = root.get("success")
        failed = code not in (None, 0, "0", 200, "200") or success is False
        if not failed:
            return ""
        message = root.get("msg") or root.get("message") or root.get("error") or "服务返回业务错误"
        safe_message = safe_error_message(message)[:240]
        if code not in (None, ""):
            return f"{safe_message}（业务状态 {code}）"
        return safe_message

    @classmethod
    def _api23_items(cls, payload: Any) -> List[Dict]:
        def unwrap(items: Iterable[Any]) -> List[Dict]:
            normalized: List[Dict] = []
            for value in items:
                if not isinstance(value, Mapping):
                    continue
                candidate = value.get("item") or value.get("aweme_info") or value.get("awemeInfo") or value
                if isinstance(candidate, Mapping):
                    normalized.append(dict(candidate))
            return normalized

        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        for container in (root, nested):
            for key in cls.API23_VIDEO_LIST_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    return unwrap(value)
        if isinstance(root.get("data"), list):
            return unwrap(root["data"])
        return []

    @classmethod
    def _api23_has_video_list(cls, payload: Any) -> bool:
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        return any(
            isinstance(container.get(key), list)
            for container in (root, nested)
            for key in cls.API23_VIDEO_LIST_KEYS
        ) or isinstance(root.get("data"), list)

    @classmethod
    def _api23_response_shape(cls, payload: Any) -> Dict[str, Any]:
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        lists: List[str] = []
        for prefix, container in (("", root), ("data.", nested)):
            for key in cls.API23_VIDEO_LIST_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    lists.append(f"{prefix}{key}={len(value)}")
        if isinstance(root.get("data"), list):
            lists.append(f"data={len(root['data'])}")
        return {
            "keys": sorted(str(key) for key in root.keys())[:12],
            "data_keys": sorted(str(key) for key in nested.keys())[:12],
            "lists": lists,
        }

    @classmethod
    def _api23_business_error(cls, payload: Any) -> str:
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        code = root.get("status_code")
        if code in (None, ""):
            code = root.get("status")
        if code in (None, ""):
            code = nested.get("status_code", nested.get("status"))
        normalized_code = code.strip().lower() if isinstance(code, str) else code
        success_codes = (None, "", 0, "0", 200, "200", "ok", "success")
        if normalized_code is True or (
            not isinstance(normalized_code, bool) and normalized_code in success_codes
        ):
            return ""
        message = (
            root.get("status_msg") or root.get("message") or root.get("msg") or root.get("error")
            or nested.get("status_msg") or nested.get("message") or nested.get("msg") or nested.get("error")
        )
        safe_message = safe_error_message(message or "服务返回业务错误")[:240]
        return f"{safe_message}（业务状态 {code}）"

    @classmethod
    def _normalize_api23_video(cls, item: Dict) -> Dict:
        return cls._normalize_video(item, "api23")

    @classmethod
    def _normalize_scraper7_video(cls, item: Dict) -> Dict:
        """Normalize Scraper7's VideoInfo object to ViralX's stable schema."""
        return cls._normalize_video(item, cls.FALLBACK_SEARCH_PROVIDER)

    @classmethod
    def _provider_items(cls, payload: Any, item_mode: str) -> List[Dict]:
        root = cls._mapping(payload)
        if item_mode == "root_videos":
            value = root.get("videos")
            return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
        if item_mode == "search_items":
            value = root.get("search_item_list") or root.get("aweme_list")
            if not isinstance(value, list):
                return []
            items: List[Dict] = []
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                candidate = item.get("aweme_info") or item.get("awemeInfo") or item
                if isinstance(candidate, Mapping):
                    items.append(dict(candidate))
            return items
        return cls._scraper7_items(payload)

    @classmethod
    def _provider_has_video_list(cls, payload: Any, item_mode: str) -> bool:
        root = cls._mapping(payload)
        if item_mode == "root_videos":
            return isinstance(root.get("videos"), list)
        if item_mode == "search_items":
            return isinstance(root.get("search_item_list"), list) or isinstance(root.get("aweme_list"), list)
        return cls._scraper7_has_video_list(payload)

    @classmethod
    def _provider_response_shape(cls, payload: Any, item_mode: str) -> Dict[str, Any]:
        root = cls._mapping(payload)
        nested = cls._mapping(root.get("data"))
        list_keys: List[str] = []
        for prefix, container in (("", root), ("data.", nested)):
            for key in ("videos", "search_item_list", "aweme_list", "items", "video_list", "videoList"):
                value = container.get(key)
                if isinstance(value, list):
                    list_keys.append(f"{prefix}{key}={len(value)}")
        return {
            "keys": sorted(str(key) for key in root.keys())[:12],
            "data_keys": sorted(str(key) for key in nested.keys())[:12],
            "lists": list_keys,
            "adapter": item_mode,
        }

    @classmethod
    def _provider_business_error(cls, payload: Any) -> str:
        root = cls._mapping(payload)
        if "status_code" in root or "status" in root:
            return cls._api23_business_error(payload)
        return cls._scraper7_business_error(payload)

    @classmethod
    def _provider_params(
        cls,
        provider: Mapping[str, Any],
        query: str,
        limit: int,
    ) -> Dict[str, Any]:
        page_size = min(max(cls._integer(provider.get("page_size"), 10), 1), 30)
        param_mode = str(provider.get("params") or "feed")
        if param_mode == "api6":
            return {"query": query, "cursor": 0, "sort_type": 1}
        if param_mode == "mobile":
            if str(provider.get("host") or "") == "scraptik.p.rapidapi.com":
                return {
                    "keyword": query,
                    "count": page_size,
                    "offset": 0,
                    "use_filters": 0,
                    "publish_time": 0,
                    "sort_type": 0,
                    "region": "US",
                    "compact": 0,
                }
            return {"keyword": query, "count": page_size, "offset": 0, "region": "US"}
        if param_mode == "api15":
            return {"keywords": query, "count": page_size, "cursor": 0}
        return {
            "keywords": query,
            "count": page_size,
            "cursor": 0,
            "region": "US",
            "publish_time": 0,
            "sort_type": 0,
        }

    def _search_provider_once(
        self,
        provider_id: str,
        search_plan: Mapping[str, Any],
        threshold: int,
        limit: int,
        diagnostics: Dict[str, Any],
        seen_video_ids: set,
        videos: List[Dict],
    ) -> None:
        provider = self.SEARCH_PROVIDERS.get(provider_id)
        if not isinstance(provider, Mapping):
            raise RapidAPISearchError(f"未知搜索来源：{provider_id}")
        label = str(provider.get("label") or provider_id)
        host = str(provider.get("host") or "")
        url = str(provider.get("url") or "")
        item_mode = str(provider.get("items") or "data_videos")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ViralX-Keyword-Search/2.0",
            "x-rapidapi-host": host,
            "x-rapidapi-key": self.api_key,
        }
        params = self._provider_params(
            provider,
            str(search_plan.get("query") or ""),
            limit,
        )
        diagnostics["requests"] += 1
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=self.SEARCH_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            detail = safe_error_message(exc, (self.api_key,))
            raise RapidAPISearchError(f"{label} 搜索请求失败：{detail}") from exc

        if response.status_code != 200:
            reason = {
                401: "拒绝了当前 RapidAPI Key",
                403: "尚未订阅或无权访问",
                429: "搜索配额已用完",
            }.get(response.status_code, "暂时不可用")
            raise RapidAPISearchError(
                f"{label} {reason}（HTTP {response.status_code}）",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RapidAPISearchError(f"{label} 返回了无法解析的响应") from exc

        business_error = self._provider_business_error(payload)
        if business_error:
            detail = safe_error_message(business_error, (self.api_key,))
            raise RapidAPISearchError(f"{label} 搜索失败：{detail}")

        diagnostics["responses"] += 1
        shape = self._provider_response_shape(payload, item_mode)
        if shape not in diagnostics["response_shapes"]:
            diagnostics["response_shapes"].append(shape)
        if self._provider_has_video_list(payload, item_mode):
            diagnostics["recognized_lists"] += 1
        before = len(videos)
        self._select_provider_items(
            self._provider_items(payload, item_mode),
            provider_id,
            search_plan,
            threshold,
            limit,
            diagnostics,
            seen_video_ids,
            videos,
        )
        diagnostics["selected_items"] = len(videos) - before
        print(
            f"[{provider_id.upper()}] 候选 {diagnostics['raw_items']}，"
            f"可识别 {diagnostics['normalized_items']}，新增 {diagnostics['selected_items']}，"
            f"语义错配 {diagnostics['rejected_irrelevant']}，无效帖子 ID {diagnostics['invalid_post_ids']}"
        )

    def _search_api23(
        self,
        search_plan: Mapping[str, Any],
        threshold: int,
        limit: int,
        diagnostics: Dict[str, Any],
    ) -> List[Dict]:
        headers = {
            "Content-Type": "application/json",
            "x-rapidapi-host": self.API23_SEARCH_HOST,
            "x-rapidapi-key": self.api_key,
        }
        error_messages = {
            401: "TikTok API23 拒绝了当前 RAPIDAPI_KEY",
            403: "当前 RapidAPI 账户尚未订阅或无权访问 TikTok API23",
            429: "TikTok API23 搜索配额已用完",
        }
        cursor: Any = 0
        search_id: Any = 0
        seen_cursors = set()
        seen_video_ids = set()
        videos: List[Dict] = []

        for _ in range(3):
            cursor_key = str(cursor)
            if cursor_key in seen_cursors:
                break
            seen_cursors.add(cursor_key)
            params = {
                "keyword": str(search_plan.get("query") or ""),
                "cursor": cursor,
                "search_id": search_id,
            }
            diagnostics["requests"] += 1
            try:
                response = requests.get(
                    self.API23_SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=self.SEARCH_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                detail = safe_error_message(exc, (self.api_key,))
                raise API23SearchError(f"TikTok API23 搜索请求失败：{detail}") from exc

            if response.status_code != 200:
                message = error_messages.get(response.status_code, "TikTok API23 搜索暂时不可用")
                raise API23SearchError(f"{message}（HTTP {response.status_code}）")
            try:
                payload = response.json()
            except ValueError as exc:
                raise API23SearchError("TikTok API23 返回了无法解析的响应") from exc

            business_error = self._api23_business_error(payload)
            if business_error:
                detail = safe_error_message(business_error, (self.api_key,))
                raise API23SearchError(f"TikTok API23 搜索失败：{detail}")

            mapped_payload = self._mapping(payload)
            diagnostics["responses"] += 1
            shape = self._api23_response_shape(mapped_payload)
            if shape not in diagnostics["response_shapes"]:
                diagnostics["response_shapes"].append(shape)
            if self._api23_has_video_list(mapped_payload):
                diagnostics["recognized_lists"] += 1
            items = self._api23_items(mapped_payload)
            self._select_provider_items(
                items,
                self.PRIMARY_SEARCH_PROVIDER,
                search_plan,
                threshold,
                limit,
                diagnostics,
                seen_video_ids,
                videos,
            )
            if len(videos) >= limit:
                break

            root = self._mapping(mapped_payload)
            nested = self._mapping(root.get("data"))

            def page_value(*keys: str, default: Any = None) -> Any:
                for container in (nested, root):
                    for key in keys:
                        if key in container and container.get(key) not in (None, ""):
                            return container.get(key)
                return default

            has_more = page_value("has_more", "hasMore", default=False)
            next_cursor = page_value("cursor", "next_cursor", "nextCursor", default=cursor)
            extra = self._mapping(root.get("extra"))
            next_search_id = (
                nested.get("search_id")
                or nested.get("searchId")
                or nested.get("search_request_id")
                or root.get("search_id")
                or root.get("searchId")
                or extra.get("search_request_id")
                or search_id
            )
            if has_more not in (True, 1, "1") or not items or str(next_cursor) == cursor_key:
                break
            cursor = next_cursor
            search_id = next_search_id

        print(
            "[API23] "
            f"候选 {diagnostics['raw_items']}，可识别 {diagnostics['normalized_items']}，"
            f"语义错配 {diagnostics['rejected_irrelevant']}，无效帖子 ID {diagnostics['invalid_post_ids']}，"
            f"符合阈值 {len(videos)}"
        )
        return videos[:limit]

    def _search_scraper7(
        self,
        search_plan: Mapping[str, Any],
        threshold: int,
        limit: int,
        diagnostics: Dict[str, Any],
    ) -> List[Dict]:
        page_size = min(max(limit, 10), 30)
        headers = {
            "Content-Type": "application/json",
            "x-rapidapi-host": self.SEARCH_HOST,
            "x-rapidapi-key": self.api_key,
        }
        error_messages = {
            401: "TikTok Scraper7 拒绝了当前 RAPIDAPI_KEY",
            403: "当前 RapidAPI 账户尚未订阅或无权访问 TikTok Scraper7",
            429: "TikTok Scraper7 搜索配额已用完，请稍后再试或检查订阅方案",
        }
        cursor: Any = 0
        seen_cursors = set()
        seen_video_ids = set()
        videos: List[Dict] = []

        for _ in range(5):
            cursor_key = str(cursor)
            if cursor_key in seen_cursors:
                break
            seen_cursors.add(cursor_key)
            params = {
                "keywords": str(search_plan.get("query") or ""),
                "region": "US",
                "count": page_size,
                "cursor": cursor,
                "publish_time": 0,
                "sort_type": 0,
            }
            diagnostics["requests"] += 1
            try:
                response = requests.get(
                    self.SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=self.SEARCH_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                detail = safe_error_message(exc, (self.api_key,))
                raise Scraper7SearchError(f"TikTok Scraper7 搜索请求失败：{detail}") from exc

            if response.status_code != 200:
                message = error_messages.get(response.status_code, "TikTok Scraper7 搜索暂时不可用")
                raise Scraper7SearchError(f"{message}（HTTP {response.status_code}）")
            try:
                payload = response.json()
            except ValueError as exc:
                raise Scraper7SearchError("TikTok Scraper7 返回了无法解析的响应") from exc

            business_error = self._scraper7_business_error(payload)
            if business_error:
                detail = safe_error_message(business_error, (self.api_key,))
                raise Scraper7SearchError(f"TikTok Scraper7 搜索失败：{detail}")

            mapped_payload = self._mapping(payload)
            diagnostics["responses"] += 1
            shape = self._scraper7_response_shape(mapped_payload)
            if shape not in diagnostics["response_shapes"]:
                diagnostics["response_shapes"].append(shape)
            if self._scraper7_has_video_list(mapped_payload):
                diagnostics["recognized_lists"] += 1
            items = self._scraper7_items(mapped_payload)
            self._select_provider_items(
                items,
                self.FALLBACK_SEARCH_PROVIDER,
                search_plan,
                threshold,
                limit,
                diagnostics,
                seen_video_ids,
                videos,
            )
            if len(videos) >= limit:
                break

            root = self._mapping(mapped_payload)
            nested = self._mapping(root.get("data"))
            container = nested or root
            has_more = container.get("has_more", container.get("hasMore", False))
            next_cursor = container.get("cursor", container.get("next_cursor", container.get("nextCursor", cursor)))
            if has_more not in (True, 1, "1") or not items or str(next_cursor) == cursor_key:
                break
            cursor = next_cursor

        print(
            "[SCRAPER7] "
            f"候选 {diagnostics['raw_items']}，可识别 {diagnostics['normalized_items']}，"
            f"语义错配 {diagnostics['rejected_irrelevant']}，无效帖子 ID {diagnostics['invalid_post_ids']}，"
            f"符合阈值 {len(videos)}"
        )
        return videos[:limit]

    @staticmethod
    def _fallback_reason(diagnostics: Mapping[str, Any], error: str = "") -> str:
        if error:
            return "provider_error"
        if int(diagnostics.get("raw_items") or 0) == 0:
            return "no_candidates"
        if int(diagnostics.get("normalized_items") or 0) == 0:
            return "no_valid_candidates"
        if int(diagnostics.get("filtered_by_likes") or 0) > 0:
            return "below_like_threshold"
        return "no_usable_candidates"

    def search_viral_videos(self, keyword: str, min_likes: int = 10000, count: int = 50) -> List[Dict]:
        """Merge providers until the target is met; failures and empty lists stay invisible to users."""
        clean_keyword = str(keyword or "").strip()
        search_plan = self._search_plan(clean_keyword)
        threshold = max(0, self._integer(min_likes))
        limit = max(1, min(self._integer(count, 30), 50))
        if not clean_keyword:
            self.last_search_diagnostics = {}
            return []
        if not str(self.api_key or "").strip():
            raise RuntimeError("TikTok 关键词发现尚未配置 RAPIDAPI_KEY；一把 Key 用于已订阅的多源搜索链")

        provider_ids = [
            provider_id
            for provider_id in self.search_provider_chain
            if provider_id in self.SEARCH_PROVIDERS
        ]
        providers = {
            provider_id: self._new_provider_diagnostics(
                provider_id, clean_keyword, search_plan, threshold,
            )
            for provider_id in provider_ids
        }
        attempted: List[str] = []
        videos: List[Dict] = []
        seen_video_ids: set = set()

        for provider_id in provider_ids:
            if len(videos) >= limit:
                break
            attempted.append(provider_id)
            diagnostics = providers[provider_id]
            try:
                self._search_provider_once(
                    provider_id,
                    search_plan,
                    threshold,
                    limit,
                    diagnostics,
                    seen_video_ids,
                    videos,
                )
            except RapidAPISearchError as exc:
                diagnostics["error"] = safe_error_message(exc, (self.api_key,))
                diagnostics["status_code"] = getattr(exc, "status_code", None)
                print(f"[SEARCH] {provider_id} 未完成，继续下一来源：{diagnostics['error']}")
                continue

            if len(videos) < limit:
                reason = self._fallback_reason(diagnostics)
                print(f"[SEARCH] {provider_id} 当前累计 {len(videos)}/{limit}（{reason}），继续补足")

        videos.sort(
            key=lambda video: (
                self._integer(video.get("search_relevance")) * 1_000_000_000,
                self._integer(video.get("digg_count")),
                self._integer(video.get("comment_count")) * 5,
                self._integer(video.get("share_count")) * 2,
                self._integer(video.get("play_count")),
            ),
            reverse=True,
        )
        videos = videos[:limit]
        result_providers = [str(video.get("search_provider") or "") for video in videos]
        unique_result_providers = list(dict.fromkeys(filter(None, result_providers)))
        selected_provider = (
            unique_result_providers[0]
            if len(unique_result_providers) == 1
            else "multi" if unique_result_providers else ""
        )
        self._set_chain_diagnostics(
            providers,
            selected_provider=selected_provider,
            fallback_used=len(attempted) > 1,
            fallback_reason="target_not_met" if len(attempted) > 1 else "",
            attempted_providers=attempted,
            result_providers=result_providers,
            selected_items=len(videos),
        )
        if videos:
            return videos

        if attempted and all(providers[provider_id].get("error") for provider_id in attempted):
            provider_errors = [
                {
                    "provider": provider_id,
                    "label": str(self.SEARCH_PROVIDERS[provider_id].get("label") or provider_id),
                    "message": str(providers[provider_id]["error"]),
                    "status_code": providers[provider_id].get("status_code"),
                }
                for provider_id in attempted
            ]
            summary = "；".join(
                f"{provider_id}: {providers[provider_id]['error']}"
                for provider_id in attempted
            )
            forbidden_provider_ids = [
                item["provider"] for item in provider_errors if item.get("status_code") == 403
            ]
            all_forbidden = len(forbidden_provider_ids) == len(provider_errors)
            if all_forbidden:
                message = (
                    "TikTok 多源搜索链均未完成：当前 RapidAPI Key 尚未订阅任何已接入的搜索源。"
                    "请从下方入口订阅至少一个来源后重试；无需更换 Key。"
                )
            else:
                message = f"TikTok 多源搜索链均未完成：{summary}"
            raise TikTokSearchChainError(
                message,
                error_code="rapidapi_subscription_required" if all_forbidden else "search_chain_failed",
                provider_errors=provider_errors,
                subscription_links=self.provider_subscription_links(forbidden_provider_ids),
            )
        return []

    def empty_result_message(self) -> str:
        """Explain an empty multi-provider result without exposing credentials or payloads."""
        diagnostics = self.last_search_diagnostics or {}
        provider_map = diagnostics.get("providers") if isinstance(diagnostics.get("providers"), Mapping) else {}
        provider_diagnostics = [value for value in provider_map.values() if isinstance(value, Mapping)] or [diagnostics]
        raw_items = sum(self._integer(item.get("raw_items")) for item in provider_diagnostics)
        normalized_items = sum(self._integer(item.get("normalized_items")) for item in provider_diagnostics)
        threshold = self._integer(diagnostics.get("threshold"))
        max_likes = max((self._integer(item.get("max_likes")) for item in provider_diagnostics), default=0)
        responses = sum(self._integer(item.get("responses")) for item in provider_diagnostics)
        recognized_lists = sum(self._integer(item.get("recognized_lists")) for item in provider_diagnostics)
        rejected_irrelevant = sum(self._integer(item.get("rejected_irrelevant")) for item in provider_diagnostics)
        invalid_post_ids = sum(self._integer(item.get("invalid_post_ids")) for item in provider_diagnostics)
        intent_label = str(diagnostics.get("search_intent_label") or "")

        if raw_items == 0:
            if responses and recognized_lists == 0:
                return "多源搜索链已响应，但没有可识别的视频列表；上游接口结构可能已经更新。"
            if responses:
                return (
                    "已自动尝试所有可用搜索源，但它们都没有返回视频候选。"
                    "没有候选可供点赞筛选，这与最低点赞数无关；请稍后重试或换一个更具体的关键词。"
                )
            return "多源搜索链没有完成任何请求；请检查网络、RapidAPI 订阅和统一搜索 Key。"
        if normalized_items == 0:
            if rejected_irrelevant:
                return (
                    f"多源搜索共返回 {raw_items} 条候选，但其中 {rejected_irrelevant} 条与“{intent_label}”"
                    "不是同一产品品类，已在进入 TK Note 前剔除。请换一个更具体的产品描述后重试。"
                )
            if invalid_post_ids:
                return (
                    f"多源搜索共返回 {raw_items} 条候选，但没有可识别的数字帖子 ID。"
                    "接口返回的 v… 标识是媒体资源 ID，不能拼成 TikTok 页面链接；ViralX 已停止生成假链接。"
                )
            return "多源搜索链已完成自动切换，但没有产生可用视频。"
        if threshold > 0 and max_likes < threshold:
            return (
                f"多源搜索共返回 {normalized_items} 条视频，但最高点赞为 {max_likes:,}，"
                f"全部低于当前阈值 {threshold:,}；请降低最低点赞数后重试。"
            )
        return f"多源搜索链共返回 {normalized_items} 条候选，但没有可用于分析的视频。"

    def get_video_comments(self, video_id: str, max_count: int = 20) -> List[Dict]:
        """使用本地 TikTok API 抓取评论。"""
        try:
            url = "http://localhost:8080/api/tiktok/web/fetch_post_comment"
            params = {"aweme_id": video_id, "cursor": 0, "count": max_count, "current_region": ""}
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                comments = data.get("data", {}).get("comments", [])
                return [
                    {"text": comment.get("text", ""), "likes": comment.get("digg_count", 0)}
                    for comment in comments[:15]
                ]
        except Exception as exc:
            print(f"[评论抓取失败] {exc}")
        return []

    def extract_video_info(self, video: Dict) -> Dict:
        """提取视频关键信息。"""
        stats = self._mapping(video.get("stats"))
        video_asset = self._mapping(video.get("video"))
        author_value = video.get("author")
        author = self._mapping(author_value)
        duration_ms = (
            video.get("duration", 0)
            or video_asset.get("duration", 0)
            or video.get("play_duration", 0)
            or video.get("video_duration", 0)
        )
        duration_s = int(duration_ms / 1000) if duration_ms > 1000 else int(duration_ms)
        return {
            "video_id": str(video.get("video_id") or video.get("id") or video_asset.get("id") or ""),
            "title": video.get("title") or video.get("desc") or "",
            "author": (
                author.get("unique_id")
                or author.get("uniqueId")
                or (author_value if isinstance(author_value, str) else "")
            ),
            "likes": self._integer(video.get("digg_count", stats.get("digg_count", stats.get("diggCount")))),
            "comments": self._integer(
                video.get("comment_count", stats.get("comment_count", stats.get("commentCount")))
            ),
            "shares": self._integer(
                video.get("share_count", stats.get("share_count", stats.get("shareCount")))
            ),
            "views": self._integer(video.get("play_count", stats.get("play_count", stats.get("playCount")))),
            "cover": video.get("cover") or video_asset.get("cover") or "",
            "duration": duration_s,
            "hashtags": list(video.get("hashtags") or []),
            "search_provider": video.get("search_provider", self.SEARCH_PROVIDER),
            "source_url": str(video.get("source_url") or ""),
            "search_relevance": self._integer(video.get("search_relevance")),
            "search_intent": str(video.get("search_intent") or "generic"),
        }

    def analyze_selling_points(self, videos: List[Dict]) -> Dict:
        """基础卖点统计。"""
        all_tags = []
        for video in videos:
            all_tags.extend(video.get("hashtags", []))
        from collections import Counter

        tag_freq = Counter(all_tags)
        return {
            "top_hashtags": tag_freq.most_common(10),
            "avg_likes": sum(video.get("likes", 0) for video in videos) / len(videos) if videos else 0,
            "total_videos": len(videos),
        }

    def run_analysis(self, keyword: str, min_likes: int = 10000):
        """执行搜索与基础统计。"""
        print(f"[1/3] 搜索关键词: {keyword}")
        videos = self.search_viral_videos(keyword, min_likes)
        print(f"[2/3] 提取 {len(videos)} 个爆款视频信息")
        video_data = [self.extract_video_info(video) for video in videos]
        print("[3/3] 分析卖点")
        analysis = self.analyze_selling_points(video_data)
        output = {"keyword": keyword, "analysis": analysis, "videos": video_data}
        output_file = self.output_dir / f"{keyword.replace(' ', '_')}_viral.json"
        output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[完成] 结果保存至: {output_file}")
        return output


if __name__ == "__main__":
    analyzer = TikTokViralAnalyzer()
    print("请先配置一把 RapidAPI Key（ViralX 会在已订阅的关键词搜索源之间自动切换）")
    # analyzer.api_key = "YOUR_API_KEY"
    # analyzer.run_analysis("picture light", min_likes=100)
