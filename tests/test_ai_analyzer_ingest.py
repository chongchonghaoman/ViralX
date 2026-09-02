import hashlib
import tempfile
import unittest
from pathlib import Path

from ai_analyzer import AIAnalyzer, OpenAICompatibleAnalyzer, _model_result_error
from shot_analyzers import ShotAnalysisResult
from video_ingest import VideoAsset, VideoIngestError


class FakeCollector:
    def __init__(self, asset):
        self.asset = asset
        self.calls = []

    def prepare(self, video_url, video_id, force=False, media_url=None):
        self.calls.append((video_url, video_id, force, media_url))
        return self.asset


class FakeShotRouter:
    def __init__(self, valid=True):
        self.valid = valid
        self.paths = []

    def analyze(self, video_file_path, user_request=""):
        self.paths.append((video_file_path, user_request))
        if not self.valid:
            return ShotAnalysisResult(
                provider="shotloom", model="vision-test", status="blocked",
                block_reason="镜头视觉模型没有返回有效证据",
            )
        source_hash = hashlib.sha256(Path(video_file_path).read_bytes()).hexdigest()
        shots = [
            {
                "shot_id": "S001", "start_ms": 0, "end_ms": 2000,
                "duration_ms": 2000, "keyframes_ms": [1000],
                "visual_facts": ["产品位于画面中央"], "unknowns": [], "confidence": 0.9,
            },
            {
                "shot_id": "S002", "start_ms": 2000, "end_ms": 4000,
                "duration_ms": 2000, "keyframes_ms": [3000],
                "visual_facts": ["手部触发产品变化"], "unknowns": [], "confidence": 0.9,
            },
        ]
        analysis = (
            "[SHOT:S001] 00:00.000-00:02.000 产品位于画面中央\n"
            "[SHOT:S002] 00:02.000-00:04.000 手部触发产品变化"
        )
        return ShotAnalysisResult(
            provider="shotloom", model="vision-test", status="completed",
            analysis=analysis,
            evidence={
                "schema": "viralx.shot_evidence.v1",
                "provider": "shotloom", "model": "vision-test",
                "source": {"sha256": source_hash, "file_name": "source.mp4"},
                "duration_ms": 4000, "shot_count": 2, "shots": shots,
                "quality": {
                    "timeline_coverage": 1.0, "analyzed_coverage": 1.0,
                    "analyzed_shots": 2, "total_shots": 2,
                },
                "shot_analysis": analysis,
            },
            fallback_chain=[{"provider": "shotloom", "status": "completed", "reason": ""}],
        )


class FakeModel:
    def __init__(self):
        self.calls = []

    def analyze(self, video_data, video_file_path=None):
        self.calls.append((video_data, video_file_path))
        return (
            "## 最终分析\n"
            "标题已采集 [META:title]\n互动数据已采集 [META:metrics]\n"
            "## 用户反馈与受众\n"
            "评论正文未采集，无法判断真实用户诉求 [META:comments]\n"
            "产品居中 [SHOT:S001]\n手部触发变化 [SHOT:S002]\n"
            "适合强调零失败安装体验 [SHOT:S001]"
        )


class FailingCollector:
    def prepare(self, *_args, **_kwargs):
        raise VideoIngestError("download blocked", code="download_failed", task_log="task.jsonl")


class FailingModel:
    def analyze(self, *_args, **_kwargs):
        raise ConnectionError("upstream closed with secret URL")


class AIAnalyzerIngestTests(unittest.TestCase):
    def test_model_failure_detection_only_accepts_explicit_error_sentinels(self):
        grounded_report = (
            "## 证据覆盖\n"
            "适合强调零失败安装体验 [SHOT:S001]\n"
            "标题已采集 [META:title]"
        )
        self.assertEqual(_model_result_error(grounded_report), "")
        self.assertEqual(_model_result_error("Custom 分析失败：HTTP 429"), "Custom 分析失败：HTTP 429")
        self.assertEqual(_model_result_error("分析结果为空"), "分析结果为空")

    def test_collection_failure_marks_downstream_stages_not_run(self):
        events = []
        analyzer = AIAnalyzer(
            analysis_mode="pipeline", model_provider="openai",
            model_api_key="model-key", model_base_url="https://api.openai.com/v1",
            model_name="gpt-4.1-mini", video_collector=FailingCollector(),
            shot_router=FakeShotRouter(),
        )
        result = analyzer.analyze_video_script_details(
            {"video_id": "123"},
            video_url="https://www.tiktok.com/@a/video/123",
            progress_callback=events.append,
        )
        self.assertEqual(result["tk_note_status"], "error")
        self.assertEqual(result["shot_status"], "not_run")
        self.assertEqual(result["model_status"], "not_run")
        self.assertEqual(events[-1]["stage_status"], "error")

    def test_final_model_exception_returns_structured_failure_and_keeps_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note", status="success", video_file=str(video),
                video_id="123", source_url="https://www.tiktok.com/@a/video/123",
                metadata={"video_id": "123"},
            )
            analyzer = AIAnalyzer(
                analysis_mode="pipeline", model_provider="openai",
                model_api_key="model-key", model_base_url="https://api.openai.com/v1",
                model_name="gpt-4.1-mini", video_collector=FakeCollector(asset),
                shot_router=FakeShotRouter(),
            )
            analyzer.model_analyzer = FailingModel()
            result = analyzer.analyze_video_script_details(
                {"video_id": "123"}, video_url=asset.source_url,
            )
            self.assertEqual(result["pipeline_status"], "error")
            self.assertEqual(result["model_status"], "error")
            self.assertEqual(result["evidence_status"], "merged")
            self.assertIn("已保存", result["analysis"])
            self.assertNotIn("secret URL", result["analysis"])

    def test_tk_note_and_shot_evidence_are_handed_to_final_model_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note", status="reused", video_file=str(video),
                video_id="real-id", source_url="https://www.tiktok.com/@a/video/123",
                transcript_source="subtitle:download.en.srt",
                asset_manifest=str(Path(tmp) / "assets" / "asset_manifest.json"),
                metadata={"video_id": "real-id", "title": "Real title", "author": "creator"},
            )
            collector = FakeCollector(asset)
            shot_router = FakeShotRouter()
            analyzer = AIAnalyzer(
                analysis_mode="pipeline", model_provider="openai",
                model_api_key="model-key", model_base_url="https://api.openai.com/v1",
                model_name="gpt-4.1-mini", video_collector=collector,
                shot_router=shot_router,
            )
            fake_model = FakeModel()
            analyzer.model_analyzer = fake_model
            video_data = {"video_id": "cache-id", "title": "placeholder"}
            result = analyzer.analyze_video_script_details(
                video_data,
                video_url=asset.source_url,
                force_collect=True,
                media_url="https://v16-webapp-prime.tiktok.com/video/tos/example.mp4?signature=private",
            )

            self.assertEqual(len(collector.calls), 1)
            self.assertEqual(collector.calls[0][2], True)
            self.assertIn("tiktok.com", collector.calls[0][3])
            self.assertEqual(shot_router.paths[0][0], str(video))
            self.assertEqual(len(fake_model.calls), 1)
            self.assertIsNone(fake_model.calls[0][1])
            bundle = fake_model.calls[0][0]["evidence_bundle"]
            self.assertEqual(bundle["schema"], "viralx.evidence_bundle.v1")
            self.assertEqual(bundle["tk_note_evidence"]["provider"], "tk-note")
            self.assertEqual(bundle["shot_evidence"]["provider"], "shotloom")
            self.assertEqual(result["pipeline_status"], "completed")
            self.assertEqual(result["shot_provider"], "shotloom")
            self.assertEqual(result["tk_note_status"], "reused")
            self.assertEqual(video_data["title"], "Real title")
            self.assertTrue(Path(result["evidence_bundle_path"]).is_file())
            self.assertTrue(Path(result["shot_evidence_path"]).is_file())
            self.assertTrue(Path(result["raw_model_report_path"]).is_file())

    def test_invalid_shot_evidence_blocks_the_final_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note", status="success", video_file=str(video),
                video_id="real-id", source_url="https://www.tiktok.com/@a/video/123",
                metadata={"video_id": "real-id"},
            )
            analyzer = AIAnalyzer(
                analysis_mode="pipeline", model_provider="deepseek",
                model_api_key="model-key", model_base_url="https://api.deepseek.com",
                model_name="deepseek-v4-flash", video_collector=FakeCollector(asset),
                shot_router=FakeShotRouter(valid=False),
            )
            fake_model = FakeModel()
            analyzer.model_analyzer = fake_model
            result = analyzer.analyze_video_script_details(
                {"video_id": "real-id"}, video_url=asset.source_url,
            )

            self.assertEqual(result["pipeline_status"], "blocked")
            self.assertEqual(result["model_status"], "blocked")
            self.assertIn("避免无证据猜测", result["analysis"])
            self.assertEqual(fake_model.calls, [])

    def test_final_checkpoint_retry_skips_collection_and_shot_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "source.mp4"
            video.write_bytes(b"video")
            asset = VideoAsset(
                provider="tk-note", status="reused", video_file=str(video),
                video_id="123", source_url="https://www.tiktok.com/@a/video/123",
                metadata={"video_id": "123", "title": "Picture light"},
            )
            collector = FakeCollector(asset)
            shot_router = FakeShotRouter()
            analyzer = AIAnalyzer(
                analysis_mode="pipeline", model_provider="openai",
                model_api_key="model-key", model_base_url="https://api.openai.com/v1",
                model_name="gpt-4.1-mini", video_collector=collector,
                shot_router=shot_router,
            )
            analyzer.model_analyzer = FailingModel()
            failed = analyzer.analyze_video_script_details(
                {"video_id": "123", "title": "Picture light"}, video_url=asset.source_url,
            )
            self.assertEqual(len(collector.calls), 1)
            self.assertEqual(len(shot_router.paths), 1)

            fake_model = FakeModel()
            analyzer.model_analyzer = fake_model
            resumed = analyzer.resume_final_analysis(
                {"video_id": "123", "title": "Picture light", "evidence_bundle": failed["evidence_bundle"]},
                evidence_bundle_path=failed["evidence_bundle_path"],
            )

            self.assertEqual(len(collector.calls), 1)
            self.assertEqual(len(shot_router.paths), 1)
            self.assertEqual(len(fake_model.calls), 1)
            self.assertIsNone(fake_model.calls[0][1])
            self.assertEqual(resumed["pipeline_status"], "completed")
            self.assertEqual(resumed["retry_scope"], "model-only")

    def test_prompt_and_validator_require_concrete_shot_ids(self):
        analyzer = OpenAICompatibleAnalyzer(
            api_key="key", model="deepseek-v4-flash",
            base_url="https://api.deepseek.com", provider_name="DeepSeek",
            supports_vision=False,
        )
        video_data = {
            "evidence_bundle": {
                "platform_evidence": {
                    "title": "Picture light", "likes": 333800, "comments": 597,
                    "shares": 77200, "views": 4800000, "comments_data": [],
                },
                "tk_note_evidence": {"transcript": "background lyric", "transcript_source": "asr"},
                "shot_evidence": {
                    "shot_count": 2,
                    "shot_analysis": (
                        "[SHOT:S001] 00:00.000 灯具未点亮\n"
                        "[SHOT:S002] 00:03.000 灯具点亮"
                    ),
                },
            }
        }

        prompt = analyzer._analyze_text_prompt(video_data)
        self.assertIn("[SHOT:S001]", prompt)
        self.assertIn("不得推断真实用户反馈", prompt)
        self.assertIn("每条关于原视频的具体事实必须", prompt)
        self.assertTrue(analyzer.grounding_error("这是没有来源的完整分析"))
        valid = (
            "标题可见 [META:title]\n数据很高 [META:metrics]\n"
            "评论正文未采集 [META:comments]\n"
            "00:00 灯具出现 [SHOT:S001]\n00:03 灯具亮起 [SHOT:S002]"
        )
        self.assertEqual(analyzer.grounding_error(valid, video_data), "")
        self.assertIn(
            "真实用户反馈",
            analyzer.grounding_error(
                "标题可见 [META:title]\n数据很高 [META:metrics]\n"
                "用户认为价格很值 [META:comments]\n"
                "00:00 灯具出现 [SHOT:S001]\n00:03 灯具亮起 [SHOT:S002]",
                video_data,
            ),
        )

    def test_feedback_headings_and_missing_data_disclosures_are_not_false_claims(self):
        analyzer = OpenAICompatibleAnalyzer(
            api_key="key", model="qwen3-vl-flash",
            base_url="https://example.com/v1", provider_name="Custom",
        )
        video_data = {
            "evidence_bundle": {
                "platform_evidence": {"comments_data": []},
                "shot_evidence": {"shot_count": 2},
            }
        }
        report = (
            "## 证据覆盖\n标题已采集 [META:title]\n互动数据已采集 [META:metrics]\n"
            "## 用户反馈与受众\n"
            "评论正文未采集，无法判断真实用户反馈 [META:comments]\n"
            "标签受众归类并非直接用户反馈，只是待验证推断 [META:hashtags]\n"
            "产品出现 [SHOT:S001]\n产品点亮 [SHOT:S002]"
        )

        self.assertEqual(analyzer.grounding_error(report, video_data), "")


if __name__ == "__main__":
    unittest.main()
