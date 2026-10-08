"""forge-v3, 2026-09-27: "Add a child" saved every child and "My Children"
showed none — the SDK's list read failed on "Unknown entity: Child" and
returned [] in silence, so every check saw a tidy empty page. The shipped
`src/sdk/server.ts` is run by its own suite (`run-swallowed-tests.sh`)."""
import re
import subprocess
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def test_the_shipped_sdk_says_a_read_that_failed():
    out = subprocess.run(["bash", str(TEMPLATES / "runtime/__tests__/run-swallowed-tests.sh")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-1500:]


def test_the_checks_count_a_swallowed_read_as_the_server_saying_something_failed():
    from services.smith.trials import _SERVER_ERROR
    assert _SERVER_ERROR.search("[forge:swallowed] list Child failed: Unknown entity: Child")
