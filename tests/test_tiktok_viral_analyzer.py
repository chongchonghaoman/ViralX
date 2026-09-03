import io
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from viralx.tiktok_viral_analyzer import (
    Scraper7SearchError,
    TikTokSearchChainError,
    TikTokViralAnalyzer,
    safe_error_message,
)


class TikTokViralAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.analyzer = TikTokViralAnalyzer(self.temp_dir.name)
        self.analyzer.api_key = "test-scraper7-secret"
        # These tests exercise one provider adapter in isolation. Multi-source
        # continuation, merge and deduplication are covered separately below.
        self.analyzer.search_provider_chain = ("scraper7",)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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
                "User-Agent": "ViralX-Keyword-Search/2.0",
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_missing_key_stops_before_network_request(self, mock_get):
        self.analyzer.api_key = ""

        with self.assertRaisesRegex(RuntimeError, "RAPIDAPI_KEY.*多源搜索链"):
            self.analyzer.search_viral_videos("camping light")

        mock_get.assert_not_called()

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_scraper7_quota_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 429

        with self.assertRaisesRegex(RuntimeError, "Scraper7.*配额.*HTTP 429"):
            self.analyzer.search_viral_videos("camping light")

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_scraper7_business_error_is_actionable(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": -1, "msg": "upstream unavailable"}

        with self.assertRaisesRegex(RuntimeError, "Scraper7.*upstream unavailable.*-1"):
            self.analyzer.search_viral_videos("picture light")

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_scraper7_reads_one_page_before_the_chain_continues(self, mock_get):
        mock_get.return_value = Mock(status_code=200)
        mock_get.return_value.json.return_value = {
            "code": 0,
            "data": {
                "has_more": 1,
                "cursor": 12,
                "videos": [
                    {"aweme_id": "7480000000000000001", "digg_count": 100},
                    {"aweme_id": "7480000000000000002", "digg_count": 200},
                ],
            },
        }

        videos = self.analyzer.search_viral_videos("camping light", min_likes=0, count=2)

        self.assertEqual(
            [video["video_id"] for video in videos],
            ["7480000000000000002", "7480000000000000001"],
        )
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_get.call_args_list[0].kwargs["params"]["cursor"], 0)

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_provider_registry_override_controls_scraper7(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"videos": []}}
        provider = dict(self.analyzer.SEARCH_PROVIDERS["scraper7"])
        provider.update({"url": "https://mock.example.test/feed/search", "host": "mock.example.test"})
        self.analyzer.SEARCH_PROVIDERS = {**self.analyzer.SEARCH_PROVIDERS, "scraper7": provider}

        self.analyzer.search_viral_videos("camping lamp", min_likes=0, count=1)

        self.assertEqual(mock_get.call_args.args[0], "https://mock.example.test/feed/search")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["x-rapidapi-host"], "mock.example.test")

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_unknown_scraper7_shape_is_not_reported_as_a_true_empty_list(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"unexpectedResults": []}}

        videos = self.analyzer.search_viral_videos("picture light", min_likes=0)

        self.assertEqual(videos, [])
        self.assertIn("接口结构可能已经更新", self.analyzer.empty_result_message())

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_empty_data_videos_is_distinguished_from_like_filtering(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"code": 0, "data": {"videos": []}}

        videos = self.analyzer.search_viral_videos("picture light", min_likes=5000)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("所有可用搜索源", message)
        self.assertIn("没有返回视频候选", message)
        self.assertIn("与最低点赞数无关", message)

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
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

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_api6_is_primary_and_normalizes_statistics(self, mock_get):
        mock_get.return_value = self.response({
            "videos": [{
                "id": "7591234567890123456",
                "description": "Rechargeable picture light above framed wall artwork #homedecor",
                "author": "gallerylamp",
                "statistics": {
                    "number_of_hearts": 6200,
                    "number_of_comments": 42,
                    "number_of_plays": 98000,
                },
                "video": {
                    "play_addr": {
                        "url_list": ["https://v16.tiktokcdn.com/api6-primary.mp4?token=short-lived"]
                    }
                },
            }],
        })

        videos = self.analyzer.search_viral_videos("picture light", min_likes=500, count=1)

        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["search_provider"], "api6")
        self.assertEqual(videos[0]["digg_count"], 6200)
        self.assertEqual(videos[0]["author"]["unique_id"], "gallerylamp")
        self.assertIn("@gallerylamp/video/", videos[0]["source_url"])
        self.assertFalse(self.analyzer.last_search_diagnostics["fallback_used"])
        mock_get.assert_called_once_with(
            "https://tiktok-api6.p.rapidapi.com/search/general/query",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "ViralX-Keyword-Search/2.0",
                "x-rapidapi-host": "tiktok-api6.p.rapidapi.com",
                "x-rapidapi-key": "test-shared-rapidapi-key",
            },
            params={
                "query": "picture light wall mounted artwork lamp",
                "cursor": 0,
                "sort_type": 1,
            },
            timeout=20,
        )

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_empty_primary_falls_through_to_scraptik_without_interrupting(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraptik")
        mock_get.side_effect = [
            self.response({"videos": []}),
            self.response({"search_item_list": [{"aweme_info": {
                "aweme_id": "7591234567890123457",
                "desc": "Wireless picture light for gallery wall",
                "author": {"unique_id": "fallbackcreator"},
                "statistics": {"digg_count": 7100},
            }}]}),
        ]

        videos = self.analyzer.search_viral_videos("picture lights", min_likes=500, count=1)

        self.assertEqual([video["search_provider"] for video in videos], ["scraptik"])
        self.assertTrue(self.analyzer.last_search_diagnostics["fallback_used"])
        self.assertEqual(self.analyzer.last_search_diagnostics["attempted_providers"], ["api6", "scraptik"])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1].kwargs["headers"]["x-rapidapi-key"], "test-shared-rapidapi-key")
        self.assertEqual(mock_get.call_args_list[1].kwargs["headers"]["x-rapidapi-host"], "scraptik.p.rapidapi.com")

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_chain_merges_and_deduplicates_until_target(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraptik", "scraper7")
        mock_get.side_effect = [
            self.response({"videos": [
                {"id": "7591234567890123460", "description": "Camping lamp one", "statistics": {"number_of_hearts": 1000}, "video": {"play": "https://v16.tiktokcdn.com/camping-one.mp4"}},
                {"id": "7591234567890123461", "description": "Camping lamp two", "statistics": {"number_of_hearts": 2000}, "video": {"play": "https://v16.tiktokcdn.com/camping-two.mp4"}},
            ]}),
            self.response({"search_item_list": [
                {"aweme_info": {"id": "7591234567890123461", "desc": "Duplicate lamp", "stats": {"diggCount": 2000}}},
                {"aweme_info": {"id": "7591234567890123462", "desc": "Camping lamp three", "stats": {"diggCount": 3000}, "video": {"play": "https://v16.tiktokcdn.com/camping-three.mp4"}}},
            ]}),
        ]

        videos = self.analyzer.search_viral_videos("camping lamp", min_likes=0, count=3)

        self.assertEqual([video["video_id"] for video in videos], [
            "7591234567890123462", "7591234567890123461", "7591234567890123460",
        ])
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(self.analyzer.last_search_diagnostics["selected_provider"], "multi")
        self.assertEqual(self.analyzer.last_search_diagnostics["selected_items"], 3)

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_later_provider_enriches_duplicate_with_private_media_transport(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraper7")
        video_id = "7591234567890123499"
        transport_url = "https://v16.tiktokcdn.com/enriched.mp4?token=short-lived"
        mock_get.side_effect = [
            self.response({"videos": [{
                "id": video_id,
                "description": "Rechargeable picture light above framed wall artwork",
                "statistics": {"number_of_hearts": 56000},
            }]}),
            self.response({"code": 0, "data": {"videos": [{
                "id": video_id,
                "title": "Rechargeable picture light above framed wall artwork",
                "digg_count": 56000,
                "video": {"play_addr": {"url_list": [transport_url]}},
            }]}}),
        ]

        videos = self.analyzer.search_viral_videos("picture lights", min_likes=500, count=1)

        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["_media_transport_url"], transport_url)
        self.assertEqual(self.analyzer.last_search_diagnostics["enriched_media_urls"], 1)
        public_video = self.analyzer.extract_video_info(videos[0])
        self.assertNotIn("_media_transport_url", public_video)
        self.assertNotIn("short-lived", repr(public_video))

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_provider_http_failure_is_invisible_when_next_source_works(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "download5")
        mock_get.side_effect = [
            self.response({}, status=429),
            self.response({"code": 0, "data": {"videos": [{
                "id": "7591234567890123463",
                "title": "Camping light review",
                "digg_count": 1500,
            }]}}),
        ]

        videos = self.analyzer.search_viral_videos("camping light", min_likes=0, count=1)

        self.assertEqual(videos[0]["search_provider"], "download5")
        self.assertIn("HTTP 429", self.analyzer.last_search_diagnostics["providers"]["api6"]["error"])
        self.assertNotIn(self.analyzer.api_key, repr(self.analyzer.last_search_diagnostics))

    def test_provider_parameter_adapters_cover_all_seven_sources(self):
        expected_modes = {
            "api6": ("query", 0),
            "scraptik": ("keyword", 10),
            "scraper7": ("keywords", 30),
            "download5": ("keywords", 10),
            "tokapi": ("keyword", 10),
            "download1": ("keywords", 10),
            "api15": ("keywords", 10),
        }
        for provider_id, (keyword_field, expected_count) in expected_modes.items():
            with self.subTest(provider=provider_id):
                params = self.analyzer._provider_params(
                    self.analyzer.SEARCH_PROVIDERS[provider_id], "picture light", 50,
                )
                self.assertEqual(params[keyword_field], "picture light")
                if provider_id != "api6":
                    self.assertEqual(params["count"], expected_count)

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_all_empty_returns_one_provider_agnostic_message(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraptik")
        mock_get.side_effect = [
            self.response({"videos": []}),
            self.response({"search_item_list": []}),
        ]

        videos = self.analyzer.search_viral_videos("camping lamp", min_likes=500, count=10)

        self.assertEqual(videos, [])
        message = self.analyzer.empty_result_message()
        self.assertIn("所有可用搜索源", message)
        self.assertIn("与最低点赞数无关", message)

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_all_provider_failures_raise_only_after_chain_and_redact_key(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraptik")
        mock_get.side_effect = [
            self.response({}, status=403),
            self.response({}, status=429),
        ]

        with self.assertRaisesRegex(Scraper7SearchError, "TikTok 多源搜索链均未完成") as raised:
            self.analyzer.search_viral_videos("camping lamp", min_likes=500, count=10)

        self.assertEqual(mock_get.call_count, 2)
        self.assertNotIn(self.analyzer.api_key, str(raised.exception))

    @patch("viralx.tiktok_viral_analyzer.requests.get")
    def test_all_forbidden_providers_expose_safe_subscription_links(self, mock_get):
        self.analyzer.search_provider_chain = ("api6", "scraptik")
        mock_get.side_effect = [
            self.response({}, status=403),
            self.response({}, status=403),
        ]

        with self.assertRaises(TikTokSearchChainError) as raised:
            self.analyzer.search_viral_videos("camping lamp", min_likes=500, count=10)

        error = raised.exception
        self.assertEqual(error.error_code, "rapidapi_subscription_required")
        self.assertEqual([item["provider"] for item in error.subscription_links], ["api6", "scraptik"])
        self.assertTrue(all(item["url"].startswith("https://rapidapi.com/") for item in error.subscription_links))
        self.assertTrue(all(item["status_code"] == 403 for item in error.provider_errors))
        self.assertIn("订阅至少一个来源", str(error))

    def test_subscription_links_require_exact_safe_rapidapi_origin(self):
        provider = self.analyzer.SEARCH_PROVIDERS["api6"]
        unsafe_urls = (
            "http://rapidapi.com/omarmhaimdat/api/tiktok-api6/pricing",
            "https://rapidapi.com.evil.example/tiktok-api6/pricing",
            "https://user:password@rapidapi.com/tiktok-api6/pricing",
            "https://rapidapi.com:444/tiktok-api6/pricing",
        )

        for unsafe_url in unsafe_urls:
            with self.subTest(url=unsafe_url), patch.dict(provider, {"subscription_url": unsafe_url}):
                self.assertEqual(self.analyzer.provider_subscription_links(("api6",)), [])


if __name__ == "__main__":
    unittest.main()
