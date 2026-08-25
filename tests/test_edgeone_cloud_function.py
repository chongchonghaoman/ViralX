import importlib.util
import json
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "cloud-functions" / "api" / "[[default]].py"


class EdgeOneCloudFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_before = os.environ.copy()
        os.environ["VIRALX_RUNTIME"] = "edgeone"
        os.environ["VIRALX_MAX_ANALYZE_VIDEOS"] = "1"
        spec = importlib.util.spec_from_file_location("viralx_edgeone_api", ENTRYPOINT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module
        cls.client = module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        current_keys = set(os.environ)
        original_keys = set(cls.env_before)
        for key in current_keys - original_keys:
            os.environ.pop(key, None)
        os.environ.update(cls.env_before)

    def test_health_reports_boolean_readiness_without_secret_values(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["runtime"], "edgeone")
        self.assertEqual(payload["keyword_search_provider"], "api23")
        self.assertEqual(payload["limits"]["max_videos"], 1)
        self.assertIsInstance(payload["analysis_ready"], bool)
        self.assertTrue(all(isinstance(value, bool) for value in payload["configured"].values()))
        self.assertNotIn("access_key", json.dumps(payload).lower())
        self.assertNotIn("api_key", json.dumps(payload).lower())

    def test_session_byok_headers_affect_readiness_without_echoing_secrets(self):
        response = self.client.get(
            "/health",
            headers={
                "X-ViralX-Analysis-Mode": "libtv",
                "X-ViralX-LibTV-Key": "session-secret-libtv",
                "X-ViralX-RapidAPI-Key": "session-secret-rapid",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["analysis_ready"])
        self.assertTrue(payload["configured"]["libtv"])
        self.assertTrue(payload["configured"]["keyword_search"])
        serialized = json.dumps(payload)
        self.assertNotIn("session-secret-libtv", serialized)
        self.assertNotIn("session-secret-rapid", serialized)

    def test_empty_analysis_request_returns_ndjson_contract(self):
        response = self.client.post("/analyze", json={"keyword": ""})
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["done"])

    def test_keyword_search_without_api23_key_returns_actionable_error(self):
        response = self.client.post("/analyze", json={"keyword": "camping light"})
        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload["status"], "error")
        self.assertIn("API23", payload["message"])
        self.assertIn("RAPIDAPI_KEY", payload["message"])

    def test_private_settings_and_cache_routes_are_not_public(self):
        self.assertEqual(self.client.get("/settings").status_code, 404)
        self.assertEqual(self.client.post("/cache/clear").status_code, 404)

    def test_browser_obsidian_export_has_no_filesystem_write(self):
        response = self.client.post(
            "/export-obsidian",
            json={"title": "测试/报告", "content": "# 报告\n内容"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["mode"], "browser")
        self.assertNotIn("/", payload["filename"])
        self.assertEqual(payload["content"], "# 报告\n内容")
        self.assertTrue(payload["obsidian_uri"].startswith("obsidian://new?"))
        self.assertNotIn("file_path", payload)


if __name__ == "__main__":
    unittest.main()
