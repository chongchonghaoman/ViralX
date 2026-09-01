import tempfile
import unittest
from pathlib import Path

from checkpoint_store import CheckpointStore


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


if __name__ == "__main__":
    unittest.main()
