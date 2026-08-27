"""Shared fixtures for the services tests."""
import json
from pathlib import Path

import pytest

FLEET = Path(__file__).resolve().parents[2] / "fleet" / "blueprints"


@pytest.fixture()
def ats() -> dict:
    """The standing ATS fixture — a fully populated Living Blueprint.

    Read fresh per test. Tests mutate it (recording decisions raises
    confidence), and a shared instance would make results depend on test order.
    """
    return json.loads((FLEET / "ats-live.json").read_text("utf-8"))
