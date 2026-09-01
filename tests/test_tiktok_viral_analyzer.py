import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from tiktok_viral_analyzer import Scraper7SearchError, TikTokViralAnalyzer, safe_error_message


class TikTokViralAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.analyzer = TikTokViralAnalyzer(self.temp_dir.name)
        self.analyzer.api_key = "test-scraper7-secret"
        # These tests exercise the legacy Scraper7 adapter in isolation. The
        # chain-level API23-first behavior is covered separately below.
        self.api23_patcher = patch.object(TikTokViralAnalyzer, "_search_api23", return_value=[])
        self.api23_patcher.start()

    def tearDown(self):
        self.api23_patcher.stop()
        self.temp_dir.cleanup()

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_search_uses_feed_search_and_normalizes_data_videos(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "videos": [
                    {
                        "aweme_id": "7480000000000000001",
                        "title": "A bright camping lamp #outdoors #camping",
                        "author": {"unique_id": "lampmaker"},
                        "cover": "https://example.com/cover.jpg",
                        "duration": 18,
                        "digg_count": 12500,
                        "comment_count": 321,
                        "share_count": 88,
                        "play_count": 250000,
                        "collect_count": 901,
                        "create_time": 1_725_000_000,
                        "is_ad": False,
                    },
                    {
                        "aweme_id": "7480000000000000099",
                        "author": {"unique_id": "smallcreator"},
                        "digg_count": 4999,
                    },
                ],
                "has_more": 0,
                "cursor": 12,
            },
        }

        output = io.StringIO()
        with redirect_stdout(output):
            videos = self.analyzer.search_viral_videos("camping light", min_likes=5000, count=30)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["video_id"], "7480000000000000001")
        self.assertEqual(videos[0]["digg_count"], 12500)
        self.assertEqual(videos[0]["author"]["unique_id"], "lampmaker")
        self.assertEqual(videos[0]["hashtags"], ["outdoors", "camping"])
        self.assertEqual(videos[0]["search_provider"], "scraper7")
        self.assertNotIn(self.analyzer.api_key, output.getvalue())

        mock_get.assert_called_once_with(
            "https://tiktok-scraper7.p.rapidapi.com/feed/search",
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": "tiktok-scraper7.p.rapidapi.com",
                "x-rapidapi-key": "test-scraper7-secret",
            },
            params={
                "keywords": "camping light",
                "region": "US",
                "count": 30,
                "cursor": 0,
                "publish_time": 0,
                "sort_type": 0,
            },
            timeout=20,
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_accepts_legacy_nested_stats_and_video_asset(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "id": "7480000000000000002",
                        "desc": "Legacy wrapper",
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
                ]
            },
        }

        video = self.analyzer.search_viral_videos("portable lamp", min_likes=0, count=1)[0]

        self.assertEqual(video["author"]["unique_id"], "creatorTwo")
        self.assertEqual(video["digg_count"], 7654)
        self.assertEqual(video["duration"], 22)
        self.assertEqual(video["create_time"], 1725000001)
        self.assertTrue(video["is_ad"])

    @patch("tiktok_viral_analyzer.requests.get")
    def test_picture_light_intent_rejects_luminous_art_before_like_ranking(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "videos": [
                    {
                        "id": "7591234567890123458",
                        "title": "Rechargeable picture light for framed wall artwork",
                        "author": {"unique_id": "gallerylamp"},
                        "digg_count": 6200,
                    },
                    {
                        "id": "7665839717681761568",
                        "title": "Световая картина «Полночь» — glowing painting",
                        "author": {"unique_id": "bibikstore"},
                        "digg_count": 333800,
                    },
                ]
            },
        }

        videos = self.analyzer.search_viral_videos("picture light", min_likes=100, count=10)

        self.assertEqual([video["video_id"] for video in videos], ["7591234567890123458"])
        self.assertEqual(videos[0]["search_intent"], "picture-light-fixture")
        self.assertGreaterEqual(videos[0]["search_relevance"], 4)
        self.assertEqual(self.analyzer.last_search_diagnostics["rejected_irrelevant"], 1)
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["keywords"],
            "picture light wall mounted artwork lamp",
        )

    def test_chinese_picture_light_terms_share_the_fixture_search_intent(self):
        for keyword in ("照画灯", "壁画灯", "画框灯", "picture lights"):
            with self.subTest(keyword=keyword):
                plan = self.analyzer._search_plan(keyword)
                self.assertEqual(plan["intent"], "picture-light-fixture")
                self.assertIn("wall mounted", plan["query"])

    def test_scraper7_prefers_numeric_post_id_over_opaque_media_ids(self):
        video = self.analyzer._normalize_scraper7_video({
            "id": "7591234567890123456",
            "aweme_id": "v26044gc0000d9h8fffog65n0rasvjtg",
            "video_id": "v26044gc0000d9h8fffog65n0rasvjtg",
            "author": {"unique_id": "bibikstore"},
        })

        self.assertEqual(video["video_id"], "7591234567890123456")
        self.assertEqual(
            video["source_url"],
            "https://www.tiktok.com/@bibikstore/video/7591234567890123456",
        )

    def test_scraper7_extracts_post_id_from_canonical_share_url(self):
        video = self.analyzer._normalize_scraper7_video({
            "aweme_id": "v26044gc0000d9h8fffog65n0rasvjtg",
            "share_url": "https://www.tiktok.com/@creator/video/7591234567890123457?lang=en",
            "author": {"unique_id": "creator"},
        })

        self.assertEqual(video["video_id"], "7591234567890123457")
        self.assertIn("/video/7591234567890123457", video["source_url"])

    def test_scraper7_media_transport_is_private_and_host_limited(self):
        signed = "https://v16-webapp-prime.tiktok.com/video/tos/example.mp4?signature=secret"
        normalized = self.analyzer._normalize_scraper7_video({
            "id": "7591234567890123457",
            "author": {"unique_id": "creator"},
            "video": {"play_addr": {"url_list": [signed]}},
        })

        self.assertEqual(normalized["_media_transport_url"], signed)
        public = self.analyzer.extract_video_info(normalized)
        self.assertNotIn("_media_transport_url", public)
        self.assertNotIn("signature", repr(public))

        rejected = self.analyzer._normalize_scraper7_video({
            "id": "7591234567890123458",
            "video": {"play": "http://127.0.0.1:8000/private.mp4"},
        })
        self.assertEqual(rejected["_media_transport_url"], "")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_missing_key_stops_before_network_request(self, mock_get):
        self.analyzer.api_key = ""

        with self.assertRaisesRegex(RuntimeError, "RAPIDAPI_KEY.*API23.*Scraper7"):
            self.analyzer.search_viral_videos("camping light")

        mock_get.assert_not_called()

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_quota_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 429

        with self.assertRaisesRegex(RuntimeError, "Scraper7.*配额.*HTTP 429"):
            self.analyzer.search_viral_videos("camping light")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_business_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": -1, "msg": "upstream unavailable"}

        with self.assertRaisesRegex(RuntimeError, "Scraper7.*upstream unavailable.*-1"):
            self.analyzer.search_viral_videos("picture light")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_pagination_uses_nested_cursor(self, mock_get):
        first = Mock(status_code=200)
        first.json.return_value = {
            "code": 0,
            "data": {
                "has_more": 1,
                "cursor": 12,
                "videos": [{"aweme_id": "7480000000000000001", "digg_count": 100}],
            },
        }
        second = Mock(status_code=200)
        second.json.return_value = {
            "code": 0,
            "data": {
                "has_more": 0,
                "cursor": 24,
                "videos": [{"aweme_id": "7480000000000000002", "digg_count": 200}],
            },
        }
        mock_get.side_effect = [first, second]

        videos = self.analyzer.search_viral_videos("camping light", min_likes=0, count=2)

        self.assertEqual(
            [video["video_id"] for video in videos],
            ["7480000000000000001", "7480000000000000002"],
        )
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"]["cursor"], 0)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["cursor"], 12)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_legacy_search_url_and_host_overrides_still_control_scraper7(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"videos": []}}
        self.analyzer.SEARCH_URL = "https://mock.example.test/feed/search"
        self.analyzer.SEARCH_HOST = "mock.example.test"

        self.analyzer.search_viral_videos("camping lamp", min_likes=0, count=1)

        self.assertEqual(mock_get.call_args.args[0], "https://mock.example.test/feed/search")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["x-rapidapi-host"], "mock.example.test")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_unknown_scraper7_shape_is_not_reported_as_a_true_empty_list(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"unexpectedResults": []}}

        videos = self.analyzer.search_viral_videos("picture light", min_likes=0)

        self.assertEqual(videos, [])
        self.assertIn("响应结构可能已经更新", self.analyzer.empty_result_message())

    @patch("tiktok_viral_analyzer.requests.get")
    def test_empty_data_videos_is_distinguished_from_like_filtering(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"videos": []}}

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("item_list / data.videos", message)
        self.assertIn("没有返回视频候选", message)
        self.assertIn("与最低点赞数无关", message)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_scraper7_empty_message_explains_like_filtering(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "videos": [
                    {
                        "aweme_id": "7480000000000000003",
                        "title": "Wireless picture light above framed artwork",
                        "digg_count": 900,
                    },
                    {
                        "aweme_id": "7480000000000000004",
                        "title": "Rechargeable picture light wall lamp",
                        "digg_count": 1200,
                    },
                ]
            },
        }

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("2 条视频", message)
        self.assertIn("最高点赞为 1,200", message)
        self.assertIn("阈值 5,000", message)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_opaque_media_ids_are_rejected_instead_of_becoming_fake_links(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "videos": [{
                    "aweme_id": "v26044gc0000d9h8fffog65n0rasvjtg",
                    "video_id": "v26044gc0000d9h8fffog65n0rasvjtg",
                    "author": {"unique_id": "bibikstore"},
                    "digg_count": 12000,
                }]
            },
        }

        videos = self.analyzer.search_viral_videos("picture light", min_likes=100)

        self.assertEqual(videos, [])
        self.assertEqual(self.analyzer.last_search_diagnostics["invalid_post_ids"], 1)
        self.assertIn("ViralX 已停止生成假链接", self.analyzer.empty_result_message())

    @patch("tiktok_viral_analyzer.requests.get")
    def test_picture_light_empty_message_explains_semantic_rejection(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "videos": [{
                    "id": "7665839717681761568",
                    "title": "Light painting and glowing canvas wall art",
                    "digg_count": 333800,
                }]
            },
        }

        videos = self.analyzer.search_viral_videos("照画灯", min_likes=100)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("不是同一产品品类", message)
        self.assertIn("进入 TK Note 前剔除", message)

    def test_error_messages_redact_exact_and_token_shaped_secrets(self):
        message = safe_error_message(
            "x-rapidapi-key=test-scraper7-secret Authorization: Bearer another-secret",
            ("test-scraper7-secret",),
        )
        self.assertNotIn("test-scraper7-secret", message)
        self.assertNotIn("another-secret", message)
        self.assertIn("redacted", message)


class TikTokSearchChainTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.analyzer = TikTokViralAnalyzer(self.temp_dir.name)
        self.analyzer.api_key = "test-shared-rapidapi-key"

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def response(payload, status=200):
        result = Mock(status_code=status)
        result.json.return_value = payload
        return result

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_is_primary_and_uses_the_shared_key(self, mock_get):
        mock_get.return_value = self.response({
            "status_code": 0,
            "cursor": 12,
            "has_more": 0,
            "item_list": [{
                "id": "7591234567890123456",
                "desc": "Rechargeable picture light above framed wall artwork #homedecor",
                "author": {"uniqueId": "gallerylamp"},
                "stats": {"diggCount": 6200, "commentCount": 42, "playCount": 98000},
                "video": {
                    "duration": 18000,
                    "cover": {"url_list": ["https://example.com/api23-cover.jpg"]},
                },
            }],
        })

        videos = self.analyzer.search_viral_videos("picture light", min_likes=500, count=10)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["search_provider"], "api23")
        self.assertEqual(videos[0]["digg_count"], 6200)
        self.assertEqual(videos[0]["cover"], "https://example.com/api23-cover.jpg")
        self.assertFalse(self.analyzer.last_search_diagnostics["fallback_used"])
        mock_get.assert_called_once_with(
            "https://tiktok-api23.p.rapidapi.com/api/search/video",
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": "tiktok-api23.p.rapidapi.com",
                "x-rapidapi-key": "test-shared-rapidapi-key",
            },
            params={
                "keyword": "picture light wall mounted artwork lamp",
                "cursor": 0,
                "search_id": 0,
            },
            timeout=20,
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_business_error_falls_back_to_scraper7_without_interrupting(self, mock_get):
        mock_get.side_effect = [
            self.response({"status_code": 4, "status_msg": "Server is currently unavailable"}),
            self.response({
                "code": 0,
                "data": {"videos": [{
                    "id": "7591234567890123457",
                    "title": "Wireless picture light for gallery wall",
                    "author": {"unique_id": "fallbackcreator"},
                    "digg_count": 7100,
                }]},
            }),
        ]

        videos = self.analyzer.search_viral_videos("picture lights", min_likes=500, count=10)

        self.assertEqual([video["search_provider"] for video in videos], ["scraper7"])
        self.assertTrue(self.analyzer.last_search_diagnostics["fallback_used"])
        self.assertEqual(self.analyzer.last_search_diagnostics["fallback_reason"], "provider_error")
        self.assertIn("业务状态 4", self.analyzer.last_search_diagnostics["providers"]["api23"]["error"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["headers"]["x-rapidapi-key"], "test-shared-rapidapi-key")
        self.assertEqual(mock_get.call_args_list[1].kwargs["headers"]["x-rapidapi-host"], "tiktok-scraper7.p.rapidapi.com")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_empty_or_invalid_candidates_fall_back_to_scraper7(self, mock_get):
        for api23_payload, expected_reason in (
            ({"status_code": 0, "item_list": []}, "no_candidates"),
            ({
                "status_code": 0,
                "item_list": [{"aweme_id": "v26044gc0000opaque", "digg_count": 9000}],
            }, "no_valid_candidates"),
        ):
            with self.subTest(expected_reason=expected_reason):
                mock_get.reset_mock()
                mock_get.side_effect = [
                    self.response(api23_payload),
                    self.response({
                        "code": 0,
                        "data": {"videos": [{
                            "id": "7591234567890123458",
                            "title": "Picture light wall mounted fixture",
                            "digg_count": 8000,
                        }]},
                    }),
                ]
                videos = self.analyzer.search_viral_videos("picture light", min_likes=500, count=10)
                self.assertEqual(videos[0]["search_provider"], "scraper7")
                self.assertEqual(self.analyzer.last_search_diagnostics["fallback_reason"], expected_reason)
                self.assertEqual(mock_get.call_count, 2)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_mixed_root_and_data_pagination_fields_are_followed(self, mock_get):
        mock_get.side_effect = [
            self.response({
                "status_code": 0,
                "has_more": 1,
                "cursor": 12,
                "data": {
                    "search_id": "search-session-1",
                    "item_list": [{
                        "id": "7591234567890123460",
                        "desc": "Camping lantern one",
                        "stats": {"diggCount": 1000},
                    }],
                },
            }),
            self.response({
                "status_code": 0,
                "has_more": 0,
                "cursor": 24,
                "data": {"item_list": [{
                    "id": "7591234567890123461",
                    "desc": "Camping lantern two",
                    "stats": {"diggCount": 2000},
                }]},
            }),
        ]

        videos = self.analyzer.search_viral_videos("camping lantern", min_likes=0, count=2)

        self.assertEqual([video["video_id"] for video in videos], [
            "7591234567890123460", "7591234567890123461",
        ])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["cursor"], 12)
        self.assertEqual(mock_get.call_args_list[1].kwargs["params"]["search_id"], "search-session-1")

    @patch("tiktok_viral_analyzer.requests.get")
    def test_api23_does_not_treat_generic_items_as_video_results(self, mock_get):
        mock_get.side_effect = [
            self.response({
                "status_code": 0,
                "items": [{"id": "7591234567890123462", "title": "search suggestion"}],
            }),
            self.response({
                "code": 0,
                "data": {"videos": [{
                    "id": "7591234567890123463",
                    "title": "Camping light review",
                    "digg_count": 1500,
                }]},
            }),
        ]

        videos = self.analyzer.search_viral_videos("camping light", min_likes=0, count=1)

        self.assertEqual(videos[0]["video_id"], "7591234567890123463")
        self.assertEqual(videos[0]["search_provider"], "scraper7")
        self.assertEqual(self.analyzer.last_search_diagnostics["providers"]["api23"]["raw_items"], 0)

    def test_api23_business_status_is_case_insensitive_and_checks_nested_data(self):
        self.assertEqual(self.analyzer._api23_business_error({"status": "SUCCESS"}), "")
        self.assertIn(
            "业务状态 4",
            self.analyzer._api23_business_error({
                "data": {"status_code": 4, "status_msg": "temporarily unavailable"},
            }),
        )

    @patch("tiktok_viral_analyzer.requests.get")
    def test_both_empty_returns_one_combined_actionable_message(self, mock_get):
        mock_get.side_effect = [
            self.response({"status_code": 0, "item_list": []}),
            self.response({"code": 0, "data": {"videos": []}}),
        ]

        videos = self.analyzer.search_viral_videos("camping lamp", min_likes=500, count=10)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("API23 已自动回退到 TikTok Scraper7", message)
        self.assertIn("与最低点赞数无关", message)

    @patch("tiktok_viral_analyzer.requests.get")
    def test_both_provider_failures_raise_only_after_fallback_and_redact_key(self, mock_get):
        mock_get.side_effect = [
            self.response({}, status=403),
            self.response({}, status=429),
        ]

        with self.assertRaisesRegex(Scraper7SearchError, "API23 与 TikTok Scraper7 均未完成搜索") as raised:
            self.analyzer.search_viral_videos("camping lamp", min_likes=500, count=10)

        self.assertEqual(mock_get.call_count, 2)
        self.assertNotIn(self.analyzer.api_key, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
