import json
import os
import unittest
from unittest.mock import patch

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = web_app.app.test_client()

    def test_pages_render_without_config_file(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/settings').status_code, 200)

    def test_direct_douyin_url_uses_libtv_and_reports_missing_key(self):
        config = {**web_app.DEFAULT_CONFIG, 'libtv_access_key': ''}
        with patch.object(web_app, 'load_config', return_value=config), patch.dict(
            os.environ, {'LIBTV_ACCESS_KEY': ''}
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
        progress = payloads[0]
        completed = payloads[-1]

        self.assertEqual(response.mimetype, 'application/x-ndjson')
        self.assertEqual(progress['video']['analysis_provider'], 'libtv')
        self.assertEqual(progress['video']['libtv_status'], 'error')
        self.assertIn('LIBTV_ACCESS_KEY', progress['video']['ai_analysis'])
        self.assertEqual(completed['failed_videos'], 1)

    def test_direct_video_data_preserves_source_url(self):
        url = 'https://www.tiktok.com/@creator/video/123'
        video = web_app.direct_video_data(url)
        self.assertEqual(video['source_url'], url)
        self.assertEqual(video['author'], 'tiktok.com')
        self.assertEqual(len(video['video_id']), 20)


if __name__ == '__main__':
    unittest.main()
