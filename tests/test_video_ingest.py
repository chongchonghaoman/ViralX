import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_ingest import (
    GenericVideoDownloader,
    TKNoteCollector,
    VideoAsset,
    VideoAssetCollector,
    VideoIngestError,
    is_tiktok_url,
)


class FakeGenericDownloader(GenericVideoDownloader):
    def __init__(self, output_dir):
        super().__init__(output_dir)
        self.calls = []

    def download(self, video_url, video_id, force=False):
        self.calls.append((video_url, video_id, force))
        path = self.output_path(video_id)
        path.write_bytes(b"generic-video")
        return str(path)


class FakeTKCollector:
    def __init__(self):
        self.calls = []

    def collect(self, video_url, video_id, force=False):
        self.calls.append((video_url, video_id, force))
        return VideoAsset("tk-note", "success", "source.mp4", video_id, video_url)


class VideoIngestTests(unittest.TestCase):
    def test_video_fields_preserve_search_metrics_when_collector_returns_zero(self):
        asset = VideoAsset(
            "tk-note", "success", "source.mp4", "123", "https://www.tiktok.com/@a/video/123",
            metadata={
                "video_id": "123", "title": "Real title", "duration": 12,
                "view_count": 0, "like_count": 0, "comment_count": 0, "share_count": 0,
            },
        )
        self.assertEqual(asset.video_fields(), {
            "video_id": "123", "title": "Real title", "duration": 12,
        })

    def test_video_fields_accept_metric_aliases_only_when_positive(self):
        asset = VideoAsset(
            "tk-note", "success", "source.mp4", "123", "https://www.tiktok.com/@a/video/123",
            metadata={
                "author": {"unique_id": "creator"}, "playCount": 1200,
                "digg_count": 88, "comments": 9, "number_of_reposts": 3,
            },
        )
        self.assertEqual(asset.video_fields(), {
            "author": "creator", "views": 1200, "likes": 88, "comments": 9, "shares": 3,
        })

    def test_tk_note_reuses_legacy_cache_when_exact_post_id_matches(self):
        script = Path(__file__).parents[1] / ".agents" / "skills" / "tk-note" / "scripts" / "extract_tiktok_text.py"
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "7480000000000000001"
            (out_dir / "assets").mkdir(parents=True)
            (out_dir / "source.mp4").write_bytes(b"verified-video")
            (out_dir / "metadata.json").write_text(
                json.dumps({"video_id": "7480000000000000001", "title": "legacy"}),
                encoding="utf-8",
            )
            (out_dir / "transcript.txt").write_text("text", encoding="utf-8")
            (out_dir / "segments.json").write_text("[]", encoding="utf-8")
            (out_dir / "note_budget.json").write_text("{}", encoding="utf-8")
            (out_dir / "assets" / "asset_manifest.json").write_text("{}", encoding="utf-8")
            url = "https://www.tiktok.com/@creator/video/7480000000000000001"

            completed = subprocess.run(
                [sys.executable, str(script), url, "--out-dir", str(out_dir), "--asr-backend", "none"],
                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout.splitlines()[-1])["status"], "reused")
            metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["source_url"], url)
            self.assertEqual((out_dir / "source.mp4").read_bytes(), b"verified-video")

    def test_platform_routing(self):
        self.assertTrue(is_tiktok_url("https://www.tiktok.com/@creator/video/123"))
        self.assertTrue(is_tiktok_url("https://vt.tiktok.com/abc"))
        self.assertFalse(is_tiktok_url("https://www.douyin.com/video/123"))

        with tempfile.TemporaryDirectory() as tmp:
            tk = FakeTKCollector()
            generic = FakeGenericDownloader(tmp)
            collector = VideoAssetCollector(
                cache_dir=tmp,
                tk_note_collector=tk,
                generic_downloader=generic,
            )
            result = collector.prepare("https://www.tiktok.com/@a/video/123", "123", force=True)
            self.assertEqual(result.provider, "tk-note")
            self.assertEqual(tk.calls[0][-1], True)
            generic_result = collector.prepare("https://www.douyin.com/video/456", "456")
            self.assertEqual(generic_result.provider, "yt-dlp")
            self.assertEqual(len(generic.calls), 1)

    def test_tk_note_uses_system_proxy_when_no_explicit_proxy_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "extract_tiktok_text.py").write_text("# fake", encoding="utf-8")
            with patch("video_ingest.getproxies", return_value={"https": "http://127.0.0.1:7892"}):
                collector = TKNoteCollector(root / "cache", skill_dir=skill)
            self.assertEqual(collector.proxy_source, "system")
            self.assertEqual(collector.proxy, "http://127.0.0.1:7892")

    def test_tk_note_explicit_proxy_takes_precedence_over_system_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "extract_tiktok_text.py").write_text("# fake", encoding="utf-8")
            with patch("video_ingest.getproxies", return_value={"https": "http://127.0.0.1:7892"}):
                collector = TKNoteCollector(
                    root / "cache",
                    skill_dir=skill,
                    proxy="socks5://127.0.0.1:1080",
                )
            self.assertEqual(collector.proxy_source, "explicit")
            self.assertEqual(collector.proxy, "socks5://127.0.0.1:1080")

    def test_tk_note_json_contract_and_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "extract_tiktok_text.py").write_text("# fake", encoding="utf-8")
            video = root / "source.mp4"
            video.write_bytes(b"video")
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps({"video_id": "real-123", "title": "A title", "like_count": 42}),
                encoding="utf-8",
            )
            payload = {
                "status": "partial",
                "source_url": "https://www.tiktok.com/@a/video/123",
                "video_id": "real-123",
                "video_file": str(video),
                "metadata": str(metadata),
                "transcript": str(root / "transcript.txt"),
                "transcript_source": "blocked",
                "asset_manifest": str(root / "assets" / "asset_manifest.json"),
                "warnings": ["ASR unavailable"],
                "blocked_stages": ["transcript"],
            }
            seen = {}

            def runner(command, timeout):
                seen["command"] = command
                seen["timeout"] = timeout
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps(payload, ensure_ascii=False) + "\n",
                    stderr=json.dumps({"stage": "download", "status": "completed"}) + "\n",
                )

            collector = TKNoteCollector(
                root / "cache",
                skill_dir=skill,
                asr_backend="auto",
                language="auto",
                cookies_from_browser="edge",
                runner=runner,
            )
            asset = collector.collect(payload["source_url"], "cache-key", force=True)
            self.assertEqual(asset.status, "partial")
            self.assertEqual(asset.video_id, "real-123")
            self.assertEqual(asset.metadata["like_count"], 42)
            self.assertEqual(asset.progress_events[0]["stage"], "download")
            self.assertIn("--cookies-from-browser", seen["command"])
            self.assertIn("--refresh-derived", seen["command"])
            self.assertNotIn("--force", seen["command"])
            task_log = Path(asset.task_log)
            self.assertTrue(task_log.is_file())
            records = [json.loads(line) for line in task_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["event"], "collection_started")
            self.assertEqual(records[-1]["event"], "collection_completed")
            self.assertEqual(records[-1]["video_size_bytes"], len(b"video"))

    def test_tk_note_media_transport_uses_child_environment_not_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "extract_tiktok_text.py").write_text("# fake", encoding="utf-8")
            video = root / "source.mp4"
            video.write_bytes(b"video")
            metadata = root / "metadata.json"
            metadata.write_text(json.dumps({"video_id": "7480000000000000001"}), encoding="utf-8")
            payload = {
                "status": "success",
                "source_url": "https://www.tiktok.com/@a/video/7480000000000000001",
                "video_id": "7480000000000000001",
                "video_file": str(video),
                "metadata": str(metadata),
                "transcript": str(root / "transcript.txt"),
                "asset_manifest": str(root / "assets" / "asset_manifest.json"),
                "warnings": [],
                "blocked_stages": [],
            }
            completed = subprocess.CompletedProcess(
                [], 0, stdout=json.dumps(payload) + "\n", stderr="",
            )
            signed = "https://v16-webapp-prime.tiktok.com/video/tos/example.mp4?signature=secret"
            collector = TKNoteCollector(root / "cache", skill_dir=skill)

            with patch("video_ingest.subprocess.run", return_value=completed) as run:
                collector.collect(payload["source_url"], payload["video_id"], media_url=signed)

            command = run.call_args.args[0]
            env = run.call_args.kwargs["env"]
            self.assertNotIn(signed, command)
            self.assertEqual(env["VIRALX_TK_MEDIA_URL"], signed)
            self.assertEqual(env["PYTHONUTF8"], "1")

    def test_tk_note_failure_is_logged_without_proxy_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "extract_tiktok_text.py").write_text("# fake", encoding="utf-8")
            proxy = "http://private-user:private-password@127.0.0.1:7890"

            def runner(command, timeout):
                return subprocess.CompletedProcess(
                    command,
                    2,
                    stdout=json.dumps({
                        "status": "error",
                        "message": (
                            f"TikTok 下载失败：proxy={proxy}; Unexpected response from webpage request; "
                            "media=https://cdn.example.com/video.mp4?token=signed-secret"
                        ),
                    }, ensure_ascii=False) + "\n",
                    stderr=json.dumps({
                        "stage": "download",
                        "status": "error",
                        "message": f"proxy={proxy}",
                    }, ensure_ascii=False) + "\n",
                )

            collector = TKNoteCollector(
                root / "cache",
                skill_dir=skill,
                proxy=proxy,
                runner=runner,
            )
            with self.assertRaises(VideoIngestError) as caught:
                collector.collect("https://www.tiktok.com/@a/video/7480000000000000001", "7480000000000000001")

            task_log = Path(caught.exception.task_log)
            self.assertTrue(task_log.is_file())
            content = task_log.read_text(encoding="utf-8")
            self.assertIn("collection_failed", content)
            self.assertIn("Unexpected response from webpage request", content)
            self.assertNotIn("private-user", content)
            self.assertNotIn("private-password", content)
            self.assertNotIn(proxy, content)
            self.assertNotIn("signed-secret", content)
            self.assertNotIn("cdn.example.com", content)
            self.assertIn("[url redacted]", content)


if __name__ == "__main__":
    unittest.main()
