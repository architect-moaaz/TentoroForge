"""Tests for services.ux_spec_generator's brief-first compliance behavior.

Spec D Wave 1 (round 2) — when the brief carries
``identity.compliance_flags``, ``generate_ux_spec`` should surface them
in the compliance header alongside the domain default. When the brief
is silent (or output_dir is not threaded through), behavior is
unchanged from before the migration.
"""
from __future__ import annotations

from pathlib import Path

from schemas.design_brief import DesignBrief
from services.ux_spec_generator import generate_ux_spec
from tests.services._brief_fixtures import healthcare_brief


def _write_brief(tmp_path: Path, brief: DesignBrief) -> Path:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "brief.json").write_text(brief.model_dump_json())
    return tmp_path


class TestGenerateUxSpecBriefFirst:
    def test_no_output_dir_matches_pre_migration_output(self) -> None:
        """Call without output_dir: brief is never read; header shows only
        the domain default. Guards against accidentally coupling every
        caller to brief-reads."""
        out = generate_ux_spec("Healthcare", {"data_models": []})
        assert "### Compliance (HIPAA)" in out
        assert "brief-requested" not in out

    def test_missing_brief_json_falls_back(self, tmp_path: Path) -> None:
        """output_dir threaded but no brief.json on disk: fall back
        silently to the domain default. No crash."""
        out = generate_ux_spec(
            "Healthcare", {"data_models": []}, output_dir=str(tmp_path),
        )
        assert "### Compliance (HIPAA)" in out
        assert "brief-requested" not in out

    def test_brief_flags_augment_domain_header(self, tmp_path: Path) -> None:
        payload = healthcare_brief().model_dump()
        payload["identity"]["compliance_flags"] = ["hipaa", "soc2"]
        _write_brief(tmp_path, DesignBrief.model_validate(payload))
        out = generate_ux_spec(
            "Healthcare", {"data_models": []}, output_dir=str(tmp_path),
        )
        # Both the domain default AND the brief-requested regimes present.
        assert "HIPAA" in out
        assert "SOC2" in out
        assert "brief-requested:" in out
        # Requirement bullets still emitted verbatim.
        assert "Audit log" in out or "audit" in out.lower()

    def test_brief_flags_survive_when_domain_has_no_compliance(
        self, tmp_path: Path,
    ) -> None:
        """A brief that names GDPR against a domain the registry has no
        compliance block for should still surface the flag so agents can
        apply generic safeguards."""
        payload = healthcare_brief().model_dump()
        payload["identity"]["compliance_flags"] = ["gdpr"]
        _write_brief(tmp_path, DesignBrief.model_validate(payload))
        # Use a domain guaranteed absent from DOMAIN_UX registry.
        out = generate_ux_spec(
            "MadeUpDomain42", {"data_models": []}, output_dir=str(tmp_path),
        )
        assert "GDPR" in out
        assert "brief-requested" in out
