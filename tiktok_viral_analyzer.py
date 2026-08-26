#!/usr/bin/env python3
"""
TikTok 美区爆款视频分析工具
使用 TikTok Research API 或第三方 API 抓取爆款视频
"""
import requests
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


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


class API23SearchError(RuntimeError):
    """An API23 failure that may or may not be safe to retry on another route."""

    def __init__(self, message: str, *, recoverable: bool = False):
        super().__init__(message)
        self.recoverable = recoverable

class TikTokViralAnalyzer:
    SEARCH_PROVIDER = "api23"
    SEARCH_HOST = "tiktok-api23.p.rapidapi.com"
    SEARCH_URL = f"https://{SEARCH_HOST}/api/search/video"
    GENERAL_SEARCH_URL = f"https://{SEARCH_HOST}/api/search/general"
    DISCOVER_URL = f"https://{SEARCH_HOST}/api/post/discover"
    SEARCH_TIMEOUT_SECONDS = 15
    ROUTE_LABELS = {
        "/api/search/video": "Search Video",
        "/api/search/general": "Search General",
        "/api/post/discover": "Discover",
    }
    API23_VIDEO_LIST_KEYS = ("item_list", "itemList", "items", "videoList", "videos")

    def __init__(self, output_dir="E:/tiktok_analyzer/data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = ""  # RapidAPI API23 key；仅用于关键词发现
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
    def _api23_items(cls, payload: Any) -> List[Dict]:
        """Read API23 search results across documented and legacy wrappers."""
        root = cls._mapping(payload)
        candidates = [root, cls._mapping(root.get("data"))]
        for container in candidates:
            for key in cls.API23_VIDEO_LIST_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]

        # Search General returns a mixed top-results list on some API23
        # revisions. Keep only entries that contain a TikTok video item.
        data = root.get("data")
        if isinstance(data, list):
            videos = []
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                item = cls._mapping(entry.get("item"))
                candidate = item or entry
                if candidate.get("id") and any(
                    key in candidate for key in ("video", "stats", "desc", "create_time", "createTime")
                ):
                    videos.append(entry)
            return videos
        return []

    @classmethod
    def _api23_has_item_list(cls, payload: Any) -> bool:
        root = cls._mapping(payload)
        candidates = [root, cls._mapping(root.get("data"))]
        if any(
            isinstance(container.get(key), list)
            for container in candidates
            for key in cls.API23_VIDEO_LIST_KEYS
        ):
            return True
        return isinstance(root.get("data"), list)

    @classmethod
    def _api23_response_shape(cls, payload: Any) -> Dict[str, Any]:
        """Summarize response structure without retaining videos, text, URLs, or credentials."""
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
            "lists": lists,
        }

    @classmethod
    def _api23_business_error(cls, payload: Any) -> tuple[str, bool]:
        """Return a safe HTTP-200 business error and whether fallback is useful."""
        root = cls._mapping(payload)
        containers = [root, cls._mapping(root.get("data"))]
        for container in containers:
            code = container.get("status_code")
            if code in (None, ""):
                code = container.get("statusCode")
            failed = code not in (None, 0, "0", 200, "200") or container.get("success") is False
            error = container.get("error")
            if not failed and not error:
                continue
            message = (
                container.get("status_msg")
                or container.get("statusMsg")
                or container.get("message")
                or (error.get("message") if isinstance(error, Mapping) else error)
                or "API23 返回了业务错误"
            )
            safe_message = safe_error_message(message)[:240]
            recoverable = code in (4, "4") or any(
                marker in safe_message.lower()
                for marker in ("temporarily unavailable", "currently unavailable", "try again later")
            )
            detail = f"{safe_message}（业务状态 {code}）" if code not in (None, "") else safe_message
            return detail, recoverable
        return "", False

    @classmethod
    def _normalize_api23_video(cls, item: Dict) -> Dict:
        """Normalize API23's nested SearchVideo item to ViralX's stable schema."""
        wrapped_item = item.get("item")
        if isinstance(wrapped_item, dict):
            item = wrapped_item

        author = cls._mapping(item.get("author"))
        stats = cls._mapping(item.get("stats"))
        video = cls._mapping(item.get("video"))
        challenges = item.get("challenges") if isinstance(item.get("challenges"), list) else []

        video_id = item.get("id") or item.get("video_id") or video.get("id")
        author_id = author.get("unique_id") or author.get("uniqueId") or ""
        hashtags = [
            str(cls._mapping(challenge).get("title") or "").strip()
            for challenge in challenges
            if str(cls._mapping(challenge).get("title") or "").strip()
        ]

        return {
            "video_id": str(video_id or ""),
            "title": str(item.get("desc") or item.get("title") or ""),
            "author": {"unique_id": str(author_id)},
            "digg_count": cls._integer(stats.get("digg_count", stats.get("diggCount"))),
            "comment_count": cls._integer(stats.get("comment_count", stats.get("commentCount"))),
            "share_count": cls._integer(stats.get("share_count", stats.get("shareCount"))),
            "play_count": cls._integer(stats.get("play_count", stats.get("playCount"))),
            "collect_count": cls._integer(stats.get("collect_count", stats.get("collectCount"))),
            "cover": str(video.get("cover") or item.get("cover") or ""),
            "duration": cls._integer(video.get("duration", item.get("duration"))),
            "hashtags": hashtags,
            "create_time": cls._integer(item.get("create_time", item.get("createTime"))),
            "is_ad": bool(item.get("is_ad", item.get("isAd", False))),
            "search_provider": cls.SEARCH_PROVIDER,
        }

    def search_viral_videos(self, keyword: str, min_likes: int = 10000, count: int = 50) -> List[Dict]:
        """Search API23 through its three official keyword-discovery routes."""
        clean_keyword = str(keyword or "").strip()
        threshold = max(0, self._integer(min_likes))
        self.last_search_diagnostics = {
            "keyword": clean_keyword,
            "threshold": threshold,
            "raw_items": 0,
            "normalized_items": 0,
            "filtered_by_likes": 0,
            "max_likes": 0,
            "routes": [],
            "responses": 0,
            "recognized_lists": 0,
            "route_errors": {},
            "route_diagnostics": {},
        }
        if not clean_keyword:
            return []
        if not str(self.api_key or "").strip():
            raise RuntimeError("API23 关键词搜索尚未配置 RAPIDAPI_KEY")

        limit = max(1, min(self._integer(count, 30), 50))
        error_messages = {
            401: "API23 拒绝了当前 RAPIDAPI_KEY",
            403: "当前 RapidAPI 账户尚未订阅或无权访问 API23",
            429: "API23 搜索配额已用完，请稍后再试或检查订阅方案",
        }
        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.SEARCH_HOST,
        }
        seen_video_ids = set()
        viral_videos: List[Dict] = []

        def route_diagnostics(route: str) -> Dict[str, Any]:
            return self.last_search_diagnostics["route_diagnostics"].setdefault(
                route,
                {
                    "requests": 0,
                    "responses": 0,
                    "recognized_lists": 0,
                    "raw_items": 0,
                    "normalized_items": 0,
                    "matched_items": 0,
                    "max_likes": 0,
                    "error": "",
                    "response_shapes": [],
                },
            )

        def request_page(url: str, params: Dict[str, Any], route: str) -> Mapping[str, Any]:
            route_stats = route_diagnostics(route)
            route_stats["requests"] += 1
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.SEARCH_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                detail = safe_error_message(exc, (self.api_key,))
                raise API23SearchError(
                    f"API23 关键词搜索请求失败：{detail}",
                    recoverable=True,
                ) from exc

            if response.status_code != 200:
                message = error_messages.get(response.status_code, "API23 关键词搜索暂时不可用")
                raise API23SearchError(
                    f"{message}（HTTP {response.status_code}）",
                    recoverable=response.status_code >= 500,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise API23SearchError(
                    "API23 返回了无法解析的响应",
                    recoverable=True,
                ) from exc
            business_error, recoverable = self._api23_business_error(payload)
            if business_error:
                detail = safe_error_message(business_error, (self.api_key,))
                raise API23SearchError(
                    f"API23 搜索失败：{detail}",
                    recoverable=recoverable,
                )
            mapped_payload = self._mapping(payload)
            self.last_search_diagnostics["responses"] += 1
            route_stats["responses"] += 1
            shape = self._api23_response_shape(mapped_payload)
            if shape not in route_stats["response_shapes"]:
                route_stats["response_shapes"].append(shape)
            if self._api23_has_item_list(mapped_payload):
                self.last_search_diagnostics["recognized_lists"] += 1
                route_stats["recognized_lists"] += 1
            return mapped_payload

        def collect_items(items: List[Dict], route: str) -> None:
            diagnostics = self.last_search_diagnostics
            route_stats = route_diagnostics(route)
            diagnostics["raw_items"] += len(items)
            route_stats["raw_items"] += len(items)
            if route not in diagnostics["routes"]:
                diagnostics["routes"].append(route)
            for item in items:
                video = self._normalize_api23_video(item)
                video_id = video["video_id"]
                if not video_id:
                    continue
                diagnostics["normalized_items"] += 1
                route_stats["normalized_items"] += 1
                diagnostics["max_likes"] = max(diagnostics["max_likes"], video["digg_count"])
                route_stats["max_likes"] = max(route_stats["max_likes"], video["digg_count"])
                if video["digg_count"] < threshold:
                    diagnostics["filtered_by_likes"] += 1
                    continue
                if video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video_id)
                viral_videos.append(video)
                route_stats["matched_items"] += 1

        def record_route_error(route: str, exc: API23SearchError) -> None:
            detail = str(exc)
            self.last_search_diagnostics["route_errors"][route] = detail
            route_diagnostics(route)["error"] = detail

        def search_cursor_route(url: str, route: str) -> None:
            cursor: Any = 0
            search_id = "0"
            seen_pages = set()

            # API23 uses cursor + log_pb.impr_id for subsequent pages. Five
            # pages keeps a search bounded while still honoring count=30.
            for _ in range(5):
                page_signature = (str(cursor), str(search_id))
                if page_signature in seen_pages:
                    break
                seen_pages.add(page_signature)

                # API23 documents cursor and search_id as optional defaults on
                # the first page, and requires both only for pagination. Mirror
                # that contract exactly instead of sending pagination state early.
                params: Dict[str, Any] = {"keyword": clean_keyword}
                if cursor not in (0, "0") or search_id != "0":
                    params.update({"cursor": cursor, "search_id": search_id})
                payload = request_page(url, params, route)
                items = self._api23_items(payload)
                collect_items(items, route)
                if len(viral_videos) >= limit:
                    break

                root = self._mapping(payload)
                nested = self._mapping(root.get("data"))
                container = nested if any(
                    isinstance(nested.get(key), list)
                    for key in self.API23_VIDEO_LIST_KEYS
                ) else root
                has_more = container.get(
                    "has_more",
                    container.get("hasMore", root.get("has_more", root.get("hasMore", False))),
                )
                if has_more not in (True, 1, "1") or not items:
                    break

                cursor = container.get(
                    "cursor",
                    container.get("next_cursor", container.get("nextCursor", root.get("cursor", cursor))),
                )
                log_pb = self._mapping(container.get("log_pb") or root.get("log_pb"))
                search_id = str(log_pb.get("impr_id") or log_pb.get("imprId") or search_id)

        cursor_routes = (
            (self.SEARCH_URL, "/api/search/video"),
            (self.GENERAL_SEARCH_URL, "/api/search/general"),
        )
        for url, route in cursor_routes:
            if viral_videos:
                break
            try:
                search_cursor_route(url, route)
            except API23SearchError as exc:
                if not exc.recoverable:
                    raise
                record_route_error(route, exc)

        # Discover is the final same-provider fallback. A recoverable failure
        # here must not erase valid empty/filtered responses from earlier routes.
        if not viral_videos:
            try:
                for page in range(1, 4):
                    payload = request_page(
                        self.DISCOVER_URL,
                        {"keyword": clean_keyword, "page": page},
                        "/api/post/discover",
                    )
                    items = self._api23_items(payload)
                    collect_items(items, "/api/post/discover")
                    if len(viral_videos) >= limit:
                        break
                    root = self._mapping(payload)
                    nested = self._mapping(root.get("data"))
                    container = nested if nested else root
                    has_more = container.get("hasMore", container.get("has_more", False))
                    if has_more not in (True, 1, "1") or not items:
                        break
            except API23SearchError as exc:
                if not exc.recoverable:
                    raise
                record_route_error("/api/post/discover", exc)

        diagnostics = self.last_search_diagnostics
        route_stats = diagnostics["route_diagnostics"]
        attempted_routes = [route for _, route in cursor_routes] + ["/api/post/discover"]
        all_routes_failed = all(route_stats.get(route, {}).get("error") for route in attempted_routes)
        if not viral_videos and all_routes_failed:
            failures = "；".join(
                f"{self.ROUTE_LABELS[route]}：{route_stats[route]['error']}" for route in attempted_routes
            )
            raise RuntimeError(f"API23 三个关键词入口均失败：{failures}")

        viral_videos = viral_videos[:limit]
        print(
            "[API23] "
            f"候选 {diagnostics['raw_items']}，可识别 {diagnostics['normalized_items']}，"
            f"符合阈值 {len(viral_videos)}"
        )
        return viral_videos

    def empty_result_message(self) -> str:
        """Explain an empty API23 result without exposing credentials or payloads."""
        diagnostics = self.last_search_diagnostics or {}
        raw_items = self._integer(diagnostics.get("raw_items"))
        normalized_items = self._integer(diagnostics.get("normalized_items"))
        threshold = self._integer(diagnostics.get("threshold"))
        max_likes = self._integer(diagnostics.get("max_likes"))
        routes = diagnostics.get("routes") or []
        route_errors = diagnostics.get("route_errors") or {}
        responses = self._integer(diagnostics.get("responses"))
        recognized_lists = self._integer(diagnostics.get("recognized_lists"))
        route_diagnostics = diagnostics.get("route_diagnostics") or {}
        route_label = "、".join(routes) or "API23 搜索接口"
        if raw_items == 0:
            if responses and recognized_lists == 0:
                return "API23 返回了响应，但没有可识别的视频列表；接口响应结构可能已经更新。"
            successful_routes = [
                self.ROUTE_LABELS.get(route, route)
                for route, stats in route_diagnostics.items()
                if self._integer(stats.get("responses")) > 0
            ]
            failed_routes = [
                self.ROUTE_LABELS.get(route, route)
                for route, stats in route_diagnostics.items()
                if stats.get("error")
            ]
            if successful_routes:
                empty_details = []
                for route, stats in route_diagnostics.items():
                    if self._integer(stats.get("responses")) <= 0:
                        continue
                    list_shapes = []
                    for shape in stats.get("response_shapes") or []:
                        list_shapes.extend(shape.get("lists") or [])
                    if list_shapes:
                        empty_details.append(
                            f"{self.ROUTE_LABELS.get(route, route)} 返回 {', '.join(dict.fromkeys(list_shapes))}"
                        )
                message = "API23 已正常响应，但服务端没有返回视频候选"
                if empty_details:
                    message += "：" + "；".join(empty_details)
                if failed_routes:
                    message += f"；{'、'.join(failed_routes)} 暂时不可用"
                return message + "。没有候选可供点赞筛选，这与最低点赞数无关；请稍后重试或在 Playground 核对同一关键词。"
            if route_errors:
                return "API23 的关键词搜索入口当前均不可用；这与最低点赞数无关，请稍后重试。"
            return f"API23 的 {route_label} 均未返回视频候选；请在 RapidAPI Playground 检查当前订阅和实际响应。"
        if normalized_items == 0:
            return f"API23 返回了 {raw_items} 条候选，但响应中没有可识别的视频 ID；接口结构可能已经更新。"
        if threshold > 0 and max_likes < threshold:
            return (
                f"API23 返回了 {normalized_items} 条视频，但最高点赞为 {max_likes:,}，"
                f"全部低于当前阈值 {threshold:,}；请降低最低点赞数后重试。"
            )
        return f"API23 返回了 {normalized_items} 条候选，但没有可用于分析的视频。"

    def get_video_comments(self, video_id: str, max_count: int = 20) -> List[Dict]:
        """使用本地 TikTok API 抓取评论"""
        try:
            url = "http://localhost:8080/api/tiktok/web/fetch_post_comment"
            params = {"aweme_id": video_id, "cursor": 0, "count": max_count, "current_region": ""}
            response = requests.get(url, params=params, timeout=15)

            if response.status_code == 200:
                data = response.json()
                comments = data.get('data', {}).get('comments', [])
                result = []
                for c in comments[:15]:
                    result.append({
                        'text': c.get('text', ''),
                        'likes': c.get('digg_count', 0)
                    })
                return result
        except Exception as e:
            print(f"[评论抓取失败] {e}")
        return []

    def extract_video_info(self, video: Dict) -> Dict:
        """提取视频关键信息"""
        stats = self._mapping(video.get('stats'))
        video_asset = self._mapping(video.get('video'))
        author_value = video.get('author')
        author = self._mapping(author_value)
        # 尝试提取时长（秒），来源可能是 duration 或 play_duration
        duration_ms = (
            video.get('duration', 0)
            or video_asset.get('duration', 0)
            or video.get('play_duration', 0)
            or video.get('video_duration', 0)
        )
        duration_s = int(duration_ms / 1000) if duration_ms > 1000 else int(duration_ms)
        return {
            'video_id': str(video.get('video_id') or video.get('id') or video_asset.get('id') or ''),
            'title': video.get('title') or video.get('desc') or '',
            'author': (
                author.get('unique_id')
                or author.get('uniqueId')
                or (author_value if isinstance(author_value, str) else '')
            ),
            'likes': self._integer(video.get('digg_count', stats.get('digg_count', stats.get('diggCount')))),
            'comments': self._integer(video.get('comment_count', stats.get('comment_count', stats.get('commentCount')))),
            'shares': self._integer(video.get('share_count', stats.get('share_count', stats.get('shareCount')))),
            'views': self._integer(video.get('play_count', stats.get('play_count', stats.get('playCount')))),
            'cover': video.get('cover') or video_asset.get('cover') or '',
            'duration': duration_s,  # 视频时长（秒）
            'hashtags': list(video.get('hashtags') or []),
            'search_provider': video.get('search_provider', self.SEARCH_PROVIDER),
        }

    def analyze_selling_points(self, videos: List[Dict]) -> Dict:
        """分析卖点（基础版：统计高频词和标签）"""
        all_text = ' '.join([v.get('title', '') for v in videos])
        all_tags = []
        for v in videos:
            all_tags.extend(v.get('hashtags', []))

        from collections import Counter
        tag_freq = Counter(all_tags)

        return {
            'top_hashtags': tag_freq.most_common(10),
            'avg_likes': sum(v.get('likes', 0) for v in videos) / len(videos) if videos else 0,
            'total_videos': len(videos)
        }

    def run_analysis(self, keyword: str, min_likes: int = 10000):
        """执行完整分析流程"""
        print(f"[1/3] 搜索关键词: {keyword}")
        videos = self.search_viral_videos(keyword, min_likes)

        print(f"[2/3] 提取 {len(videos)} 个爆款视频信息")
        video_data = [self.extract_video_info(v) for v in videos]

        print(f"[3/3] 分析卖点")
        analysis = self.analyze_selling_points(video_data)

        # 保存结果
        output = {
            'keyword': keyword,
            'analysis': analysis,
            'videos': video_data
        }
        output_file = self.output_dir / f"{keyword.replace(' ', '_')}_viral.json"
        output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))

        print(f"\n[完成] 结果保存至: {output_file}")
        return output

if __name__ == "__main__":
    analyzer = TikTokViralAnalyzer()
    print("请先配置 API Key（RapidAPI TikTok API23）")
    print("获取地址: https://rapidapi.com/Lundehund/api/tiktok-api23")

    # analyzer.api_key = "YOUR_API_KEY"
    # analyzer.run_analysis("outdoor lighting lamp", min_likes=10000)
