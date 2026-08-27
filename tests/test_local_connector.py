import json
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from flask import jsonify

import local_connector


TRUSTED_ORIGIN = "https://viralx.metrolabs.mobi"


class LocalConnectorTests(unittest.TestCase):
    def setUp(self):
        self.broker = local_connector.PairingBroker(pairing_ttl=60, session_ttl=60)
        self.app, _ = local_connector.create_connector_app(
            broker=self.broker,
            origin_allowlist={TRUSTED_ORIGIN},
        )
        self.client = self.app.test_client()
        self.origin_headers = {"Origin": TRUSTED_ORIGIN}

    def pair(self):
        secret = self.broker.issue_pairing_secret()
        response = self.client.post(
            "/connector/v1/pair",
            json={"pairing_secret": secret},
            headers=self.origin_headers,
        )
        self.assertEqual(response.status_code, 200)
        return secret, response.get_json()["session_token"]

    def authenticated_headers(self, token):
        return {**self.origin_headers, "X-ViralX-Connector-Token": token}

    def test_untrusted_origin_is_rejected_without_cors_opt_in(self):
        response = self.client.get(
            "/connector/v1/status",
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_preflight_allows_exact_origin_and_private_network(self):
        response = self.client.open(
            "/connector/v1/analyze",
            method="OPTIONS",
            headers={
                "Origin": TRUSTED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, x-viralx-connector-token, x-viralx-model-key, x-viralx-model-name, x-viralx-shot-engine, x-viralx-shot-model-key",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], TRUSTED_ORIGIN)
        self.assertEqual(response.headers["Access-Control-Allow-Private-Network"], "true")
        self.assertIn("Origin", response.headers["Vary"])

    def test_preflight_rejects_unknown_headers(self):
        response = self.client.open(
            "/connector/v1/analyze",
            method="OPTIONS",
            headers={
                "Origin": TRUSTED_ORIGIN,
                "Access-Control-Request-Headers": "x-not-allowed",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_local_launcher_can_request_a_fresh_pairing_link(self):
        response = self.client.post(
            local_connector.LOCAL_PAIRING_PATH,
            json={"site": TRUSTED_ORIGIN},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        pairing_url = response.get_json()["pairing_url"]
        parsed = urlsplit(pairing_url)
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}", TRUSTED_ORIGIN)
        self.assertEqual(parsed.path, "/settings.html")
        secret = parse_qs(parsed.fragment)["viralx-connector"][0]

        paired = self.client.post(
            "/connector/v1/pair",
            json={"pairing_secret": secret},
            headers=self.origin_headers,
        )
        self.assertEqual(paired.status_code, 200)

    def test_browser_origin_cannot_issue_pairing_links(self):
        response = self.client.post(
            local_connector.LOCAL_PAIRING_PATH,
            json={"site": TRUSTED_ORIGIN},
            headers=self.origin_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_local_launcher_can_request_graceful_replacement(self):
        stopped = threading.Event()
        self.app.config["VIRALX_SHUTDOWN_CALLBACK"] = stopped.set
        response = self.client.post(
            local_connector.LOCAL_SHUTDOWN_PATH,
            json={},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"], "shutting_down")
        self.assertTrue(stopped.wait(1.0))

    def test_browser_origin_cannot_shutdown_connector(self):
        callback = Mock()
        self.app.config["VIRALX_SHUTDOWN_CALLBACK"] = callback
        response = self.client.post(
            local_connector.LOCAL_SHUTDOWN_PATH,
            json={},
            headers=self.origin_headers,
        )
        self.assertEqual(response.status_code, 403)
        callback.assert_not_called()

    def test_pairing_secret_is_one_use_and_session_is_not_echoed_by_status(self):
        secret, token = self.pair()
        replay = self.client.post(
            "/connector/v1/pair",
            json={"pairing_secret": secret},
            headers=self.origin_headers,
        )
        self.assertEqual(replay.status_code, 401)

        with patch.object(local_connector.web_app.libtv_auth, "status", return_value={
            "state": "connected", "connected": True, "cli_installed": True,
        }):
            response = self.client.get(
                "/connector/v1/status",
                headers=self.authenticated_headers(token),
            )
        payload = response.get_json()
        self.assertTrue(payload["paired"])
        self.assertTrue(payload["libtv"]["connected"])
        self.assertIn("installed", payload["shotloom_core"])
        self.assertNotIn(token, json.dumps(payload))
        self.assertNotIn(secret, json.dumps(payload))

    def test_libtv_and_analysis_routes_require_a_paired_session(self):
        for method, path in (
            ("get", "/connector/v1/libtv/status"),
            ("post", "/connector/v1/libtv/login/start"),
            ("post", "/connector/v1/libtv/logout"),
            ("post", "/connector/v1/analyze"),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(path, headers=self.origin_headers)
                self.assertEqual(response.status_code, 401)

    def test_connector_analysis_forces_pipeline_and_transfers_session_model_config(self):
        _, token = self.pair()
        captured = {}

        def fake_response(**kwargs):
            captured.update(kwargs)
            return jsonify({"status": "ok"})

        with patch.object(local_connector.web_app, "load_config", return_value={
            **local_connector.web_app.DEFAULT_CONFIG,
            "analysis_mode": "model",
        }), patch.object(local_connector.web_app, "build_analyze_response", side_effect=fake_response):
            response = self.client.post(
                "/connector/v1/analyze",
                json={"keyword": "https://www.tiktok.com/@creator/video/123"},
                headers={
                    **self.authenticated_headers(token),
                    "X-ViralX-Analysis-Mode": "model",
                    "X-ViralX-RapidAPI-Key": "session-search-key",
                    "X-ViralX-TK-ASR": "auto",
                    "X-ViralX-TK-Timeout": "180",
                    "X-ViralX-Model-Provider": "openai",
                    "X-ViralX-Model-Protocol": "openai",
                    "X-ViralX-Model-Key": "session-model-key",
                    "X-ViralX-Model-Base-URL": "https://api.openai.com/v1",
                    "X-ViralX-Model-Name": "gpt-4.1-mini",
                    "X-ViralX-Shot-Engine": "shotloom",
                    "X-ViralX-Shot-Model-Source": "custom",
                    "X-ViralX-Shot-Model-Key": "session-shot-key",
                    "X-ViralX-Shot-Model-Base-URL": "https://vision.example.com/v1",
                    "X-ViralX-Shot-Model-Name": "vision-model",
                    "X-ViralX-Shot-Threshold": "31",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured["max_videos"], local_connector.web_app.MAX_ANALYZE_VIDEOS)
        self.assertEqual(captured["config_override"]["analysis_mode"], "pipeline")
        self.assertEqual(captured["config_override"]["rapidapi_key"], "session-search-key")
        self.assertEqual(captured["config_override"]["tk_note_timeout"], 180)
        self.assertEqual(captured["config_override"]["model_api_key"], "session-model-key")
        self.assertEqual(captured["config_override"]["model_name"], "gpt-4.1-mini")
        self.assertEqual(captured["config_override"]["shot_engine"], "shotloom")
        self.assertEqual(captured["config_override"]["shot_model_api_key"], "session-shot-key")
        self.assertEqual(captured["config_override"]["shot_scene_threshold"], 31)


if __name__ == "__main__":
    unittest.main()
