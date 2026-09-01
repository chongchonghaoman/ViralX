from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerLauncherTests(unittest.TestCase):
    def test_launcher_replaces_only_project_owned_worker_processes(self):
        launcher = (ROOT / "start-worker.cmd").read_text(encoding="utf-8")
        stopper = (ROOT / "scripts" / "stop-viralx-worker.ps1").read_text(encoding="utf-8")

        self.assertIn("stop-viralx-worker.ps1", launcher)
        self.assertIn("venv\\Scripts\\python.exe", stopper)
        self.assertIn("$parentExecutable -ieq $venvPython", stopper)
        self.assertIn("worker_server\\.py", stopper)
        self.assertIn("Stop-Process", stopper)
        self.assertNotIn("taskkill.exe", launcher)


if __name__ == "__main__":
    unittest.main()
