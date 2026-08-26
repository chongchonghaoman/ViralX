import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents" / "skills" / "tk-note" / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMMON = load_module("tk_note_common_for_tests", SCRIPTS / "_common.py")
with mock.patch.dict(sys.modules, {"_common": COMMON}):
    EXTRACT = load_module("tk_note_extract_for_tests", SCRIPTS / "extract_tiktok_text.py")


class SharedWhisperEnvironmentTests(unittest.TestCase):
    def test_explicit_whisper_python_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit_python = root / "custom-whisper" / "python.exe"
            explicit_python.parent.mkdir(parents=True)
            explicit_python.write_bytes(b"")

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "RIMAGINATION_WHISPER_PYTHON": str(explicit_python),
                        "RIMAGINATION_NOTE_CACHE": str(root / "cache"),
                    },
                    clear=True,
                ),
                mock.patch.object(
                    COMMON.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
            ):
                selected = COMMON.find_shared_whisper_python()

            self.assertEqual(selected, explicit_python)
            self.assertEqual(run.call_args.args[0], [str(explicit_python), "-c", "import whisper"])
            self.assertEqual(run.call_args.kwargs["timeout"], 20)
            self.assertIs(run.call_args.kwargs["stdout"], subprocess.DEVNULL)
            self.assertIs(run.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_existing_qwen_environment_can_supply_whisper(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "rimagination-notes"
            shared_python = cache / "qwen3-asr-venv" / "Scripts" / "python.exe"
            shared_python.parent.mkdir(parents=True)
            shared_python.write_bytes(b"")

            with (
                mock.patch.dict(
                    os.environ,
                    {"RIMAGINATION_NOTE_CACHE": str(cache)},
                    clear=True,
                ),
                mock.patch.object(
                    COMMON.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ),
            ):
                selected = COMMON.find_shared_whisper_python()
                qwen_selected = COMMON.find_shared_qwen_python()

            self.assertEqual(selected, shared_python)
            self.assertEqual(qwen_selected, shared_python)

    def test_candidate_without_whisper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            explicit_python = root / "python.exe"
            explicit_python.write_bytes(b"")

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "RIMAGINATION_WHISPER_PYTHON": str(explicit_python),
                        "RIMAGINATION_NOTE_CACHE": str(root / "cache"),
                    },
                    clear=True,
                ),
                mock.patch.object(
                    COMMON.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 1),
                ),
            ):
                selected = COMMON.find_shared_whisper_python()

            self.assertIsNone(selected)

    def test_run_whisper_uses_selected_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out_dir = root / "out"
            out_dir.mkdir()
            audio = root / "audio_16k.wav"
            audio.write_bytes(b"audio")
            shared_python = root / "whisper-venv" / "python.exe"
            commands = []

            def run(command, **kwargs):
                commands.append((command, kwargs))
                (out_dir / "audio_16k.json").write_text(
                    json.dumps(
                        {
                            "text": "Hello world",
                            "segments": [
                                {"start": 0.0, "end": 1.2, "text": " Hello world "},
                                {"start": 1.2, "end": 2.0, "text": ""},
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with (
                mock.patch.object(EXTRACT, "find_shared_whisper_python", return_value=shared_python),
                mock.patch.object(EXTRACT.subprocess, "run", side_effect=run),
            ):
                segments, text = EXTRACT.run_whisper(audio, out_dir, "zh", "small")

            self.assertEqual(text, "Hello world")
            self.assertEqual(segments, [{"start": 0.0, "end": 1.2, "text": "Hello world"}])
            self.assertEqual(commands[0][0][0:3], [str(shared_python), "-m", "whisper"])
            self.assertIn("--language", commands[0][0])
            self.assertIn("zh", commands[0][0])
            self.assertEqual(commands[0][1]["timeout"], 3600)

    def test_run_whisper_reports_missing_environment(self):
        with mock.patch.object(EXTRACT, "find_shared_whisper_python", return_value=None):
            with self.assertRaisesRegex(EXTRACT.TKNoteError, "RIMAGINATION_WHISPER_PYTHON"):
                EXTRACT.run_whisper(Path("audio.wav"), Path("out"), "auto", "small")


if __name__ == "__main__":
    unittest.main()
