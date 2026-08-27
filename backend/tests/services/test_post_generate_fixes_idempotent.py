"""Phase 7 — idempotency of the ``apply_post_generate_fixes`` entry point.

The suite has ~50 guards. A second top-level call for the same
``output_dir`` in one process is almost always a bug (the router
branches through mutually-exclusive schema/full paths, so a legitimate
double-call means routing crossed wires). Smith edit flows that
legitimately need to re-heal an output_dir pass ``force=True``.
"""
from __future__ import annotations

import logging

import pytest

from services.post_generate_fixes import apply_post_generate_fixes
from services.post_gen_phases import is_run_complete, reset_run


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    reset_run(str(tmp_path))
    yield
    reset_run(str(tmp_path))


class TestIdempotency:
    def test_missing_output_dir_returns_zero(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        assert apply_post_generate_fixes(str(missing)) == 0

    def test_first_call_marks_run_complete(self, tmp_path):
        # Even with an empty output_dir the entry point completes and
        # marks the run so the idempotency guard can fire on any second
        # call — the guards themselves are all wrapped in try/except so
        # a bare tmp_path just no-ops through them.
        (tmp_path / "src").mkdir()  # give the suite a real dir to walk
        apply_post_generate_fixes(str(tmp_path))
        assert is_run_complete(str(tmp_path))

    def test_second_call_warns_and_noops(self, tmp_path, caplog):
        (tmp_path / "src").mkdir()
        apply_post_generate_fixes(str(tmp_path))
        with caplog.at_level(logging.WARNING, logger="services.post_generate_fixes"):
            result = apply_post_generate_fixes(str(tmp_path))
        assert result == 0
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "called twice" in joined
        assert "force=True" in joined

    def test_force_bypasses_idempotency(self, tmp_path, caplog):
        (tmp_path / "src").mkdir()
        apply_post_generate_fixes(str(tmp_path))
        # A forced re-run should NOT warn and should proceed. It might
        # still return 0 (nothing to fix on an empty tree), but the
        # crucial check is the absence of the "called twice" warning.
        with caplog.at_level(logging.WARNING, logger="services.post_generate_fixes"):
            apply_post_generate_fixes(str(tmp_path), force=True)
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "called twice" not in joined

    def test_reset_run_reenables_normal_call(self, tmp_path):
        (tmp_path / "src").mkdir()
        apply_post_generate_fixes(str(tmp_path))
        reset_run(str(tmp_path))
        # After reset, another normal (unforced) call should succeed
        # without the duplicate warning, because reset drops output_dir
        # from the completed set.
        assert not is_run_complete(str(tmp_path))
        apply_post_generate_fixes(str(tmp_path))
        assert is_run_complete(str(tmp_path))
