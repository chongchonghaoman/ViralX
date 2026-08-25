#!/usr/bin/env python3
"""
TikTok 美区爆款视频分析工具
使用 TikTok Research API 或第三方 API 抓取爆款视频
"""
import requests
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

class TikTokViralAnalyzer:
    SEARCH_PROVIDER = "api23"
    SEARCH_HOST = "tiktok-api23.p.rapidapi.com"
    SEARCH_URL = f"https://{SEARCH_HOST}/api/search/video"
    SEARCH_TIMEOUT_SECONDS = 15

    def __init__(self, output_dir="E:/tiktok_analyzer/data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = ""  # RapidAPI API23 key；仅用于关键词发现

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
            for key in ("item_list", "itemList", "items"):
                value = container.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

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
        """Use RapidAPI API23 for keyword discovery and return ViralX video rows."""
        clean_keyword = str(keyword or "").strip()
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
        cursor: Any = 0
        search_id = "0"
        seen_pages = set()
        seen_video_ids = set()
        viral_videos: List[Dict] = []

        # API23 uses cursor + log_pb.impr_id for subsequent pages. Five pages
        # keeps a single ViralX search bounded while still honoring count=30.
        for _ in range(5):
            page_signature = (str(cursor), str(search_id))
            if page_signature in seen_pages:
                break
            seen_pages.add(page_signature)

            params = {"keyword": clean_keyword, "cursor": cursor, "search_id": search_id}
            try:
                response = requests.get(
                    self.SEARCH_URL,
                    headers=headers,
                    params=params,
                    timeout=self.SEARCH_TIMEOUT_SECONDS,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"API23 关键词搜索请求失败：{exc}") from exc

            if response.status_code != 200:
                message = error_messages.get(response.status_code, "API23 关键词搜索暂时不可用")
                raise RuntimeError(f"{message}（HTTP {response.status_code}）")

            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("API23 返回了无法解析的响应") from exc

            items = self._api23_items(payload)
            for item in items:
                video = self._normalize_api23_video(item)
                video_id = video["video_id"]
                if (
                    video_id
                    and video_id not in seen_video_ids
                    and video["digg_count"] >= self._integer(min_likes)
                ):
                    seen_video_ids.add(video_id)
                    viral_videos.append(video)
                    if len(viral_videos) >= limit:
                        break
            if len(viral_videos) >= limit:
                break

            root = self._mapping(payload)
            nested = self._mapping(root.get("data"))
            container = nested if any(
                isinstance(nested.get(key), list) for key in ("item_list", "itemList", "items")
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

        viral_videos = viral_videos[:limit]
        print(f"[API23] 找到 {len(viral_videos)} 个符合阈值的视频")
        return viral_videos

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
