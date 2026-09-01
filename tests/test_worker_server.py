import json
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Response

import worker_server


ORIGIN = "https://viralx.metrolabs.mobi"
ROOT = Path(__file__).resolve().parents[1]


class WorkerServerTests(unittest.TestCase):
    def setUp(self):
        self.app = worker_server.create_worker_app({ORIGIN})
        self.client = self.app.test_client()
        self.headers = {"Origin": ORIGIN}

    def test_health_is_cors_enabled_and_never_returns_secret_values(self):
        config = {
            **worker_server.web_app.DEFAULT_CONFIG,
            "rapidapi_key": "server-search-secret",
            "model_api_key": "server-model-secret",
        }
        with patch.object(worker_server.web_app, "load_config", return_value=config), patch.object(
            worker_server.web_app.libtv_auth,
            "status",
            return_value={"state": "disconnected", "connected": False, "cli_installed": False},
        ):
            response = self.client.get("/api/health", headers=self.headers)

        payload = response.get_json()
        serialized = json.dumps(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(response.headers["Access-Control-Allow-Private-Network"], "true")
        self.assertEqual(payload["runtime"], "worker")
        self.assertEqual(payload["service"]["id"], worker_server.WORKER_ID)
        self.assertTrue(payload["configured"]["keyword_search"])
        self.assertTrue(payload["configured"]["model"])
        self.assertNotIn("server-search-secret", serialized)
        self.assertNotIn("server-model-secret", serialized)

    def test_untrusted_origin_and_local_management_routes_are_blocked(self):
        denied = self.client.get("/api/health", headers={"Origin": "https://example.com"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json()["message"], "Origin is not allowed")

        for path in ("/api/settings", "/api/cache/clear", "/api/libtv/auth/start", "/api/export-obsidian"):
            with self.subTest(path=path):
                response = self.client.post(path, headers=self.headers, json={})
                self.assertEqual(response.status_code, 404)

    def test_preflight_allows_byok_but_rejects_machine_control_headers(self):
        allowed = self.client.options("/api/analyze", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Headers": "content-type, x-viralx-model-key, x-viralx-rapidapi-key",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertEqual(allowed.status_code, 204)
        self.assertEqual(allowed.headers["Access-Control-Allow-Private-Network"], "true")

        denied = self.client.options("/api/analyze", headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Headers": "content-type, x-viralx-tk-proxy",
            "Access-Control-Request-Private-Network": "true",
        })
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Private-Network", denied.headers)

    def test_browser_overrides_cannot_select_local_proxy_cookie_or_libtv(self):
        with self.app.test_request_context("/api/health", headers={
            "Origin": ORIGIN,
            "X-ViralX-TK-Proxy": "http://127.0.0.1:7890",
            "X-ViralX-TK-Cookies-Browser": "chrome",
            "X-ViralX-Shot-Engine": "libtv",
            "X-ViralX-Model-Key": "session-model-key",
        }):
            with patch.object(worker_server.web_app, "load_config", return_value={
                **worker_server.web_app.DEFAULT_CONFIG,
                "tk_note_proxy": "",
                "tk_note_cookies_from_browser": "",
                "shot_engine": "shotloom",
            }):
                config = worker_server._request_config()

        self.assertEqual(config["tk_note_proxy"], "")
        self.assertEqual(config["tk_note_cookies_from_browser"], "")
        self.assertEqual(config["shot_engine"], "shotloom")
        self.assertEqual(config["model_api_key"], "session-model-key")

    def test_health_returns_safe_model_configuration_issue(self):
        headers = {
            **self.headers,
            "X-ViralX-Model-Provider": "custom",
            "X-ViralX-Model-Protocol": "openai",
            "X-ViralX-Model-Key": "session-model-secret",
            "X-ViralX-Model-Base-URL": "http://127.0.0.1:8000/v1",
            "X-ViralX-Model-Name": "vision-model",
        }
        response = self.client.get("/api/health", headers=headers)
        payload = response.get_json()
        serialized = json.dumps(payload)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["configured"]["model"])
        self.assertIn("Base URL", payload["configuration_issues"]["model"])
        self.assertNotIn("session-model-secret", serialized)

    def test_only_one_analysis_stream_runs_at_a_time(self):
        def fake_response(**_kwargs):
            return Response(iter([b'{"status":"success","done":true}\n']), mimetype="application/x-ndjson")

        with patch.object(worker_server.web_app, "build_analyze_response", side_effect=fake_response):
            first = self.client.post(
                "/api/analyze",
                headers=self.headers,
                json={"keyword": "picture lights"},
                buffered=False,
            )
            second = self.client.post(
                "/api/analyze",
                headers=self.headers,
                json={"keyword": "picture lights"},
            )
            self.assertEqual(second.status_code, 409)
            first.close()

    def test_launcher_replaces_project_worker_processes_before_starting(self):
        launcher = (ROOT / "start-worker.cmd").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "run-worker.ps1").read_text(encoding="utf-8")
        stop_script = (ROOT / "scripts" / "stop-viralx-worker.ps1").read_text(encoding="utf-8")

        self.assertIn("run-worker.ps1", launcher)
        self.assertIn("stop-viralx-worker.ps1", runner)
        self.assertIn("Get-CimInstance Win32_Process", stop_script)
        self.assertIn("worker_server\\.py", stop_script)
        self.assertIn("$parentExecutable -ieq $venvPython", stop_script)


if __name__ == "__main__":
    unittest.main()
