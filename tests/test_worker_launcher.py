from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WorkerLauncherTests(unittest.TestCase):
    def test_launcher_replaces_only_project_owned_worker_processes(self):
        launcher = (ROOT / "start-worker.cmd").read_text(encoding="utf-8")
        stopper = (ROOT / "scripts" / "stop-viralx-worker.ps1").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "run-worker.ps1").read_text(encoding="utf-8")

        self.assertIn("run-worker.ps1", launcher)
        self.assertIn("stop-viralx-worker.ps1", runner)
        self.assertIn("venv\\Scripts\\python.exe", runner)
        self.assertIn("VIRALX_ALLOWED_ORIGINS", runner)
        self.assertIn("venv\\Scripts\\python.exe", stopper)
        self.assertIn("$parentExecutable -ieq $venvPython", stopper)
        self.assertIn("worker_server\\.py", stopper)
        self.assertIn("Stop-Process", stopper)
        self.assertNotIn("taskkill.exe", launcher)

    def test_autostart_is_current_user_scoped_restartable_and_reversible(self):
        installer = (ROOT / "scripts" / "install-worker-autostart.ps1").read_text(encoding="utf-8")

        self.assertIn('taskName = "ViralX Home Worker"', installer)
        self.assertIn("New-ScheduledTaskTrigger -AtLogOn", installer)
        self.assertIn("-WindowStyle Hidden", installer)
        self.assertIn("-RestartCount 5", installer)
        self.assertIn("-MultipleInstances IgnoreNew", installer)
        self.assertIn("[switch]$Remove", installer)
        self.assertIn("Unregister-ScheduledTask", installer)


if __name__ == "__main__":
    unittest.main()
