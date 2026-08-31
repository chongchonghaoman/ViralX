from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerLauncherTests(unittest.TestCase):
    def test_launcher_only_replaces_a_verified_viralx_worker(self):
        launcher = (ROOT / "start-worker.cmd").read_text(encoding="utf-8")
        self.assertIn("/api/health", launcher)
        self.assertIn("viralx-home-worker", launcher)
        self.assertIn("Get-NetTCPConnection", launcher)
        self.assertIn("taskkill.exe /PID %%P", launcher)


if __name__ == "__main__":
    unittest.main()
