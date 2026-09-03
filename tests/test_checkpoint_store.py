import tempfile
import unittest
from pathlib import Path

from viralx.checkpoint_store import CheckpointStore


class CheckpointStoreTests(unittest.TestCase):
    def test_checkpoint_is_persistent_public_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CheckpointStore(tmp, retention_hours=1)
            public = store.create_final_checkpoint({
                "video_id": "123",
                "title": "Picture light",
                "pipeline_status": "error",
                "pipeline_stage": "final-analysis",
                "evidence_status": "merged",
                "evidence_bundle": {
                    "schema": "viralx.evidence_bundle.v1",
                    "shot_evidence": {"shot_count": 2},
                },
                "evidence_bundle_path": str(Path(tmp) / "viralx-evidence" / "evidence-bundle.json"),
                "model_api_key": "must-not-persist",
                "_media_transport_url": "https://signed.example/video?secret=1",
            })

            record = store.load(public["task_id"])
            serialized = (store.root / f'{public["task_id"]}.json').read_text(encoding="utf-8")
            self.assertEqual(record["resumable_stage"], "final-analysis")
            self.assertTrue(public["artifacts"]["evidence_bundle"])
            self.assertNotIn("model_api_key", serialized)
            self.assertNotIn("must-not-persist", serialized)
            self.assertNotIn("signed.example", serialized)
            self.assertNotIn("internal", str(public))

    def test_invalid_or_unknown_task_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CheckpointStore(tmp)
            with self.assertRaises(ValueError):
                store.load("../../config")
            with self.assertRaises(KeyError):
                store.load("A" * 24)

    def test_checkpoint_snapshots_per_video_audit_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "tk-note" / "123"
            audit = package / "viralx-evidence"
            audit.mkdir(parents=True)
            source = package / "source.mp4"
            source.write_bytes(b"video")
            bundle = audit / "evidence-bundle.json"
            shot = audit / "shot-evidence.md"
            report = audit / "final-model-report.raw.md"
            bundle.write_text('{"target_product":"picture light"}', encoding="utf-8")
            shot.write_text("shot evidence", encoding="utf-8")
            report.write_text("first report", encoding="utf-8")
            store = CheckpointStore(root / "cache")

            public = store.create_final_checkpoint({
                "video_id": "123",
                "pipeline_status": "error",
                "evidence_bundle": {"schema": "viralx.evidence_bundle.v1"},
                "evidence_bundle_path": str(bundle),
                "shot_evidence_path": str(shot),
                "raw_model_report_path": str(report),
            })
            report.write_text("second report", encoding="utf-8")
            record = store.load(public["task_id"])

            frozen_report = Path(record["internal"]["raw_model_report_path"])
            self.assertEqual(frozen_report.read_text(encoding="utf-8"), "first report")
            self.assertEqual(frozen_report.parent.name, public["task_id"])
            self.assertEqual(record["internal"]["source_video_path"], str(source))


if __name__ == "__main__":
    unittest.main()
