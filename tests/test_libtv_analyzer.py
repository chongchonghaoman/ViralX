import tempfile
import unittest
from pathlib import Path

from libtv_analyzer import LibTVAnalyzer, LibTVError, _extract_report


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class LibTVAnalyzerTests(unittest.TestCase):
    def make_video(self):
        temp_dir = tempfile.TemporaryDirectory()
        video_path = Path(temp_dir.name) / "douyin.mp4"
        video_path.write_bytes(b"fake-video")
        self.addCleanup(temp_dir.cleanup)
        return video_path

    def test_full_upload_session_poll_workflow(self):
        calls = []
        query_count = 0

        def runner(script_name, args, timeout):
            nonlocal query_count
            calls.append((script_name, args, timeout))
            if script_name == "upload_file.py":
                return {"url": "https://libtv-res.liblib.art/claw/project/video.mp4"}
            if script_name == "create_session.py":
                return {
                    "sessionId": "session-1",
                    "projectUuid": "project-1",
                    "projectUrl": "https://www.liblib.tv/canvas?projectId=project-1",
                }
            query_count += 1
            if query_count == 1:
                return {
                    "messages": [
                        {"id": "m1", "seq": 1, "role": "assistant", "content": "正在分析中，请稍候"}
                    ]
                }
            return {
                "messages": [
                    {
                        "id": "m2",
                        "seq": 2,
                        "role": "assistant",
                        "status": "completed",
                        "content": "## 一键拉片\n\n| 时间轴 | 镜头 | 画面 |\n|---|---|---|\n| 0-3s | 特写 | 产品开场 |",
                    }
                ]
            }

        clock = FakeClock()
        analyzer = LibTVAnalyzer(
            access_key="test-key",
            poll_interval=1,
            timeout=10,
            runner=runner,
            sleeper=clock.sleep,
            clock=clock,
        )

        result = analyzer.analyze(str(self.make_video()))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.session_id, "session-1")
        self.assertIn("时间轴", result.analysis)
        self.assertEqual([call[0] for call in calls[:2]], ["upload_file.py", "create_session.py"])
        self.assertIn("一键拉片", calls[1][1][0])
        self.assertIn("参考视频：https://libtv-res.liblib.art/claw/project/video.mp4", calls[1][1][0])
        self.assertIn("--after-seq", calls[-1][1])
        self.assertIn("1", calls[-1][1])

    def test_timeout_keeps_project_link_and_latest_progress(self):
        clock = FakeClock()

        def runner(script_name, args, timeout):
            if script_name == "upload_file.py":
                return {"url": "https://libtv-res.liblib.art/claw/p/video.mp4"}
            if script_name == "create_session.py":
                return {
                    "sessionId": "session-timeout",
                    "projectUuid": "project-timeout",
                    "projectUrl": "https://www.liblib.tv/canvas?projectId=project-timeout",
                }
            return {
                "messages": [
                    {"id": "progress", "seq": 1, "role": "assistant", "content": "正在分析中，请稍候"}
                ]
            }

        analyzer = LibTVAnalyzer(
            access_key="test-key",
            poll_interval=1,
            timeout=2,
            runner=runner,
            sleeper=clock.sleep,
            clock=clock,
        )

        result = analyzer.analyze(str(self.make_video()))

        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.project_uuid, "project-timeout")
        self.assertIn("正在分析", result.analysis)

    def test_missing_access_key_fails_before_upload(self):
        analyzer = LibTVAnalyzer(access_key="", runner=lambda *_: {})
        with self.assertRaisesRegex(LibTVError, "LIBTV_ACCESS_KEY"):
            analyzer.analyze(str(self.make_video()))

    def test_progress_message_is_not_mistaken_for_report(self):
        messages = [
            {
                "role": "assistant",
                "content": "正在分析中，请稍候。我们正在进行镜头和时间轴识别。",
            }
        ]
        self.assertIsNone(_extract_report(messages))


if __name__ == "__main__":
    unittest.main()
