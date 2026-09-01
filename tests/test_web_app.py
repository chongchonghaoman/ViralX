import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = web_app.app.test_client()

    def test_pages_render_without_config_file(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/settings').status_code, 200)

    def test_legacy_implicit_auto_workflow_migrates_to_fixed_visual_pipeline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / 'config.json'
            config_path.write_text(json.dumps({
                'workflow_version': 1,
                'shot_engine': 'auto',
                'shot_model_source': 'qwen',
            }), encoding='utf-8')
            with patch.object(web_app, 'CONFIG_PATH', config_path), patch.dict(
                web_app.os.environ, {}, clear=True,
            ):
                config = web_app.load_config()

        self.assertEqual(config['workflow_version'], 2)
        self.assertEqual(config['shot_engine'], 'shotloom')
        self.assertEqual(config['shot_model_source'], 'inherit')

    def test_health_returns_readiness_without_secret_values(self):
        with patch.object(web_app.libtv_auth, 'status', return_value={
            'state': 'disconnected', 'connected': False, 'cli_installed': True,
        }):
            response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['runtime'], 'local')
        self.assertEqual(payload['keyword_search_provider'], 'api23+scraper7')
        self.assertEqual(payload['keyword_search_strategy'], 'api23-first-scraper7-fallback')
        self.assertIsInstance(payload['analysis_ready'], bool)
        self.assertTrue(all(isinstance(value, bool) for value in payload['configured'].values()))
        self.assertEqual(payload['libtv']['auth'], 'web')
        self.assertEqual(payload['libtv']['connection_state'], 'disconnected')

    def test_health_reports_but_does_not_mark_a_text_only_model_pipeline_ready(self):
        config = {
            **web_app.DEFAULT_CONFIG,
            'analysis_mode': 'pipeline',
            'model_provider': 'deepseek',
            'model_api_key': 'local-secret',
            'model_base_url': 'https://api.deepseek.com',
            'model_name': 'deepseek-v4-flash',
        }
        with patch.object(web_app, 'load_config', return_value=config), patch.object(
            web_app.libtv_auth,
            'status',
            return_value={'state': 'connected', 'connected': True, 'cli_installed': True},
        ):
            response = self.client.get('/api/health')
        payload = response.get_json()
        self.assertEqual(payload['analysis_provider'], 'deepseek')
        self.assertFalse(payload['analysis_ready'])
        self.assertFalse(payload['configured']['shot'])
        self.assertTrue(payload['configured']['model'])
        self.assertNotIn('local-secret', json.dumps(payload))

    def test_direct_url_skips_discovery_and_reports_shot_block(self):
        config = {
            **web_app.DEFAULT_CONFIG,
            'analysis_mode': 'pipeline',
            'model_provider': 'openai',
            'model_api_key': 'model-key',
            'model_base_url': 'https://api.openai.com/v1',
            'model_name': 'gpt-4.1-mini',
        }
        class FakeAI:
            def __init__(self, **_kwargs):
                pass

            def batch_analyze_streaming(self, videos, **_kwargs):
                yield {
                    **videos[0],
                    'ai_analysis': '镜头证据不可用，最终模型未调用',
                    'analysis_provider': 'pipeline',
                    'pipeline_stage': 'shot-analysis',
                    'pipeline_status': 'blocked',
                    'shot_provider': 'shotloom',
                    'shot_status': 'blocked',
                    'model_status': 'blocked',
                }

        with patch.object(web_app, 'load_config', return_value=config), patch.object(
            web_app, 'AIAnalyzer', FakeAI,
        ):
            response = self.client.post(
                '/api/analyze',
                json={'keyword': 'https://www.douyin.com/video/123456'},
            )
            payloads = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]
        progress = next(payload for payload in payloads if payload.get('video'))
        completed = payloads[-1]

        self.assertEqual(response.mimetype, 'application/x-ndjson')
        self.assertEqual(payloads[0]['stage'], 'discovery')
        self.assertEqual(payloads[0]['stage_status'], 'skipped')
        self.assertEqual(progress['video']['analysis_provider'], 'pipeline')
        self.assertEqual(progress['video']['shot_status'], 'blocked')
        self.assertIn('最终模型未调用', progress['video']['ai_analysis'])
        self.assertEqual(completed['failed_videos'], 1)

    def test_libtv_auth_start_returns_only_safe_browser_state(self):
        state = {
            'state': 'awaiting_browser',
            'connected': False,
            'cli_installed': True,
            'login_url': 'https://www.liblib.tv/zh?callback_url=http%3A%2F%2F127.0.0.1%3A63393%2Fcallback',
            'message': '请在官方网页完成授权',
        }
        with patch.object(web_app.libtv_auth, 'start_login', return_value=state):
            response = self.client.post('/api/libtv/auth/start')
        payload = response.get_json()
        self.assertEqual(payload['state'], 'awaiting_browser')
        self.assertTrue(payload['login_url'].startswith('https://www.liblib.tv/'))
        serialized = json.dumps(payload).lower()
        self.assertNotIn('token', serialized)
        self.assertNotIn('authorization', serialized)

    def test_direct_video_data_preserves_source_url(self):
        url = 'https://www.tiktok.com/@creator/video/123'
        video = web_app.direct_video_data(url)
        self.assertEqual(video['source_url'], url)
        self.assertEqual(video['author'], 'tiktok.com')
        self.assertEqual(len(video['video_id']), 20)

    def test_keyword_search_without_shared_rapidapi_key_returns_actionable_error(self):
        config = {**web_app.DEFAULT_CONFIG, 'rapidapi_key': ''}
        with patch.object(web_app, 'load_config', return_value=config):
            response = self.client.post('/api/analyze', json={'keyword': 'camping light'})

        payloads = [json.loads(line) for line in response.get_data(as_text=True).splitlines() if line.strip()]
        self.assertEqual(payloads[0]['stage'], 'discovery')
        payload = payloads[-1]
        self.assertEqual(payload['status'], 'error')
        self.assertIn('API23 与 Scraper7', payload['message'])
        self.assertIn('RAPIDAPI_KEY', payload['message'])


if __name__ == '__main__':
    unittest.main()
