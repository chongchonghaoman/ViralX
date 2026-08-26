import tempfile
import unittest
from pathlib import Path

from ai_analyzer import AIAnalyzer, OpenAICompatibleAnalyzer
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
        shot_analysis = (
            "00:00 开场展示产品，固定机位，中景；"
            "00:02 操作者触发产品变化，画面亮度改变；"
            "00:05 近景展示产品细节，镜头保持稳定；"
            "00:08 全景展示使用场景与最终效果，背景音乐持续，画面最后停留在成品上。"
        )
        return LibTVAnalysisResult(
            analysis=shot_analysis,
            status="completed",
            project_uuid="project",
            project_url="https://example.com/project",
            result_urls=[],
            evidence={"provider": "libtv", "shot_analysis": shot_analysis},
        )


class FakeModel:
    def __init__(self):
        self.calls = []

    def analyze(self, video_data, video_file_path=None):
        self.calls.append((video_data, video_file_path))
        return "## 最终分析\n证据链完整"


class EmptyEvidenceLibTV(FakeLibTV):
    def analyze(self, video_file_path, user_request=""):
        return LibTVAnalysisResult(
            analysis="完成",
            status="completed",
            evidence={"provider": "libtv", "shot_analysis": "完成"},
        )


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
            self.assertTrue(Path(result["evidence_bundle_path"]).is_file())
            self.assertTrue(Path(result["libtv_evidence_path"]).is_file())
            self.assertTrue(Path(result["raw_model_report_path"]).is_file())

    def test_invalid_libtv_evidence_blocks_the_final_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note",
                status="success",
                video_file=str(video),
                video_id="real-id",
                source_url="https://www.tiktok.com/@a/video/123",
                metadata={"video_id": "real-id"},
            )
            analyzer = AIAnalyzer(
                analysis_mode="pipeline",
                model_provider="deepseek",
                model_api_key="model-key",
                model_base_url="https://api.deepseek.com",
                model_name="deepseek-v4-flash",
                video_collector=FakeCollector(asset),
            )
            fake_model = FakeModel()
            analyzer.libtv = EmptyEvidenceLibTV()
            analyzer.model_analyzer = fake_model

            result = analyzer.analyze_video_script_details(
                {"video_id": "real-id"},
                video_url=asset.source_url,
            )

            self.assertEqual(result["pipeline_status"], "error")
            self.assertEqual(result["model_status"], "blocked")
            self.assertIn("避免无证据猜测", result["analysis"])
            self.assertEqual(fake_model.calls, [])

    def test_deepseek_prompt_and_validator_require_named_evidence_sources(self):
        analyzer = OpenAICompatibleAnalyzer(
            api_key="key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com",
            provider_name="DeepSeek",
            supports_vision=False,
        )
        video_data = {
            "evidence_bundle": {
                "platform_evidence": {
                    "title": "Light painting",
                    "likes": 333800,
                    "comments": 597,
                    "shares": 77200,
                    "views": 4800000,
                    "comments_data": [],
                },
                "tk_note_evidence": {"transcript": "background lyric", "transcript_source": "asr"},
                "libtv_evidence": {"shot_analysis": "00:00 画作未亮；00:03 画作亮起"},
            }
        }

        prompt = analyzer._analyze_text_prompt(video_data)
        self.assertIn("[LIBTV:shot]", prompt)
        self.assertIn("不得推断真实用户反馈", prompt)
        self.assertIn("每条关于原视频的具体事实必须", prompt)
        self.assertTrue(analyzer.grounding_error("这是没有来源的完整分析"))
        self.assertEqual(
            analyzer.grounding_error(
                "标题可见 [META:title]\n数据很高 [META:metrics]\n评论正文未采集 [META:comments]\n"
                "00:00 画作出现 [LIBTV:shot]\n00:03 画作亮起 [LIBTV:shot]",
                video_data,
            ),
            "",
        )
        self.assertIn(
            "真实用户反馈",
            analyzer.grounding_error(
                "标题可见 [META:title]\n数据很高 [META:metrics]\n用户认为价格很值 [META:comments]\n"
                "00:00 画作出现 [LIBTV:shot]\n00:03 画作亮起 [LIBTV:shot]",
                video_data,
            ),
        )


if __name__ == "__main__":
    unittest.main()
