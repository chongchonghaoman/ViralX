import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from tiktok_viral_analyzer import TikTokViralAnalyzer, safe_error_message


class TikTokViralAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.analyzer = TikTokViralAnalyzer(self.temp_dir.name)
        self.analyzer.api_key = "test-api23-secret"

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_search_uses_documented_request_and_normalizes_item_list(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "item_list": [
                {
                    "id": "7480000000000000001",
                    "desc": "A bright camping lamp #outdoors",
                    "create_time": 1_725_000_000,
                    "author": {"unique_id": "lampmaker"},
                    "challenges": [{"title": "outdoors"}, {"title": "camping"}],
                    "video": {"duration": 18, "cover": "https://example.com/cover.jpg"},
                    "stats": {
                        "digg_count": 12500,
                        "comment_count": 321,
                        "share_count": 88,
                        "play_count": 250000,
                        "collect_count": 901,
                    },
                    "is_ad": False,
                },
                {
                    "id": "low-like-video",
                    "author": {"unique_id": "smallcreator"},
                    "stats": {"digg_count": 4999},
                },
            ]
        }

        output = io.StringIO()
        with redirect_stdout(output):
            videos = self.analyzer.search_viral_videos("camping light", min_likes=5000, count=30)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["video_id"], "7480000000000000001")
        self.assertEqual(videos[0]["digg_count"], 12500)
        self.assertEqual(videos[0]["author"]["unique_id"], "lampmaker")
        self.assertEqual(videos[0]["hashtags"], ["outdoors", "camping"])
        self.assertEqual(videos[0]["search_provider"], "api23")
        self.assertNotIn(self.analyzer.api_key, output.getvalue())

        mock_get.assert_called_once_with(
            "https://tiktok-api23.p.rapidapi.com/api/search/video",
            headers={
                "x-rapidapi-key": "test-api23-secret",
                "x-rapidapi-host": "tiktok-api23.p.rapidapi.com",
            },
            params={"keyword": "camping light"},
            timeout=15,
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_search_accepts_nested_camel_case_response(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": {
                "itemList": [
                    {
                        "item": {
                            "id": "7480000000000000002",
                            "desc": "Camel case payload",
                            "createTime": "1725000001",
                            "author": {"uniqueId": "creatorTwo"},
                            "video": {"duration": "22", "cover": "https://example.com/two.jpg"},
                            "stats": {
                                "diggCount": "7654",
                                "commentCount": "44",
                                "shareCount": "12",
                                "playCount": "90000",
                                "collectCount": "77",
                            },
                            "isAd": True,
                        }
                    }
                ]
            }
        }

        videos = self.analyzer.search_viral_videos("portable lamp", min_likes=0, count=1)
        video = videos[0]

        self.assertEqual(video["author"]["unique_id"], "creatorTwo")
        self.assertEqual(video["digg_count"], 7654)
        self.assertEqual(video["duration"], 22)
        self.assertEqual(video["create_time"], 1725000001)
        self.assertTrue(video["is_ad"])

    @patch("tiktok_viral_analyzer.requests.get")
    def test_missing_key_stops_before_network_request(self, mock_get):
        self.analyzer.api_key = ""

        with self.assertRaisesRegex(RuntimeError, "API23.*RAPIDAPI_KEY"):
            self.analyzer.search_viral_videos("camping light")

        mock_get.assert_not_called()

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_quota_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 429

        with self.assertRaisesRegex(RuntimeError, "API23.*配额.*HTTP 429"):
            self.analyzer.search_viral_videos("camping light")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_pagination_uses_cursor_and_search_id(self, mock_get):
        first = Mock(status_code=200)
        first.json.return_value = {
            "has_more": 1,
            "cursor": 10,
            "log_pb": {"impr_id": "search-session-1"},
            "item_list": [{"id": "first", "stats": {"digg_count": 100}}],
        }
        second = Mock(status_code=200)
        second.json.return_value = {
            "has_more": 0,
            "cursor": 20,
            "item_list": [{"id": "second", "stats": {"digg_count": 200}}],
        }
        mock_get.side_effect = [first, second]

        videos = self.analyzer.search_viral_videos("camping light", min_likes=0, count=2)

        self.assertEqual([video["video_id"] for video in videos], ["first", "second"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"], {"keyword": "camping light"})
        self.assertEqual(
            mock_get.call_args_list[1].kwargs["params"],
            {"keyword": "camping light", "cursor": 10, "search_id": "search-session-1"},
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_falls_back_to_discover_posts(self, mock_get):
        search = Mock(status_code=200)
        search.json.return_value = {"hasMore": 0, "item_list": []}
        general = Mock(status_code=200)
        general.json.return_value = {"hasMore": 0, "data": []}
        discover = Mock(status_code=200)
        discover.json.return_value = {
            "hasMore": False,
            "videoList": [
                {
                    "id": "discover-result",
                    "desc": "Picture light for a gallery wall",
                    "author": {"uniqueId": "lightingstudio"},
                    "stats": {"diggCount": 25000, "playCount": 800000},
                    "video": {"duration": 17},
                }
            ],
        }
        mock_get.side_effect = [search, general, discover]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000, count=30)

        self.assertEqual([video["video_id"] for video in videos], ["discover-result"])
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_get.call_args_list[1].args[0], self.analyzer.GENERAL_SEARCH_URL)
        self.assertEqual(mock_get.call_args_list[2].args[0], self.analyzer.DISCOVER_URL)
        self.assertEqual(
            mock_get.call_args_list[2].kwargs["params"],
            {"keyword": "picture light", "page": 1},
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_falls_back_to_trending_keyword_and_resolves_post_detail(self, mock_get):
        search = Mock(status_code=200)
        search.json.return_value = {"status_code": 0, "item_list": []}
        general = Mock(status_code=200)
        general.json.return_value = {"status_code": 0, "item_list": []}
        unavailable = Mock(status_code=200)
        unavailable.json.return_value = {
            "status_code": 4,
            "status_msg": "Server is currently unavailable. Please try again later.",
        }
        trending = Mock(status_code=200)
        trending.json.return_value = {"data": {"video_list": ["7588556037062479135"]}}
        detail = Mock(status_code=200)
        detail.json.return_value = {
            "itemInfo": {
                "itemStruct": {
                    "id": "7588556037062479135",
                    "desc": "Picture light styling idea",
                    "author": {"uniqueId": "gallerylighting"},
                    "stats": {"diggCount": 8400, "playCount": 210000},
                    "video": {"duration": 19, "cover": "https://example.com/detail.jpg"},
                }
            }
        }
        mock_get.side_effect = [search, general, unavailable, trending, detail]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=100, count=30)

        self.assertEqual([video["video_id"] for video in videos], ["7588556037062479135"])
        self.assertEqual(videos[0]["digg_count"], 8400)
        self.assertEqual(
            mock_get.call_args_list[3].kwargs["params"],
            {"keyword": "picture light", "country": "US", "limit": 10, "period": 120},
        )
        self.assertEqual(
            mock_get.call_args_list[4].kwargs["params"],
            {"videoId": "7588556037062479135"},
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_explains_when_trending_ids_cannot_be_resolved(self, mock_get):
        empty = Mock(status_code=200)
        empty.json.return_value = {"status_code": 0, "item_list": []}
        unavailable = Mock(status_code=200)
        unavailable.json.return_value = {
            "status_code": 4,
            "status_msg": "Server is currently unavailable. Please try again later.",
        }
        trending = Mock(status_code=200)
        trending.json.return_value = {"data": {"video_list": ["7588556037062479135"]}}
        mock_get.side_effect = [empty, empty, unavailable, trending, unavailable]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=100)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("返回了 1 个视频 ID", message)
        self.assertIn("Post Detail 暂时不可用", message)
        self.assertIn("尚不能执行热度筛选", message)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_http_200_business_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status_code": 10222,
            "status_msg": "Search upstream is unavailable",
        }

        with self.assertRaisesRegex(RuntimeError, "API23.*Search upstream.*10222"):
            self.analyzer.search_viral_videos("picture light")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_status_four_uses_search_general_fallback(self, mock_get):
        unavailable = Mock(status_code=200)
        unavailable.json.return_value = {
            "status_code": 4,
            "status_msg": "Server is currently unavailable. Please try again later.",
        }
        general = Mock(status_code=200)
        general.json.return_value = {
            "hasMore": False,
            "data": [
                {
                    "type": 1,
                    "item": {
                        "id": "general-after-status-four",
                        "desc": "Picture light ideas",
                        "stats": {"diggCount": 9000},
                        "video": {"duration": 15},
                    },
                },
                {"type": 2, "user": {"id": "not-a-video"}},
            ],
        }
        mock_get.side_effect = [unavailable, general]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000)

        self.assertEqual([video["video_id"] for video in videos], ["general-after-status-four"])
        self.assertEqual(mock_get.call_args_list[1].args[0], self.analyzer.GENERAL_SEARCH_URL)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_reports_when_all_routes_are_unavailable(self, mock_get):
        unavailable = Mock(status_code=200)
        unavailable.json.return_value = {
            "status_code": 4,
            "status_msg": "Server is currently unavailable. Please try again later.",
        }
        mock_get.side_effect = [unavailable, unavailable, unavailable, unavailable]

        with self.assertRaisesRegex(RuntimeError, "关键词入口均失败.*Search General.*Discover.*Trending"):
            self.analyzer.search_viral_videos("picture light", min_likes=0)

        self.assertEqual(mock_get.call_count, 4)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_fallback_status_four_does_not_mask_a_valid_empty_search(self, mock_get):
        search = Mock(status_code=200)
        search.json.return_value = {"hasMore": 0, "item_list": []}
        unavailable = Mock(status_code=200)
        unavailable.json.return_value = {
            "status_code": 4,
            "status_msg": "Server is currently unavailable. Please try again later.",
        }
        mock_get.side_effect = [search, unavailable, unavailable, unavailable]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=500)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("Search Video 返回 item_list=0", message)
        self.assertIn("与最低点赞数无关", message)
        self.assertIn("Search General、Discover、Trending Video by Keyword 暂时不可用", message)

    def test_error_messages_redact_exact_and_token_shaped_secrets(self):
        message = safe_error_message(
            "x-rapidapi-key=test-api23-secret Authorization: Bearer another-secret",
            ("test-api23-secret",),
        )
        self.assertNotIn("test-api23-secret", message)
        self.assertNotIn("another-secret", message)
        self.assertIn("redacted", message)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_unknown_api23_shape_is_not_reported_as_a_true_empty_list(self, mock_get):
        first = Mock(status_code=200)
        first.json.return_value = {"unexpectedResults": [{"id": "one"}]}
        second = Mock(status_code=200)
        second.json.return_value = {"anotherUnexpectedShape": True}
        third = Mock(status_code=200)
        third.json.return_value = {"thirdUnexpectedShape": True}
        fourth = Mock(status_code=200)
        fourth.json.return_value = {"fourthUnexpectedShape": True}
        mock_get.side_effect = [first, second, third, fourth]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=0)

        self.assertEqual(videos, [])
        self.assertIn("响应结构可能已经更新", self.analyzer.empty_result_message())

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_empty_message_distinguishes_like_filtering(self, mock_get):
        search = Mock(status_code=200)
        search.json.return_value = {
            "hasMore": False,
            "item_list": [{"id": "low-search", "stats": {"diggCount": 900}}],
        }
        general = Mock(status_code=200)
        general.json.return_value = {
            "hasMore": False,
            "data": [
                {
                    "item": {
                        "id": "low-general",
                        "stats": {"diggCount": 1000},
                        "video": {"duration": 10},
                    }
                }
            ],
        }
        discover = Mock(status_code=200)
        discover.json.return_value = {
            "hasMore": False,
            "videoList": [{"id": "low-discover", "stats": {"diggCount": 1200}}],
        }
        trending = Mock(status_code=200)
        trending.json.return_value = {"data": {"video_list": []}}
        mock_get.side_effect = [search, general, discover, trending]

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("3 条视频", message)
        self.assertIn("最高点赞为 1,200", message)
        self.assertIn("阈值 5,000", message)


if __name__ == "__main__":
    unittest.main()
