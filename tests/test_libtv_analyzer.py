import tempfile
import unittest
from subprocess import CompletedProcess
from pathlib import Path

from libtv_analyzer import LibTVAnalyzer, LibTVError, _safe_message


class LibTVAnalyzerTests(unittest.TestCase):
    def make_video(self):
        temp_dir = tempfile.TemporaryDirectory()
        video_path = Path(temp_dir.name) / "douyin.mp4"
        video_path.write_bytes(b"fake-video")
        self.addCleanup(temp_dir.cleanup)
        return video_path

    def test_creates_canvas_then_uploads_source_video(self):
        calls = []

        def runner(args, timeout):
            calls.append((args, timeout))
            if args[:2] == ["project", "create"]:
                return {"data": {"uuid": "project-1"}}
            if args[0] == "upload":
                return {"success": True}
            if args[0] == "node":
                return {"data": {"content": "## 镜头证据\n00:00 产品出现"}}
            raise AssertionError(args)

        analyzer = LibTVAnalyzer(
            cli_path="libtv",
            runner=runner,
            auth_checker=lambda: True,
        )
        result = analyzer.analyze(str(self.make_video()))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.project_uuid, "project-1")
        self.assertEqual(result.project_url, "https://www.liblib.tv/canvas?projectId=project-1")
        self.assertIn("00:00", result.analysis)
        self.assertEqual(result.evidence["model"], "GVLM 3.1 Flash")
        self.assertEqual(calls[0][0][:2], ["project", "create"])
        self.assertEqual(calls[1][0][0], "upload")
        self.assertIn("--resource", calls[1][0])
        self.assertIn("--project", calls[1][0])
        self.assertIn("project-1", calls[1][0])
        self.assertEqual(calls[2][0][0], "node")
        self.assertIn("--run", calls[2][0])
        self.assertIn("model=GVLM 3.1 Flash", calls[2][0])

    def test_accepts_official_human_readable_project_output(self):
        calls = []

        def runner(args, timeout):
            calls.append(args)
            if args[:2] == ["project", "create"]:
                return CompletedProcess(args, 0, "画布创建成功\n项目 UUID: project-human-123\n", "")
            if args[0] == "node":
                return CompletedProcess(args, 0, '{"data":{"content":"逐镜证据"}}\n', "")
            return CompletedProcess(args, 0, "上传成功\n", "")

        analyzer = LibTVAnalyzer(
            cli_path="libtv",
            runner=runner,
            auth_checker=lambda: True,
        )
        result = analyzer.analyze(str(self.make_video()))
        self.assertEqual(result.project_uuid, "project-human-123")
        self.assertIn("project-human-123", calls[1])

    def test_browser_login_is_required_before_any_upload(self):
        calls = []
        analyzer = LibTVAnalyzer(
            cli_path="libtv",
            runner=lambda args, timeout: calls.append(args),
            auth_checker=lambda: False,
        )
        with self.assertRaisesRegex(LibTVError, "连接 LibTV"):
            analyzer.analyze(str(self.make_video()))
        self.assertEqual(calls, [])

    def test_missing_official_cli_has_actionable_error(self):
        analyzer = LibTVAnalyzer(cli_path="", auth_checker=lambda: False)
        analyzer.cli_path = ""
        with self.assertRaisesRegex(LibTVError, "官方 LibTV CLI"):
            analyzer.analyze(str(self.make_video()))

    def test_cli_errors_redact_token_shaped_values(self):
        message = _safe_message("Authorization: Bearer secret-token access_token=abc123")
        self.assertNotIn("secret-token", message)
        self.assertNotIn("abc123", message)
        self.assertIn("redacted", message)


if __name__ == "__main__":
    unittest.main()
