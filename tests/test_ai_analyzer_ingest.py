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
            analysis="00:00 开场展示产品",
            status="completed",
            project_uuid="project",
            project_url="https://example.com/project",
            result_urls=[],
            evidence={"provider": "libtv", "shot_analysis": "00:00 开场展示产品"},
        )


class FakeModel:
    def __init__(self):
        self.calls = []

    def analyze(self, video_data, video_file_path=None):
        self.calls.append((video_data, video_file_path))
        return "## 最终分析\n证据链完整"


class AIAnalyzerIngestTests(unittest.TestCase):
    def test_tk_note_and_libtv_evidence_are_handed_to_final_model_once(self):
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
                analysis_mode="pipeline",
                model_provider="openai",
                model_api_key="model-key",
                model_base_url="https://api.openai.com/v1",
                model_name="gpt-4.1-mini",
                video_collector=collector,
            )
            fake_libtv = FakeLibTV()
            fake_model = FakeModel()
            analyzer.libtv = fake_libtv
            analyzer.model_analyzer = fake_model
            video_data = {"video_id": "cache-id", "title": "placeholder"}
            result = analyzer.analyze_video_script_details(
                video_data,
                video_url=asset.source_url,
                force_collect=True,
            )

            self.assertEqual(len(collector.calls), 1)
            self.assertEqual(collector.calls[0][-1], True)
            self.assertEqual(fake_libtv.paths, [(str(video), "逐镜头拉片并输出结构化证据")])
            self.assertEqual(len(fake_model.calls), 1)
            self.assertEqual(fake_model.calls[0][1], str(video))
            bundle = fake_model.calls[0][0]["evidence_bundle"]
            self.assertEqual(bundle["schema"], "viralx.evidence.v1")
            self.assertEqual(bundle["tk_note_evidence"]["provider"], "tk-note")
            self.assertIn("00:00", bundle["libtv_evidence"]["shot_analysis"])
            self.assertEqual(result["analysis_provider"], "openai")
            self.assertEqual(result["pipeline_status"], "completed")
            self.assertEqual(result["tk_note_status"], "reused")
            self.assertEqual(video_data["title"], "Real title")


if __name__ == "__main__":
    unittest.main()
