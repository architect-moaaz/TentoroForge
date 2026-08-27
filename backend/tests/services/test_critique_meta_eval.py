# backend/tests/services/test_critique_meta_eval.py
from services.critique_meta_eval import diagnose_distribution


def test_empty_samples():
    out = diagnose_distribution([])
    assert out["sample_size"] == 0


def test_lenient_evaluator_warning():
    samples = [{"score": 9.5, "issues": []} for _ in range(10)]
    out = diagnose_distribution(samples)
    assert any("lenient" in w for w in out["warnings"])


def test_low_discrimination_warning():
    samples = [{"score": 7.0, "issues": []} for _ in range(10)]
    out = diagnose_distribution(samples)
    assert any("discriminating" in w for w in out["warnings"])
