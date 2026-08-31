import unittest
from unittest.mock import patch

from ai_analyzer import AIAnalyzer
from model_providers import MODEL_PROVIDER_PRESETS, normalize_model_config, validate_custom_base_url


class ModelProviderTests(unittest.TestCase):
    def test_qwen3_vl_flash_is_the_new_user_default(self):
        config = normalize_model_config({})
        self.assertEqual(config["model_provider"], "qwen")
        self.assertEqual(config["model_name"], "qwen3-vl-flash")
        self.assertEqual(
            config["model_base_url"],
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertTrue(MODEL_PROVIDER_PRESETS["qwen"]["vision"])

    def test_legacy_openrouter_config_migrates_to_generic_contract(self):
        config = normalize_model_config({
            "analysis_mode": "openrouter",
            "openrouter_api_key": "legacy-key",
            "openrouter_model": "openrouter/auto",
        })
        self.assertEqual(config["analysis_mode"], "pipeline")
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
    def test_selected_final_model_is_initialized_without_minimax_fallback(self, analyzer_class):
        analyzer = AIAnalyzer(
            analysis_mode="pipeline",
            model_provider="openai",
            model_api_key="model-key",
            model_name="gpt-4.1-mini",
            api_key="legacy-minimax-key",
        )
        self.assertEqual(analyzer.model_provider, "openai")
        self.assertIs(analyzer.model_analyzer, analyzer_class.return_value)
        analyzer_class.assert_called_once()

    def test_missing_selected_model_key_does_not_fall_back_to_minimax(self):
        analyzer = AIAnalyzer(
            analysis_mode="pipeline",
            model_provider="openai",
            model_api_key="",
            model_name="gpt-4.1-mini",
            api_key="legacy-minimax-key",
        )
        self.assertEqual(analyzer.model_provider, "openai")
        self.assertIsNone(analyzer.model_analyzer)
        self.assertNotEqual(analyzer.model_api_key, "legacy-minimax-key")


if __name__ == "__main__":
    unittest.main()
