import unittest
from unittest.mock import patch

import requests

from shot_analyzers import (
    ShotAnalysisResult,
    ShotAnalyzerError,
    ShotAnalyzerRouter,
    ShotAnalyzerTransportError,
    ShotBoundary,
    ShotLoomCoreAnalyzer,
    merge_short_boundaries,
    normalize_shot_config,
    validate_shot_evidence,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class SequenceSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, *_args, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def valid_result(provider="shotloom"):
    shots = [
        {
            "shot_id": "S001", "start_ms": 0, "end_ms": 120,
            "duration_ms": 120, "keyframes_ms": [60],
            "visual_facts": ["物体出现"], "unknowns": [], "confidence": 0.8,
        },
        {
            "shot_id": "S002", "start_ms": 120, "end_ms": 1000,
            "duration_ms": 880, "keyframes_ms": [560],
            "visual_facts": ["物体移动"], "unknowns": [], "confidence": 0.8,
        },
    ]
    return ShotAnalysisResult(
        provider=provider, model="vision", status="completed",
        analysis="[SHOT:S001] 物体出现\n[SHOT:S002] 物体移动",
        evidence={
            "schema": "viralx.shot_evidence.v1",
            "source": {"sha256": "a" * 64},
            "duration_ms": 1000, "shot_count": 2, "shots": shots,
            "quality": {"timeline_coverage": 1.0, "analyzed_coverage": 1.0},
        },
    )


class FakeProvider:
    def __init__(self, ready=True, result=None, message="未就绪"):
        self.ready = ready
        self.result = result
        self.message = message
        self.calls = 0

    def status(self):
        return {"ready": self.ready, "message": self.message}

    def analyze(self, video_path, user_request=""):
        self.calls += 1
        return self.result


class NetworkFailingProvider(FakeProvider):
    def analyze(self, video_path, user_request=""):
        self.calls += 1
        raise requests.Timeout("vision timeout")


class ShotAnalyzerTests(unittest.TestCase):
    @staticmethod
    def shotloom(session):
        return ShotLoomCoreAnalyzer({
            "shot_engine": "shotloom", "shot_model_source": "custom",
            "shot_model_api_key": "key", "shot_model_base_url": "https://api.example.com/v1",
            "shot_model_name": "vision",
        }, session=session)

    def test_shotloom_retries_transient_connection_failure(self):
        session = SequenceSession([requests.ConnectionError("closed"), FakeResponse(200)])
        analyzer = self.shotloom(session)
        with patch("shot_analyzers.time.sleep"):
            response = analyzer._post_with_retry({"model": "vision"}, {"Authorization": "Bearer key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.calls, 2)

    def test_shotloom_does_not_retry_non_transient_auth_failure(self):
        session = SequenceSession([FakeResponse(401)])
        analyzer = self.shotloom(session)
        response = analyzer._post_with_retry({}, {})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(session.calls, 1)

    def test_shotloom_splits_a_batch_after_retry_exhaustion(self):
        analyzer = self.shotloom(SequenceSession([]))
        calls = []

        def request(_video_path, shots):
            calls.append([shot.shot_id for shot in shots])
            if len(shots) > 1:
                raise ShotAnalyzerTransportError("upstream closed")
            return [{"shot_id": shots[0].shot_id}]

        analyzer._request_batch = request
        shots = [ShotBoundary(index=i, start_time=float(i), end_time=float(i + 1), duration=1.0) for i in range(4)]
        records = analyzer._request_batch_resilient("source.mp4", shots)
        self.assertEqual([item["shot_id"] for item in records], ["S001", "S002", "S003", "S004"])
        self.assertGreater(len(calls), 4)

    def test_quality_gate_rejects_malformed_coverage_without_raising(self):
        result = valid_result()
        result.evidence["quality"]["timeline_coverage"] = "unknown"
        self.assertIn("有效数值", validate_shot_evidence(result))
        result.evidence["quality"]["timeline_coverage"] = float("nan")
        self.assertIn("有限数值", validate_shot_evidence(result))

    def test_default_visual_config_reads_the_source_video_directly(self):
        config = normalize_shot_config({})
        self.assertEqual(config["engine"], "direct")
        self.assertEqual(config["model_source"], "inherit")

    def test_fast_cuts_are_retained_and_timeline_stays_contiguous(self):
        shots = merge_short_boundaries([0.04, 0.12, 0.4, None, float("nan")], duration=1.0)
        self.assertEqual([(shot.start_time, shot.end_time) for shot in shots], [
            (0.0, 0.12), (0.12, 0.4), (0.4, 1.0),
        ])
        self.assertEqual(sum(shot.duration for shot in shots), 1.0)

    def test_quality_gate_rejects_incomplete_timeline(self):
        result = valid_result()
        result.evidence["quality"]["timeline_coverage"] = 0.7
        self.assertIn("98%", validate_shot_evidence(result))

    def test_auto_falls_back_to_libtv_and_records_reason(self):
        shotloom = FakeProvider(ready=False, message="依赖未安装")
        libtv = FakeProvider(result=valid_result("libtv"))
        router = ShotAnalyzerRouter(
            {"shot_engine": "auto"}, shotloom=shotloom, libtv=libtv,
        )
        result = router.analyze("source.mp4")
        self.assertEqual(result.provider, "libtv")
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.fallback_chain[0]["provider"], "shotloom")
        self.assertIn("依赖未安装", result.fallback_chain[0]["reason"])
        self.assertEqual(libtv.calls, 1)

    def test_auto_falls_back_when_shot_model_times_out(self):
        shotloom = NetworkFailingProvider()
        libtv = FakeProvider(result=valid_result("libtv"))
        router = ShotAnalyzerRouter(
            {"shot_engine": "auto"}, shotloom=shotloom, libtv=libtv,
        )
        result = router.analyze("source.mp4")
        self.assertEqual(result.provider, "libtv")
        self.assertTrue(result.fallback_used)
        self.assertIn("vision timeout", result.fallback_chain[0]["reason"])

    def test_explicit_shotloom_never_silently_falls_back(self):
        shotloom = FakeProvider(ready=False, message="依赖未安装")
        libtv = FakeProvider(result=valid_result("libtv"))
        router = ShotAnalyzerRouter(
            {"shot_engine": "shotloom"}, shotloom=shotloom, libtv=libtv,
        )
        result = router.analyze("source.mp4")
        self.assertEqual(result.status, "blocked")
        self.assertEqual(libtv.calls, 0)

    def test_inherit_requires_openai_compatible_vision_model(self):
        config = normalize_shot_config({
            "shot_engine": "shotloom", "shot_model_source": "inherit",
            "model_protocol": "openai", "model_supports_vision": False,
            "model_api_key": "key", "model_base_url": "https://api.example.com/v1",
            "model_name": "text-only",
        })
        self.assertFalse(config["compatible"])


if __name__ == "__main__":
    unittest.main()
