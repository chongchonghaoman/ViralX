"""Guard resource paths and public entrypoints when reorganizing the repository."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from viralx.paths import PROJECT_ROOT


class PackageLayoutTests(unittest.TestCase):
    def test_project_root_is_not_the_python_package(self):
        self.assertEqual(PROJECT_ROOT, Path(__file__).resolve().parents[1])
        self.assertTrue((PROJECT_ROOT / "config/config.json.example").is_file())

    def test_legacy_imports_share_the_implementation_module(self):
        for name in ("web_app", "worker_server"):
            with self.subTest(module=name):
                self.assertIs(importlib.import_module(name),
                              importlib.import_module("viralx." + name))

    def test_flask_resources_and_config_survive_another_working_directory(self):
        from viralx import web_app

        self.assertEqual(web_app.CONFIG_PATH, PROJECT_ROOT / "config.json")
        self.assertEqual(Path(web_app.app.template_folder), PROJECT_ROOT / "templates")
        self.assertEqual(Path(web_app.app.static_folder), PROJECT_ROOT / "static")
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                with patch.object(web_app, "CONFIG_PATH", Path(temporary) / "missing.json"):
                    client = web_app.app.test_client()
                    for url in ("/", "/settings", "/static/tokens.css"):
                        with self.subTest(url=url):
                            with client.get(url) as response:
                                self.assertEqual(response.status_code, 200)
            finally:
                os.chdir(previous)

    def test_tk_note_and_libtv_keep_their_project_location(self):
        from viralx.libtv_analyzer import LibTVAuthManager
        from viralx.video_ingest import TKNoteCollector

        with tempfile.TemporaryDirectory() as temporary:
            collector = TKNoteCollector(Path(temporary))
            self.assertEqual(collector.skill_dir, PROJECT_ROOT / ".agents/skills/tk-note")
        self.assertEqual(LibTVAuthManager().cwd, PROJECT_ROOT)

    def test_legacy_worker_launcher_runs_outside_project_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "worker_server.py"), "--help"],
                cwd=temporary, capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--port", result.stdout)


if __name__ == "__main__":
    unittest.main()
