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
    DISCOVER_URL = f"https://{SEARCH_HOST}/api/post/discover"
    SEARCH_TIMEOUT_SECONDS = 15

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
            for key in ("item_list", "itemList", "items", "videoList", "videos"):
                value = container.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _api23_has_item_list(cls, payload: Any) -> bool:
        root = cls._mapping(payload)
        candidates = [root, cls._mapping(root.get("data"))]
        return any(
            isinstance(container.get(key), list)
            for container in candidates
            for key in ("item_list", "itemList", "items", "videoList", "videos")
        )

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
        """Search API23, with its Discover endpoint as a same-provider fallback."""
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

        def request_page(url: str, params: Dict[str, Any]) -> Mapping[str, Any]:
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
            if self._api23_has_item_list(mapped_payload):
                self.last_search_diagnostics["recognized_lists"] += 1
            return mapped_payload

        def collect_items(items: List[Dict], route: str) -> None:
            diagnostics = self.last_search_diagnostics
            diagnostics["raw_items"] += len(items)
            if route not in diagnostics["routes"]:
                diagnostics["routes"].append(route)
            for item in items:
                video = self._normalize_api23_video(item)
                video_id = video["video_id"]
                if not video_id:
                    continue
                diagnostics["normalized_items"] += 1
                diagnostics["max_likes"] = max(diagnostics["max_likes"], video["digg_count"])
                if video["digg_count"] < threshold:
                    diagnostics["filtered_by_likes"] += 1
                    continue
                if video_id in seen_video_ids:
                    continue
                seen_video_ids.add(video_id)
                viral_videos.append(video)

        cursor: Any = 0
        search_id = "0"
        seen_pages = set()

        # API23 uses cursor + log_pb.impr_id for subsequent pages. Five pages
        # keeps a single ViralX search bounded while still honoring count=30.
        try:
            for _ in range(5):
                page_signature = (str(cursor), str(search_id))
                if page_signature in seen_pages:
                    break
                seen_pages.add(page_signature)

                payload = request_page(
                    self.SEARCH_URL,
                    {"keyword": clean_keyword, "cursor": cursor, "search_id": search_id},
                )
                items = self._api23_items(payload)
                collect_items(items, "/api/search/video")
                if len(viral_videos) >= limit:
                    break

                root = self._mapping(payload)
                nested = self._mapping(root.get("data"))
                container = nested if any(
                    isinstance(nested.get(key), list)
                    for key in ("item_list", "itemList", "items", "videoList", "videos")
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
        except API23SearchError as exc:
            if not exc.recoverable:
                raise
            self.last_search_diagnostics["route_errors"]["/api/search/video"] = str(exc)

        # API23 exposes a second official keyword-discovery route. It is useful
        # when TikTok's search route returns an empty first result set, and keeps
        # ViralX on the user's selected API23 provider.
        if not viral_videos:
            try:
                for page in range(1, 4):
                    payload = request_page(
                        self.DISCOVER_URL,
                        {"keyword": clean_keyword, "page": page},
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
                primary_error = self.last_search_diagnostics["route_errors"].get("/api/search/video")
                if primary_error:
                    raise RuntimeError(f"{primary_error}；备用入口也失败：{exc}") from exc
                raise

        viral_videos = viral_videos[:limit]
        diagnostics = self.last_search_diagnostics
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
        route_label = "、".join(routes) or "API23 搜索接口"
        if raw_items == 0:
            if responses and recognized_lists == 0:
                return "API23 返回了响应，但没有可识别的视频列表；接口响应结构可能已经更新。"
            if route_errors.get("/api/search/video"):
                return "API23 主搜索暂时不可用，备用 Discover 入口也没有返回视频候选；请稍后重试。"
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
