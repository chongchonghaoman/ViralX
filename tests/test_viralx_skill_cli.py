import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "viralx" / "scripts" / "viralx.py"
SPEC = importlib.util.spec_from_file_location("viralx_skill_client", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        return iter(self.lines)


class ViralXSkillClientTests(unittest.TestCase):
    def test_api_url_supports_site_and_api_base_urls(self):
        self.assertEqual(
            MODULE.api_url("https://viralx.metrolabs.mobi", "health"),
            "https://viralx.metrolabs.mobi/api/health",
        )
        self.assertEqual(
            MODULE.api_url("http://127.0.0.1:5001/api/", "/analyze"),
            "http://127.0.0.1:5001/api/analyze",
        )

    def test_credentials_map_to_headers_without_changing_values(self):
        headers = MODULE.credential_headers({
            "RAPIDAPI_KEY": "rapid-secret",
            "LIBTV_ACCESS_KEY": "libtv-secret",
            "ANALYSIS_MODE": "libtv",
        })
        self.assertEqual(headers["X-ViralX-RapidAPI-Key"], "rapid-secret")
        self.assertEqual(headers["X-ViralX-LibTV-Key"], "libtv-secret")
        self.assertEqual(headers["X-ViralX-Analysis-Mode"], "libtv")

    @patch.object(MODULE, "urlopen")
    def test_application_error_stream_returns_exit_code_two(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse([
            json.dumps({"status": "error", "message": "missing key", "done": True}).encode("utf-8") + b"\n"
        ])
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = MODULE.stream_analyze(
                "https://viralx.metrolabs.mobi",
                {"keyword": "camping light"},
                timeout=10,
            )
        self.assertEqual(exit_code, 2)
        self.assertIn("missing key", output.getvalue())


if __name__ == "__main__":
    unittest.main()
