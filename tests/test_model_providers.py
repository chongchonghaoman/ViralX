import unittest
from unittest.mock import patch

from ai_analyzer import AIAnalyzer
from model_providers import normalize_model_config, validate_custom_base_url


class ModelProviderTests(unittest.TestCase):
    def test_legacy_openrouter_config_migrates_to_generic_contract(self):
        config = normalize_model_config({
            "analysis_mode": "openrouter",
            "openrouter_api_key": "legacy-key",
            "openrouter_model": "openrouter/auto",
        })
        self.assertEqual(config["analysis_mode"], "model")
        self.assertEqual(config["model_provider"], "openrouter")
        self.assertEqual(config["model_api_key"], "legacy-key")
        self.assertEqual(config["model_base_url"], "https://openrouter.ai/api/v1")

    def test_local_custom_endpoint_can_use_private_http(self):
        endpoint = validate_custom_base_url(
            "http://127.0.0.1:11434/v1/",
            allow_private=True,
        )
        self.assertEqual(endpoint, "http://127.0.0.1:11434/v1")

    def test_cloud_custom_endpoint_rejects_private_http(self):
        with self.assertRaises(ValueError):
            validate_custom_base_url("http://127.0.0.1:11434/v1", allow_private=False)

    @patch("ai_analyzer.OpenAICompatibleAnalyzer")
    def test_selected_model_provider_is_used_without_minimax_fallback(self, analyzer_class):
        analyzer_class.return_value.analyze.return_value = "## 分析\n完成"
        analyzer = AIAnalyzer(
            analysis_mode="model",
            model_provider="openai",
            model_api_key="model-key",
            model_name="gpt-4.1-mini",
            api_key="legacy-minimax-key",
        )
        result = analyzer.analyze_video_script_details({"video_id": "v1", "title": "demo"})
        self.assertEqual(result["analysis_provider"], "openai")
        self.assertEqual(result["model_status"], "completed")
        analyzer_class.return_value.analyze.assert_called_once()

    def test_missing_selected_model_key_does_not_fall_back_to_minimax(self):
        analyzer = AIAnalyzer(
            analysis_mode="model",
            model_provider="openai",
            model_api_key="",
            model_name="gpt-4.1-mini",
            api_key="legacy-minimax-key",
        )
        result = analyzer.analyze_video_script_details({"video_id": "v1"})
        self.assertEqual(result["analysis_provider"], "openai")
        self.assertEqual(result["model_status"], "error")
        self.assertIn("API Key", result["analysis"])


if __name__ == "__main__":
    unittest.main()
