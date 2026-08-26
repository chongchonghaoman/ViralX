#!/usr/bin/env python3
"""TikTok viral-video discovery and stable metadata normalization for ViralX."""

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping
from urllib.parse import quote

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


class Scraper7SearchError(RuntimeError):
    """A TikTok Scraper7 request or business-response failure."""


class TikTokViralAnalyzer:
    """Discover TikTok videos through RapidAPI TikTok Scraper7."""

    SEARCH_PROVIDER = "scraper7"
    SEARCH_HOST = "tiktok-scraper7.p.rapidapi.com"
    SEARCH_URL = f"https://{SEARCH_HOST}/feed/search"
    SEARCH_TIMEOUT_SECONDS = 20
    VIDEO_LIST_KEYS = ("videos", "items", "video_list", "videoList")
    POST_ID_PATTERN = re.compile(r"^\d{15,25}$")
    POST_URL_PATTERN = re.compile(r"/video/(\d{15,25})(?:[/?#]|$)", re.IGNORECASE)
    SOURCE_URL_KEYS = ("share_url", "shareUrl", "web_url", "webUrl", "source_url", "sourceUrl", "url")
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

        # Some Scraper7 responses expose a canonical page URL. It is the most
        # reliable source because it binds the post ID to the original author.
        for container in (item, video):
            for key in cls.SOURCE_URL_KEYS:
                source_url = str(container.get(key) or "").strip()
                if "tiktok.com/" not in source_url.lower():
                    continue
                match = cls.POST_URL_PATTERN.search(source_url)
                if match:
                    return match.group(1), source_url

        # Scraper7 may put an opaque `v260...` media resource ID in aweme_id or
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
                author = cls._mapping(item.get("author"))
                unique_id = str(
                    author.get("unique_id")
                    or author.get("uniqueId")
                    or author.get("sec_uid")
                    or "tiktok"
                ).strip().lstrip("@")
                safe_author = quote(unique_id or "tiktok", safe="._-")
                return post_id, f"https://www.tiktok.com/@{safe_author}/video/{post_id}"

        return "", ""

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
    def _normalize_scraper7_video(cls, item: Dict) -> Dict:
        """Normalize Scraper7's VideoInfo object to ViralX's stable schema."""
        author = cls._mapping(item.get("author"))
        stats = cls._mapping(item.get("stats"))
        video = cls._mapping(item.get("video"))
        video_id, source_url = cls._post_identity(item)
        title = str(item.get("title") or item.get("desc") or "")

        challenges = item.get("challenges") if isinstance(item.get("challenges"), list) else []
        hashtags = [
            str(cls._mapping(challenge).get("title") or "").strip()
            for challenge in challenges
            if str(cls._mapping(challenge).get("title") or "").strip()
        ]
        if not hashtags:
            hashtags = list(dict.fromkeys(re.findall(r"(?<!\w)#([\w-]+)", title)))

        return {
            "video_id": str(video_id or ""),
            "source_url": source_url,
            "title": title,
            "author": {
                "unique_id": str(
                    author.get("unique_id")
                    or author.get("uniqueId")
                    or author.get("sec_uid")
                    or author.get("id")
                    or ""
                )
            },
            "digg_count": cls._integer(
                item.get("digg_count", stats.get("digg_count", stats.get("diggCount")))
            ),
            "comment_count": cls._integer(
                item.get("comment_count", stats.get("comment_count", stats.get("commentCount")))
            ),
            "share_count": cls._integer(
                item.get("share_count", stats.get("share_count", stats.get("shareCount")))
            ),
            "play_count": cls._integer(
                item.get("play_count", stats.get("play_count", stats.get("playCount")))
            ),
            "collect_count": cls._integer(
                item.get("collect_count", stats.get("collect_count", stats.get("collectCount")))
            ),
            "cover": str(item.get("cover") or item.get("origin_cover") or video.get("cover") or ""),
            "duration": cls._integer(item.get("duration", video.get("duration"))),
            "hashtags": hashtags,
            "create_time": cls._integer(item.get("create_time", item.get("createTime"))),
            "is_ad": bool(item.get("is_ad", item.get("isAd", False))),
            "search_provider": cls.SEARCH_PROVIDER,
        }

    def search_viral_videos(self, keyword: str, min_likes: int = 10000, count: int = 50) -> List[Dict]:
        """Search Scraper7 /feed/search, paginate, normalize and apply the likes filter."""
        clean_keyword = str(keyword or "").strip()
        search_plan = self._search_plan(clean_keyword)
        search_query = search_plan["query"]
        threshold = max(0, self._integer(min_likes))
        self.last_search_diagnostics = {
            "provider": self.SEARCH_PROVIDER,
            "keyword": clean_keyword,
            "search_query": search_query,
            "search_intent": search_plan["intent"],
            "search_intent_label": search_plan["label"],
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
        }
        if not clean_keyword:
            return []
        if not str(self.api_key or "").strip():
            raise RuntimeError("TikTok Scraper7 关键词搜索尚未配置 RAPIDAPI_KEY")

        limit = max(1, min(self._integer(count, 30), 50))
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

        seen_video_ids = set()
        viral_videos: List[Dict] = []
        cursor: Any = 0
        seen_cursors = set()

        for _ in range(5):
            cursor_key = str(cursor)
            if cursor_key in seen_cursors:
                break
            seen_cursors.add(cursor_key)
            params = {
                "keywords": search_query,
                "region": "US",
                "count": page_size,
                "cursor": cursor,
                "publish_time": 0,
                "sort_type": 0,
            }
            self.last_search_diagnostics["requests"] += 1
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
            diagnostics = self.last_search_diagnostics
            diagnostics["responses"] += 1
            shape = self._scraper7_response_shape(mapped_payload)
            if shape not in diagnostics["response_shapes"]:
                diagnostics["response_shapes"].append(shape)
            if self._scraper7_has_video_list(mapped_payload):
                diagnostics["recognized_lists"] += 1

            items = self._scraper7_items(mapped_payload)
            diagnostics["raw_items"] += len(items)
            for item in items:
                video = self._normalize_scraper7_video(item)
                video_id = video["video_id"]
                if not video_id:
                    diagnostics["invalid_post_ids"] += 1
                    continue
                diagnostics["valid_post_ids"] += 1
                relevance, rejection_reason = self._search_relevance(video, search_plan["intent"])
                if rejection_reason:
                    diagnostics["rejected_irrelevant"] += 1
                    continue
                video["search_relevance"] = relevance
                video["search_intent"] = search_plan["intent"]
                diagnostics["normalized_items"] += 1
                diagnostics["max_likes"] = max(diagnostics["max_likes"], video["digg_count"])
                if video["digg_count"] < threshold:
                    diagnostics["filtered_by_likes"] += 1
                    continue
                if video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video_id)
                viral_videos.append(video)
                if len(viral_videos) >= limit:
                    break

            if len(viral_videos) >= limit:
                break
            root = self._mapping(mapped_payload)
            nested = self._mapping(root.get("data"))
            container = nested or root
            has_more = container.get("has_more", container.get("hasMore", False))
            next_cursor = container.get(
                "cursor",
                container.get("next_cursor", container.get("nextCursor", cursor)),
            )
            if has_more not in (True, 1, "1") or not items or str(next_cursor) == cursor_key:
                break
            cursor = next_cursor

        diagnostics = self.last_search_diagnostics
        print(
            "[SCRAPER7] "
            f"候选 {diagnostics['raw_items']}，可识别 {diagnostics['normalized_items']}，"
            f"语义错配 {diagnostics['rejected_irrelevant']}，无效帖子 ID {diagnostics['invalid_post_ids']}，"
            f"符合阈值 {len(viral_videos)}"
        )
        return viral_videos[:limit]

    def empty_result_message(self) -> str:
        """Explain an empty Scraper7 result without exposing credentials or payloads."""
        diagnostics = self.last_search_diagnostics or {}
        raw_items = self._integer(diagnostics.get("raw_items"))
        normalized_items = self._integer(diagnostics.get("normalized_items"))
        threshold = self._integer(diagnostics.get("threshold"))
        max_likes = self._integer(diagnostics.get("max_likes"))
        responses = self._integer(diagnostics.get("responses"))
        recognized_lists = self._integer(diagnostics.get("recognized_lists"))
        rejected_irrelevant = self._integer(diagnostics.get("rejected_irrelevant"))
        intent_label = str(diagnostics.get("search_intent_label") or "")

        if raw_items == 0:
            if responses and recognized_lists == 0:
                return "TikTok Scraper7 已响应，但没有可识别的 data.videos 列表；接口响应结构可能已经更新。"
            if responses:
                return (
                    "TikTok Scraper7 已正常响应，但 data.videos 没有返回视频候选。"
                    "没有候选可供点赞筛选，这与最低点赞数无关；请在 RapidAPI Playground 核对同一关键词。"
                )
            return "TikTok Scraper7 没有完成搜索请求；请检查网络、订阅和 RapidAPI Key。"
        if normalized_items == 0:
            if rejected_irrelevant:
                return (
                    f"TikTok Scraper7 返回了 {raw_items} 条候选，但其中 {rejected_irrelevant} 条与“{intent_label}”"
                    "不是同一产品品类，已在进入 TK Note 前剔除。请换一个更具体的产品描述后重试。"
                )
            return (
                f"TikTok Scraper7 返回了 {raw_items} 条候选，但没有可识别的数字帖子 ID。"
                "接口返回的 v… 标识是媒体资源 ID，不能拼成 TikTok 页面链接；ViralX 已停止生成假链接。"
            )
        if threshold > 0 and max_likes < threshold:
            return (
                f"TikTok Scraper7 返回了 {normalized_items} 条视频，但最高点赞为 {max_likes:,}，"
                f"全部低于当前阈值 {threshold:,}；请降低最低点赞数后重试。"
            )
        return f"TikTok Scraper7 返回了 {normalized_items} 条候选，但没有可用于分析的视频。"

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
    print("请先配置 API Key（RapidAPI TikTok Scraper7）")
    print("获取地址: https://rapidapi.com/tikwm-tikwm-default/api/tiktok-scraper7")
    # analyzer.api_key = "YOUR_API_KEY"
    # analyzer.run_analysis("picture light", min_likes=100)
