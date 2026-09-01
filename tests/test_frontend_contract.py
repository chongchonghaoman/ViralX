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
        cls.home_css = (ROOT / "static" / "viralx.css").read_text(encoding="utf-8")
        cls.settings_js = (ROOT / "static" / "settings.js").read_text(encoding="utf-8")
        cls.runtime_config_js = (ROOT / "static" / "runtime-config.js").read_text(encoding="utf-8")
        cls.cloud_config_js = (ROOT / "static" / "cloud-config.js").read_text(encoding="utf-8")
        cls.build_js = (ROOT / "scripts" / "build-edgeone.mjs").read_text(encoding="utf-8")
        cls.deploy_guard_js = (ROOT / "scripts" / "require-public-worker.mjs").read_text(encoding="utf-8")
        cls.package_json = (ROOT / "package.json").read_text(encoding="utf-8")

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
            "shot_model_source": "shot_model_source",
            "shot_model_api_key": "shot_model_api_key",
            "shot_model_base_url": "shot_model_base_url",
            "shot_model_name": "shot_model_name",
            "shot_scene_threshold": "shot_scene_threshold",
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
        self.assertIn('ShotLoom Core', self.settings)
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
        self.assertIn("function renderShotEngine", self.settings_js)
        for mode in ("auto", "shotloom", "libtv", "skip"):
            self.assertIn(f'name="shot_engine" value="{mode}"', self.settings)
        for state in ("connected", "awaiting_browser", "starting", "unavailable", "error", "local_only", "disconnected"):
            self.assertIn(f'{state}:', self.settings_js)

    def test_settings_has_a_two_key_quick_start_without_removing_advanced_controls(self):
        self.assertIn('name="quick_mode" value="full"', self.settings)
        self.assertIn('name="quick_mode" value="evidence"', self.settings)
        self.assertIn('name="model_provider" value="qwen"', self.settings)
        self.assertIn("Qwen3-VL Flash", self.settings)
        self.assertIn('class="settings-section settings-section--advanced"', self.settings)
        self.assertIn("function selectQuickMode", self.settings_js)
        self.assertIn('model_provider: "qwen"', self.settings_js)
        self.assertIn('class="quick-search-card"', self.settings)
        self.assertIn('SettingsValidationError("rapidapi_key"', self.settings_js)
        self.assertNotIn("可选 · 视频直链不需要搜索 Key", self.settings)
        self.assertEqual(self.settings.count('id="rapidapi_key"'), 1)
        self.assertIn("TikTok 多源发现", self.settings)
        self.assertIn("自动换源", self.settings)

    def test_settings_explains_the_fixed_collection_and_visual_evidence_contract(self):
        self.assertIn("TK Note 采集故障处理", self.settings)
        self.assertIn("每条搜索候选都会交给 TK Note", self.settings)
        self.assertIn("ShotLoom 切镜", self.settings)
        self.assertIn('id="shot-model-inherited-name"', self.settings)
        self.assertIn("标准流程 · 推荐", self.settings)
        self.assertIn("视觉模型与接口", self.settings)
        self.assertIn("同一模型负责逐镜识别与证据终审", self.settings)
        self.assertIn('workflow_version: 2', self.settings_js)
        self.assertIn('shot_engine: "shotloom"', self.settings_js)
        self.assertIn('shot_model_source: "inherit"', self.settings_js)

    def test_quick_model_card_exposes_a_complete_customizable_visual_model_contract(self):
        quick_card_start = self.settings.index('class="quick-model-card"')
        quick_card_end = self.settings.index('class="pipeline-peek"', quick_card_start)
        quick_card = self.settings[quick_card_start:quick_card_end]
        for control_id in ("model_base_url", "model_api_key", "model_name"):
            self.assertIn(f'id="{control_id}"', quick_card)
        self.assertIn("KEY 02 · 推荐模型", quick_card)
        self.assertIn("所选模型需要具备视频识别能力", quick_card)
        self.assertIn("第三方兼容地址", quick_card)
        self.assertIn("function promoteEditedEndpointToCustom", self.settings_js)
        self.assertIn('selectedProvider = "custom"', self.settings_js)

    def test_hosted_site_uses_a_remote_worker_instead_of_visitor_loopback(self):
        for html in (self.home, self.settings):
            self.assertNotIn("http://127.0.0.1:57231", html)
            self.assertNotIn("filename='connector.js'", html)
            self.assertIn("filename='runtime-config.js'", html)
        self.assertIn('mode: "same-origin"', self.runtime_config_js)
        self.assertIn("REMOTE_WORKER_PATHS", self.cloud_config_js)
        self.assertIn("function workerUrl", self.cloud_config_js)
        self.assertIn("apiBaseUrl", self.build_js)
        self.assertIn('"remote-worker"', self.build_js)
        self.assertIn('"same-origin-worker"', self.build_js)
        self.assertIn('["remote-worker", "same-origin-worker"]', self.cloud_config_js)
        self.assertNotIn('join(projectRoot, "static", "connector.js")', self.build_js)
        self.assertNotIn("ViralXConnector", self.home_js)
        self.assertIn("const HEALTH_TIMEOUT_MS = 15000;", self.cloud_config_js)
        self.assertIn("new AbortController()", self.cloud_config_js)
        self.assertIn("const REMOTE_WORKER_HEADER_FIELDS = new Set", self.cloud_config_js)
        self.assertIn("headers({ remoteWorker })", self.cloud_config_js)
        self.assertIn("if (remoteWorker && !REMOTE_WORKER_HEADER_FIELDS.has(field)) return;", self.cloud_config_js)
        for field in ("min_likes", "rapidapi_key", "model_provider", "model_protocol", "model_api_key", "model_base_url", "model_name", "shot_scene_threshold"):
            self.assertIn(f'    "{field}",', self.cloud_config_js)
        self.assertIn("无法连接实时 Worker", self.settings_js)

    def test_home_readiness_distinguishes_keyword_search_from_direct_video(self):
        self.assertIn("let runtimeAnalysisReady = false;", self.home_js)
        self.assertIn("let runtimeSearchReady = false;", self.home_js)
        self.assertIn("function isDirectVideoSource(value)", self.home_js)
        self.assertIn("if (!isDirectVideoSource(source) && !runtimeSearchReady)", self.home_js)
        self.assertIn("直链分析已经就绪", self.home_js)
        self.assertNotIn("Boolean(data.analysis_ready && data.configured?.keyword_search)", self.home_js)

    def test_motion_is_concentrated_instead_of_repeating_on_every_story_section(self):
        self.assertIn('document.querySelectorAll("[data-motion]")', self.home_js)
        self.assertNotIn('window.gsap.utils.toArray(".story-section")', self.home_js)
        self.assertIn('window.gsap.from(".waveform i"', self.home_js)

    def test_hosted_settings_hide_links_to_owner_only_sections(self):
        self.assertIn('<a href="#advanced" data-server-owner-only>高级设置</a>', self.settings)
        self.assertIn('<a href="#models" data-server-owner-only>使用其他预设</a>', self.settings)
        self.assertIn('<div data-server-owner-only><span>调整</span>', self.settings)

    def test_home_uses_explicit_five_stage_pipeline_events(self):
        for stage in ("discovery", "collection", "shot-analysis", "evidence-merge", "final-analysis"):
            self.assertIn(f'data-stage="{stage}"', self.home)
        self.assertIn("function setPipelineStage", self.home_js)
        self.assertIn("if (data.stage) setPipelineStage", self.home_js)
        self.assertIn('acquisitionProvider === "tk-note" ? "TK Note"', self.home_js)
        self.assertIn('failed: "采集失败"', self.home_js)
        self.assertIn('notRun: "未运行"', self.home_js)
        self.assertIn('unknown: "状态未知"', self.home_js)
        self.assertIn('["completed", "complete", "success", "reused"]', self.home_js)
        self.assertNotIn(': `${shotProvider} · 已完成`', self.home_js)
        self.assertIn('pipelineFailed ? "查看失败详情" : "打开最终分析"', self.home_js)
        self.assertIn('status || "not_run"', self.home_js)
        self.assertIn(".provider-badge.not_run", self.home_css)
        self.assertIn('class="video-card__error"', self.home_js)

    def test_subscription_failures_render_safe_actionable_rapidapi_links(self):
        self.assertIn("function renderSubscriptionRecovery", self.home_js)
        self.assertIn("payload?.subscription_links", self.home_js)
        self.assertIn('url.hostname === "rapidapi.com"', self.home_js)
        self.assertIn("!url.username", self.home_js)
        self.assertIn("!url.password", self.home_js)
        self.assertIn('url.port === "443"', self.home_js)
        self.assertIn('link.target = "_blank"', self.home_js)
        self.assertIn('link.rel = "noopener noreferrer"', self.home_js)
        self.assertIn("subscription-link-list", self.home_css)
        self.assertIn("min-height: 2.75rem", self.home_css)

    def test_edgeone_builder_rewrites_versioned_subscription_assets(self):
        home_versions = set(re.findall(r"url_for\('static', filename='[^']+', v='([^']+)'\)", self.home))
        settings_versions = set(re.findall(r"url_for\('static', filename='[^']+', v='([^']+)'\)", self.settings))
        self.assertEqual(home_versions, {"1.1.7"})
        self.assertEqual(settings_versions, home_versions)
        self.assertIn("const renderStaticUrls", self.build_js)
        self.assertIn('`/static/${filename}${version ? `?v=${version}` : ""}`', self.build_js)
        self.assertNotIn("const assetVersion", self.build_js)

    def test_edgeone_build_carries_the_evidence_contract_module(self):
        self.assertIn('"evidence_contract.py",', self.build_js)

    def test_evidence_story_does_not_fragment_on_ultrawide_screens(self):
        self.assertIn('id="evidence-title">从看见视频，到看见结构。</h2>', self.home)
        self.assertIn("@media (min-width: 100rem)", self.home_css)
        self.assertIn("124rem", self.home_css)
        self.assertIn("grid-template-columns: minmax(36rem, 0.76fr) minmax(64rem, 1.34fr);", self.home_css)
        self.assertIn("background: var(--color-ink);", self.home_css)

    def test_production_deploy_cannot_silently_fall_back_to_edgeone_proxying(self):
        self.assertIn("VIRALX_PUBLIC_API_BASE_URL", self.deploy_guard_js)
        self.assertIn("if (!rawUrl)", self.deploy_guard_js)
        self.assertIn("node scripts/require-public-worker.mjs", self.package_json)

    def test_gateway_timeout_explains_recovery_path(self):
        self.assertIn("responseError.status = response.status", self.home_js)
        self.assertIn("长任务被中转网关提前截断", self.home_js)
        self.assertNotIn("请稍后重试后重试", self.home_js)

    def test_stream_protocol_deduplicates_results_and_requires_a_terminal_event(self):
        self.assertIn('async function consumeAnalysisStream(requestBody, onPayload, endpoint = "/api/analyze")', self.home_js)
        self.assertIn("if (terminal) return;", self.home_js)
        self.assertIn("function stableVideoKey(video)", self.home_js)
        self.assertIn("const resultCards = new Map();", self.home_js)
        self.assertIn("resultCards.set(key, card);", self.home_js)
        self.assertNotIn("received += 1", self.home_js)
        self.assertIn("分析流提前结束，未收到完成信号", self.home_js)
        self.assertIn("分析流包含无法解析的数据，结果可能不完整", self.home_js)
        self.assertIn("loading.hidden = true;", self.home_js)

    def test_failed_final_analysis_exposes_a_single_checkpoint_recovery_action(self):
        self.assertIn('video.resumable_stage === "final-analysis"', self.home_js)
        self.assertIn('video.retry_scope === "model-only"', self.home_js)
        self.assertIn('"仅重试终审"', self.home_js)
        self.assertIn("不会重新下载或切镜", self.home_js)
        self.assertIn("function checkpointExpiryLabel(value)", self.home_js)
        self.assertIn('/api/tasks/${encodeURIComponent(video.task_id)}/resume', self.home_js)
        self.assertIn('target.pathname.startsWith("/api/tasks/")', self.cloud_config_js)

    def test_failed_video_has_an_in_place_retry_and_runtime_self_recovers(self):
        self.assertIn('class="retry-video-btn"', self.home_js)
        self.assertIn("重试这条视频", self.home_js)
        self.assertIn("async function retryVideo(video, card, button)", self.home_js)
        self.assertIn('const refresh = !finalOnly && video.pipeline_stage === "collection";', self.home_js)
        self.assertIn("card.replaceWith(replacement);", self.home_js)
        self.assertIn("RUNTIME_RECHECK_MS = 30000", self.home_js)
        self.assertIn('window.setInterval(() => checkRuntime({ silent: true })', self.home_js)
        self.assertIn('document.addEventListener("visibilitychange"', self.home_js)
        self.assertIn(".retry-video-btn", self.home_css)

    def test_analysis_results_are_adjacent_and_revealed_once(self):
        self.assertIn('id="results-zone"', self.home)
        self.assertLess(self.home.index('id="results-zone"'), self.home.index('class="signal-strip"'))
        self.assertIn('id="results" aria-busy="false"', self.home)
        self.assertIn("let resultRevealHandled = false;", self.home_js)
        self.assertIn('function revealFirstResult()', self.home_js)
        self.assertIn('revealSection("results-zone")', self.home_js)
        self.assertIn('byId("results")?.setAttribute("aria-busy"', self.home_js)

    def test_tk_note_network_controls_remain_available_to_local_owner(self):
        cookie_field = self.settings.split('id="tk_note_cookies_from_browser"', 1)[0].rsplit('<div class="settings-field"', 1)[-1]
        proxy_field = self.settings.split('id="tk_note_proxy"', 1)[0].rsplit('<div class="settings-field"', 1)[-1]
        self.assertNotIn("data-local-only", cookie_field)
        self.assertNotIn("data-local-only", proxy_field)
        self.assertIn('tk_note_timeout: 1800', self.settings_js)
        self.assertIn('Math.min(Math.max(settings.tk_note_timeout, 120), 7200)', self.settings_js)
        self.assertIn('SettingsValidationError("tk_note_proxy"', self.settings_js)

    def test_field_validation_targets_the_relevant_control(self):
        self.assertIn("class SettingsValidationError", self.settings_js)
        self.assertIn('SettingsValidationError("model_api_key"', self.settings_js)
        self.assertIn('SettingsValidationError("model_name"', self.settings_js)
        self.assertIn('SettingsValidationError("model_base_url"', self.settings_js)
        self.assertIn('SettingsValidationError("shot_model_source"', self.settings_js)
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

    def test_unready_runtime_stays_on_analysis_page_and_explains_offline_state(self):
        self.assertIn("function syncPrimaryActions()", self.home_js)
        self.assertIn("function primaryActionLabel(navigation = false)", self.home_js)
        self.assertIn('offline: "实时分析暂离线"', self.home_js)
        self.assertIn('server_config_missing: "分析服务配置中"', self.home_js)
        self.assertIn('action.href = "#analysis-studio"', self.home_js)
        self.assertNotIn("window.location.assign(settingsUrl())", self.home_js)
        self.assertNotIn("Connector", self.home_js)
        self.assertIn("function handleAnalyzeAction(refresh = false)", self.home_js)
        self.assertIn("data-runtime-action", self.home)
        self.assertIn('data-deployment="edgeone"', self.build_js)

    def test_hosted_settings_enter_connecting_mode_before_remote_health_returns(self):
        connecting = self.settings_js.index('runtimeMode = "connecting";')
        load = self.settings_js.rindex("loadSettings();")
        self.assertLess(connecting, load)
        self.assertIn('updateRuntimeNote({ runtime: "connecting", configured: {} });', self.settings_js)

    def test_hosted_settings_verify_worker_acceptance_before_same_tab_return(self):
        self.assertIn('if (!healthResponse.ok) throw new Error(`Worker 返回 HTTP ${healthResponse.status}`);', self.settings_js)
        self.assertIn('if (settings.shot_engine !== "skip" && !serverConfigured.model)', self.settings_js)
        self.assertIn('lastHealth.configuration_issues?.model', self.settings_js)
        self.assertIn('window.location.assign("/#analysis-studio")', self.settings_js)
        self.assertIn("新标签页不会共享 Key", self.settings_js)
        self.assertIn("新标签页不会共享 Key", self.home_js)

    def test_responsive_hero_assets_are_built(self):
        png = ROOT / "static" / "assets" / "viralx-signal-orbit.png"
        for width in (640, 1024):
            asset = ROOT / "static" / "assets" / f"viralx-signal-orbit-{width}.webp"
            with self.subTest(width=width):
                self.assertTrue(asset.is_file())
                self.assertLess(asset.stat().st_size, png.stat().st_size)
                self.assertIn(asset.name, self.home)
        self.assertIn("for (const width of [640, 1024])", self.build_js)
        self.assertIn("`viralx-signal-orbit-${width}.webp`", self.build_js)


if __name__ == "__main__":
    unittest.main()
