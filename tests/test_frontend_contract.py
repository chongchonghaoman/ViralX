import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        cls.settings = (ROOT / "templates" / "settings.html").read_text(encoding="utf-8")
        cls.home_js = (ROOT / "static" / "viralx.js").read_text(encoding="utf-8")
        cls.settings_js = (ROOT / "static" / "settings.js").read_text(encoding="utf-8")
        cls.connector_js = (ROOT / "static" / "connector.js").read_text(encoding="utf-8")
        cls.cloud_config_js = (ROOT / "static" / "cloud-config.js").read_text(encoding="utf-8")
        cls.build_js = (ROOT / "scripts" / "build-edgeone.mjs").read_text(encoding="utf-8")

    def assert_named_control(self, html, control_id, name):
        pattern = rf'<(?:input|select|textarea)\b[^>]*\bid="{re.escape(control_id)}"[^>]*\bname="{re.escape(name)}"'
        self.assertRegex(html, pattern)

    def test_home_inputs_keep_api_field_names(self):
        self.assert_named_control(self.home, "keyword", "keyword")
        self.assert_named_control(self.home, "product-name", "product_name")
        self.assert_named_control(self.home, "product-info", "product_info")

    def test_settings_controls_have_stable_names(self):
        controls = {
            "analysis_mode": "analysis_mode",
            "min_likes": "min_likes",
            "rapidapi_key": "rapidapi_key",
            "output_dir": "output_dir",
            "tk_note_asr_backend": "tk_note_asr_backend",
            "tk_note_language": "tk_note_language",
            "tk_note_cookies_from_browser": "tk_note_cookies_from_browser",
            "tk_note_proxy": "tk_note_proxy",
            "tk_note_timeout": "tk_note_timeout",
            "video_cache_dir": "video_cache_dir",
            "model_api_key": "model_api_key",
            "model_name": "model_name",
            "model_protocol": "model_protocol",
            "model_base_url": "model_base_url",
            "new-keyword": "new_keyword",
        }
        for control_id, name in controls.items():
            with self.subTest(control_id=control_id):
                self.assert_named_control(self.settings, control_id, name)
        self.assertNotIn('id="libtv_access_key"', self.settings)
        self.assertNotIn('X-ViralX-LibTV-Key', self.settings_js)

    def test_settings_progressive_disclosure_and_actions_are_preserved(self):
        self.assertIn('value="pipeline"', self.settings)
        self.assertIn('class="pipeline-contract"', self.settings)
        self.assertIn('TK Note', self.settings)
        self.assertIn('LibTV', self.settings)
        self.assertIn('模型 API', self.settings)
        self.assertIn("function syncAnalysisMode()", self.settings_js)
        self.assertLess(self.settings.index('id="save-btn"'), self.settings.index('id="runtime"'))
        for button_id, button_type in (
            ("save-btn", "submit"),
            ("reset-btn", "button"),
            ("clear-session-btn", "button"),
            ("libtv-connect-btn", "button"),
            ("libtv-refresh-btn", "button"),
            ("libtv-disconnect-btn", "button"),
        ):
            self.assertRegex(self.settings, rf'<button\b[^>]*\bid="{button_id}"[^>]*\btype="{button_type}"')
        self.assertIn('data-connection-state="starting"', self.settings)
        self.assertIn("function renderLibTVState", self.settings_js)
        for state in ("connected", "awaiting_browser", "starting", "unavailable", "error", "local_only", "disconnected"):
            self.assertIn(f'{state}:', self.settings_js)

    def test_hosted_libtv_uses_a_fixed_paired_loopback_connector(self):
        for html in (self.home, self.settings):
            self.assertIn("http://127.0.0.1:57231", html)
            self.assertIn("filename='connector.js'", html)
        self.assertIn('const CONNECTOR_ORIGIN = "http://127.0.0.1:57231"', self.connector_js)
        self.assertIn('const PAIRING_FRAGMENT = "viralx-connector"', self.connector_js)
        self.assertIn('targetAddressSpace: "loopback"', self.connector_js)
        self.assertIn('"loopback-network"', self.connector_js)
        self.assertIn('X-ViralX-Connector-Token', self.connector_js)
        self.assertIn("window.sessionStorage.setItem(TOKEN_KEY", self.connector_js)
        self.assertIn("window.history.replaceState", self.connector_js)
        self.assertNotIn("console.log", self.connector_js)
        self.assertIn('(read().analysis_mode || "pipeline") === "pipeline"', self.cloud_config_js)
        self.assertIn("CONNECTOR_REQUEST_HEADERS", self.cloud_config_js)
        self.assertIn("headers: connectorHeaders", self.cloud_config_js)
        connector_header_block = self.cloud_config_js.split(
            "const CONNECTOR_REQUEST_HEADERS", 1
        )[1].split("])", 1)[0]
        self.assertIn("x-viralx-model-key", connector_header_block.lower())
        self.assertIn("x-viralx-model-base-url", connector_header_block.lower())
        self.assertIn("connector_missing:", self.settings_js)
        self.assertIn("pairing_required:", self.settings_js)
        self.assertIn('join(projectRoot, "static", "connector.js")', self.build_js)

    def test_home_uses_explicit_five_stage_pipeline_events(self):
        for stage in ("discovery", "collection", "shot-analysis", "evidence-merge", "final-analysis"):
            self.assertIn(f'data-stage="{stage}"', self.home)
        self.assertIn("function setPipelineStage", self.home_js)
        self.assertIn("if (data.stage) setPipelineStage", self.home_js)

    def test_field_validation_targets_the_relevant_control(self):
        self.assertIn("class SettingsValidationError", self.settings_js)
        self.assertIn('SettingsValidationError("model_api_key"', self.settings_js)
        self.assertIn('SettingsValidationError("model_name"', self.settings_js)
        self.assertIn('SettingsValidationError("model_base_url"', self.settings_js)
        self.assertIn('control.setAttribute("aria-invalid", "true")', self.settings_js)
        self.assertIn('control.setAttribute("aria-errormessage", error.id)', self.settings_js)

    def test_zero_minimum_likes_is_preserved(self):
        self.assertIn("const parsedMinLikes = Number.parseInt", self.settings_js)
        self.assertIn("Number.isFinite(parsedMinLikes)", self.settings_js)
        self.assertNotIn('Number.parseInt(byId("min_likes").value, 10) || DEFAULTS.min_likes', self.settings_js)

    def test_report_markdown_is_version_pinned_and_sanitized(self):
        self.assertIn("marked@15.0.12/marked.min.js", self.home)
        self.assertIn("integrity=\"sha384-", self.home)
        self.assertIn('http-equiv="Content-Security-Policy"', self.home)
        self.assertIn("object-src 'none'", self.home)
        self.assertIn('http-equiv="Content-Security-Policy"', self.settings)
        self.assertIn("function sanitizeReportHtml(html)", self.home_js)
        self.assertIn("REPORT_ALLOWED_TAGS", self.home_js)
        self.assertIn("sanitizeReportHtml(rendered)", self.home_js)
        self.assertNotIn("innerHTML = window.marked", self.home_js)

    def test_unready_runtime_routes_to_the_correct_settings_page(self):
        self.assertIn('dataset.deployment === "edgeone"', self.home_js)
        self.assertIn('return runtimeMode === "edgeone" || deployedToEdgeOne ? "/settings.html" : "/settings"', self.home_js)
        self.assertIn("function syncPrimaryActions()", self.home_js)
        self.assertIn("function handleAnalyzeAction(refresh = false)", self.home_js)
        self.assertIn("data-runtime-action", self.home)
        self.assertIn('data-deployment="edgeone"', self.build_js)

    def test_responsive_hero_assets_are_built(self):
        png = ROOT / "static" / "assets" / "viralx-signal-orbit.png"
        for width in (640, 1024):
            asset = ROOT / "static" / "assets" / f"viralx-signal-orbit-{width}.webp"
            with self.subTest(width=width):
                self.assertTrue(asset.is_file())
                self.assertLess(asset.stat().st_size, png.stat().st_size)
                self.assertIn(asset.name, self.home)
                self.assertIn(asset.name, self.build_js)


if __name__ == "__main__":
    unittest.main()
