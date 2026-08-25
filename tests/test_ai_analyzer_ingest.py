import tempfile
import unittest
from pathlib import Path

from ai_analyzer import AIAnalyzer
from libtv_analyzer import LibTVAnalysisResult
from video_ingest import VideoAsset


class FakeCollector:
    def __init__(self, asset):
        self.asset = asset
        self.calls = []

    def prepare(self, video_url, video_id, force=False):
        self.calls.append((video_url, video_id, force))
        return self.asset


class FakeLibTV:
    available = True

    def __init__(self):
        self.paths = []

    def is_authenticated(self):
        return True

    def analyze(self, video_file_path, user_request=""):
        self.paths.append((video_file_path, user_request))
        return LibTVAnalysisResult(
            analysis="视频已上传画布",
            status="uploaded",
            project_uuid="project",
            project_url="https://example.com/project",
            result_urls=[],
        )


class AIAnalyzerIngestTests(unittest.TestCase):
    def test_tk_note_asset_is_handed_to_libtv_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note",
                status="reused",
                video_file=str(video),
                video_id="real-id",
                source_url="https://www.tiktok.com/@a/video/123",
                transcript_source="subtitle:download.en.srt",
                asset_manifest=str(Path(tmp) / "assets" / "asset_manifest.json"),
                metadata={"video_id": "real-id", "title": "Real title", "author": "creator"},
            )
            collector = FakeCollector(asset)
            analyzer = AIAnalyzer(
                analysis_mode="libtv",
                video_collector=collector,
            )
            fake_libtv = FakeLibTV()
            analyzer.libtv = fake_libtv
            video_data = {"video_id": "cache-id", "title": "placeholder"}
            result = analyzer.analyze_video_script_details(
                video_data,
                video_url=asset.source_url,
                force_collect=True,
            )

            self.assertEqual(len(collector.calls), 1)
            self.assertEqual(collector.calls[0][-1], True)
            self.assertEqual(fake_libtv.paths, [(str(video), "逐帧拉片")])
            self.assertEqual(result["analysis_provider"], "libtv")
            self.assertEqual(result["tk_note_status"], "reused")
            self.assertEqual(video_data["title"], "Real title")


if __name__ == "__main__":
    unittest.main()
