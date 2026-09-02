import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "cloud-functions" / "api" / "[[default]].py"


class EdgeOneCloudFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_before = os.environ.copy()
        os.environ["VIRALX_RUNTIME"] = "edgeone"
        os.environ["VIRALX_MAX_ANALYZE_VIDEOS"] = "1"
        os.environ["VIRALX_WORKER_PROXY_ENABLED"] = "0"
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
        self.assertEqual(payload["keyword_search_provider"], "rapidapi-multisource")
        self.assertEqual(payload["keyword_search_strategy"], "api6-scraptik-scraper7-download5-tokapi-download1-api15")
        self.assertEqual(payload["limits"]["max_videos"], 1)
        self.assertIsInstance(payload["analysis_ready"], bool)
        self.assertTrue(all(isinstance(value, bool) for value in payload["configured"].values()))
        self.assertNotIn("access_key", json.dumps(payload).lower())
        self.assertNotIn("api_key", json.dumps(payload).lower())

    def test_libtv_is_explicitly_local_only_even_with_legacy_header(self):
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
        self.assertFalse(payload["analysis_ready"])
        self.assertFalse(payload["configured"]["libtv"])
        self.assertTrue(payload["configured"]["keyword_search"])
        self.assertEqual(payload["libtv"]["connection_state"], "local_only")
        self.assertEqual(payload["libtv"]["scope"], "local")
        serialized = json.dumps(payload)
        self.assertNotIn("session-secret-libtv", serialized)
        self.assertNotIn("session-secret-rapid", serialized)

    def test_cloud_pipeline_analysis_returns_local_runtime_recovery(self):
        response = self.client.post(
            "/analyze",
            json={"keyword": "https://www.tiktok.com/@creator/video/123"},
            headers={"X-ViralX-Analysis-Mode": "pipeline"},
        )
        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload["status"], "error")
        self.assertIn("ViralX Worker", payload["message"])
        self.assertIn("TK Note", payload["message"])
        self.assertIn("模型 API", payload["message"])

    def test_generic_model_headers_select_provider_without_echoing_key(self):
        response = self.client.get(
            "/health",
            headers={
                "X-ViralX-Analysis-Mode": "model",
                "X-ViralX-Model-Provider": "openai",
                "X-ViralX-Model-Key": "session-secret-model",
                "X-ViralX-Model-Name": "gpt-4.1-mini",
            },
        )
        payload = response.get_json()
        self.assertEqual(payload["analysis_provider"], "openai")
        self.assertFalse(payload["analysis_ready"])
        self.assertTrue(payload["configured"]["model"])
        self.assertNotIn("session-secret-model", json.dumps(payload))

    def test_cloud_custom_model_rejects_insecure_or_private_endpoint(self):
        response = self.client.get(
            "/health",
            headers={
                "X-ViralX-Analysis-Mode": "model",
                "X-ViralX-Model-Provider": "custom",
                "X-ViralX-Model-Protocol": "openai",
                "X-ViralX-Model-Key": "session-secret-model",
                "X-ViralX-Model-Base-URL": "http://127.0.0.1:11434/v1",
                "X-ViralX-Model-Name": "local-model",
            },
        )
        payload = response.get_json()
        self.assertEqual(payload["analysis_provider"], "custom")
        self.assertFalse(payload["analysis_ready"])

    def test_empty_analysis_request_returns_ndjson_contract(self):
        response = self.client.post("/analyze", json={"keyword": ""})
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["done"])

    def test_direct_cloud_pipeline_endpoint_never_claims_local_analysis(self):
        response = self.client.post("/analyze", json={"keyword": "camping light"})
        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload["status"], "error")
        self.assertIn("Worker", payload["message"])
        self.assertIn("镜头取证", payload["message"])

    def test_private_settings_and_cache_routes_are_not_public(self):
        self.assertEqual(self.client.get("/settings").status_code, 404)
        self.assertEqual(self.client.post("/cache/clear").status_code, 404)
        self.assertEqual(self.client.post("/libtv/auth/start").status_code, 404)

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

    def test_same_origin_health_proxy_forwards_only_worker_safe_headers(self):
        upstream = requests.Response()
        upstream.status_code = 200
        upstream._content = json.dumps({"status": "ok", "runtime": "worker"}).encode("utf-8")
        upstream.headers["Content-Type"] = "application/json"

        with patch.object(self.module, "WORKER_PROXY_ENABLED", True), patch.object(
            self.module.requests,
            "request",
            return_value=upstream,
        ) as request_mock:
            response = self.client.get(
                "/health",
                headers={
                    "X-ViralX-Model-Key": "session-secret-model",
                    "X-ViralX-TK-Proxy": "http://127.0.0.1:7890",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["runtime"], "worker")
        call = request_mock.call_args
        self.assertEqual(call.args[:2], ("GET", f"{self.module.WORKER_BASE_URL}/api/health"))
        self.assertEqual(call.kwargs["headers"]["Origin"], "https://viralx.metrolabs.mobi")
        self.assertEqual(call.kwargs["headers"]["X-ViralX-Model-Key"], "session-secret-model")
        self.assertNotIn("X-ViralX-TK-Proxy", call.kwargs["headers"])

    def test_worker_proxy_falls_back_to_ipv4_relay_with_original_tls_hostname(self):
        upstream = requests.Response()
        upstream.status_code = 200
        upstream._content = json.dumps({"status": "ok", "runtime": "worker"}).encode("utf-8")
        upstream.headers["Content-Type"] = "application/json"

        class FakeSession:
            def __init__(self):
                self.trust_env = True
                self.mount_args = None
                self.request_args = None
                self.closed = False

            def mount(self, prefix, adapter):
                self.mount_args = (prefix, adapter)

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)
                return upstream

            def close(self):
                self.closed = True

        fake_session = FakeSession()
        with patch.object(self.module, "WORKER_PROXY_ENABLED", True), patch.object(
            self.module.requests,
            "request",
            side_effect=requests.ConnectionError("no IPv6 route"),
        ), patch.object(
            self.module,
            "_worker_ipv4_candidates",
            return_value=["208.111.35.209"],
        ), patch.object(
            self.module.requests,
            "Session",
            return_value=fake_session,
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["runtime"], "worker")
        self.assertFalse(fake_session.trust_env)
        prefix, adapter = fake_session.mount_args
        self.assertEqual(prefix, "https://")
        self.assertEqual(adapter.connect_ip, "208.111.35.209")
        self.assertEqual(adapter.server_hostname, "desktop-6a71m2q.tail2691cd.ts.net")
        call_args, call_kwargs = fake_session.request_args
        self.assertEqual(call_args[:2], ("GET", f"{self.module.WORKER_BASE_URL}/api/health"))
        self.assertEqual(call_kwargs["headers"]["Host"], "desktop-6a71m2q.tail2691cd.ts.net")
        self.assertTrue(fake_session.closed)

    def test_checkpoint_routes_proxy_the_exact_opaque_task_id(self):
        task_id = "A" * 24
        with patch.object(
            self.module,
            "_proxy_worker",
            return_value=({"status": "ready"}, 200),
        ) as proxy:
            get_response = self.client.get(f"/tasks/{task_id}")
            post_response = self.client.post(f"/tasks/{task_id}/resume", json={})

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(proxy.call_args_list[0].args, (f"/api/tasks/{task_id}",))
        self.assertEqual(proxy.call_args_list[1].args, (f"/api/tasks/{task_id}/resume",))
        self.assertTrue(proxy.call_args_list[1].kwargs["stream"])

    def test_analysis_job_routes_proxy_short_requests_without_streaming(self):
        job_id = "J" * 32
        task_id = "T" * 24
        with patch.object(
            self.module,
            "_proxy_worker",
            return_value=({"status": "ready"}, 200),
        ) as proxy:
            start_response = self.client.post("/jobs", json={"keyword": "picture lights"})
            poll_response = self.client.get(f"/jobs/{job_id}/events?after=3")
            resume_response = self.client.post(f"/jobs/tasks/{task_id}/resume", json={})

        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(proxy.call_args_list[0].args, ("/api/jobs",))
        self.assertEqual(proxy.call_args_list[1].args, (f"/api/jobs/{job_id}/events",))
        self.assertEqual(proxy.call_args_list[2].args, (f"/api/jobs/tasks/{task_id}/resume",))
        self.assertFalse(proxy.call_args_list[0].kwargs)
        self.assertFalse(proxy.call_args_list[1].kwargs)
        self.assertFalse(proxy.call_args_list[2].kwargs)

    def test_checkpoint_routes_reject_path_like_ids_before_proxying(self):
        response = self.client.get("/tasks/too-short")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
