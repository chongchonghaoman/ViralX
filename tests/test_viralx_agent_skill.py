import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_SCRIPTS = ROOT / ".agents" / "skills" / "viralx-agent" / "scripts"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SKILL_SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


prepare = load_module("viralx_agent_prepare", "prepare_agent_evidence.py")
validator = load_module("viralx_agent_validator", "validate_agent_report.py")


class ViralXAgentPreparationTests(unittest.TestCase):
    def test_preparation_script_has_no_remote_model_transport(self):
        source = (SKILL_SCRIPTS / "prepare_agent_evidence.py").read_text(encoding="utf-8")
        for forbidden in ("chat/completions", "Authorization", "OPENAI_API_KEY", "MODEL_API_KEY", "api_key"):
            self.assertNotIn(forbidden, source)

    def test_canonical_url_removes_query_and_fragment(self):
        value = prepare.canonical_url("https://www.tiktok.com/@demo/video/123?is_copy_url=1#x")
        self.assertEqual(value, "https://www.tiktok.com/@demo/video/123")

    def test_adaptive_times_cover_beginning_and_end(self):
        times = prepare.adaptive_frame_times(12.0, max_frames=36)
        self.assertEqual(times[0], 0.1)
        self.assertEqual(times[-1], 11.9)
        self.assertLessEqual(max(b - a for a, b in zip(times, times[1:])), 1.01)

    def test_frame_limit_is_enforced_and_timestamp_is_stable(self):
        times = prepare.adaptive_frame_times(240.0, max_frames=12)
        self.assertEqual(len(times), 12)
        self.assertEqual(prepare.timestamp_label(62.345), "01:02.345")
        self.assertEqual(prepare.frame_filename(7, 62.345), "F007_01-02-345.jpg")


class ViralXAgentReportValidationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {
            "schema": "viralx.agent-evidence.v1",
            "frames": [
                {"id": "F001", "timestamp": "00:00.100"},
                {"id": "F002", "timestamp": "00:01.100"},
            ],
            "evidence": {
                "metadata_path": "C:/evidence/metadata.json",
                "transcript_available": True,
                "comments_available": False,
            },
            "coverage": {"coverage_limited": False},
        }

    def test_valid_report_passes(self):
        report = (
            "标题来自平台元数据。[META:title]\n"
            "开场出现产品。[FRAME:F001@00:00.100]\n"
            "随后展示安装。[FRAME:F002@00:01.100]\n"
            "台词见转写。[TK:transcript]\n"
            "评论证据未采集。[COMMENTS:unavailable]\n"
        )
        result = validator.validate_report(self.manifest, report)
        self.assertTrue(result["valid"])
        self.assertEqual(result["valid_frame_citations"], ["F001", "F002"])

    def test_fabricated_and_mismatched_evidence_is_rejected(self):
        report = (
            "画面如此。[FRAME:F999@00:00.100]\n"
            "另一帧时间写错。[FRAME:F002@00:09.999]\n"
            "用户很喜欢。[COMMENTS:sample]\n"
        )
        result = validator.validate_report(self.manifest, report)
        self.assertFalse(result["valid"])
        joined = "\n".join(result["errors"])
        self.assertIn("Unknown frame citation", joined)
        self.assertIn("Timestamp mismatch", joined)
        self.assertIn("comment sample", joined)


if __name__ == "__main__":
    unittest.main()
