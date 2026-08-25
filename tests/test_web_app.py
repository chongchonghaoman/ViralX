import json
import unittest
from unittest.mock import patch

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = web_app.app.test_client()

    def test_pages_render_without_config_file(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/settings').status_code, 200)

    def test_health_returns_readiness_without_secret_values(self):
        with patch.object(web_app.libtv_auth, 'status', return_value={
            'state': 'disconnected', 'connected': False, 'cli_installed': True,
        }):
            response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['runtime'], 'local')
        self.assertEqual(payload['keyword_search_provider'], 'api23')
        self.assertIsInstance(payload['analysis_ready'], bool)
        self.assertTrue(all(isinstance(value, bool) for value in payload['configured'].values()))
        self.assertEqual(payload['libtv']['auth'], 'web')
        self.assertEqual(payload['libtv']['connection_state'], 'disconnected')

    def test_health_reports_selected_generic_model_provider(self):
        config = {
            **web_app.DEFAULT_CONFIG,
            'analysis_mode': 'model',
            'model_provider': 'deepseek',
            'model_api_key': 'local-secret',
            'model_base_url': 'https://api.deepseek.com',
            'model_name': 'deepseek-v4-flash',
        }
        with patch.object(web_app, 'load_config', return_value=config):
            response = self.client.get('/api/health')
        payload = response.get_json()
        self.assertEqual(payload['analysis_provider'], 'deepseek')
        self.assertTrue(payload['analysis_ready'])
        self.assertNotIn('local-secret', json.dumps(payload))

    def test_direct_douyin_url_reports_missing_browser_login(self):
        config = {**web_app.DEFAULT_CONFIG, 'analysis_mode': 'libtv'}
        with patch.object(web_app, 'load_config', return_value=config), patch(
            'ai_analyzer.LibTVAnalyzer'
        ) as analyzer_class:
            analyzer_class.return_value.available = True
            analyzer_class.return_value.is_authenticated.return_value = False
            response = self.client.post(
                '/api/analyze',
                json={'keyword': 'https://www.douyin.com/video/123456'},
            )
            payloads = [
                json.loads(line)
                for line in response.get_data(as_text=True).splitlines()
                if line.strip()
            ]
        progress = payloads[0]
        completed = payloads[-1]

        self.assertEqual(response.mimetype, 'application/x-ndjson')
        self.assertEqual(progress['video']['analysis_provider'], 'libtv')
        self.assertEqual(progress['video']['libtv_status'], 'error')
        self.assertIn('连接 LibTV', progress['video']['ai_analysis'])
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

    def test_keyword_search_without_api23_key_returns_actionable_error(self):
        config = {**web_app.DEFAULT_CONFIG, 'rapidapi_key': ''}
        with patch.object(web_app, 'load_config', return_value=config):
            response = self.client.post('/api/analyze', json={'keyword': 'camping light'})

        payload = json.loads(response.get_data(as_text=True).strip())
        self.assertEqual(payload['status'], 'error')
        self.assertIn('API23', payload['message'])
        self.assertIn('RAPIDAPI_KEY', payload['message'])


if __name__ == '__main__':
    unittest.main()
