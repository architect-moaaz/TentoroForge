"""People are given the app's own address — its main domain, else the
production alias — which moves to the newest publish; each build's frozen
address is kept beside it for the history and a rollback. The tester kept
the first publish's address and saw a fault fixed in the second (2026-10-15)."""
from __future__ import annotations

import json
from pathlib import Path

from services.deploy.sign_in_address import stable_address


def _blueprint(tmp_path: Path, domains: list[dict]) -> Path:
    out = tmp_path / "pcn4owv7"
    (out / ".forge" / "blueprint").mkdir(parents=True)
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps({"deployment": {"domains": domains}}))
    return out


def test_the_alias_vercel_reports_or_the_projects_own(tmp_path):
    out = _blueprint(tmp_path, [])
    assert stable_address(out, "pcn4owv7", "pcn4owv7.vercel.app") == "https://pcn4owv7.vercel.app"
    assert stable_address(out, "pcn4owv7", "") == "https://pcn4owv7.vercel.app"
    assert stable_address(out, "pcn4owv7", "https://pcn4owv7.vercel.app") == "https://pcn4owv7.vercel.app"


def test_a_live_main_domain_wins(tmp_path):
    out = _blueprint(tmp_path, [{"name": "money.acme.com", "main": True, "status": "live"},
                                {"name": "old.acme.com", "main": False, "status": "live"}])
    assert stable_address(out, "pcn4owv7", "pcn4owv7.vercel.app") == "https://money.acme.com"
    out2 = _blueprint(tmp_path / "b", [{"name": "money.acme.com", "main": True, "status": "pending"}])
    assert stable_address(out2, "pcn4owv7", "") == "https://pcn4owv7.vercel.app"
