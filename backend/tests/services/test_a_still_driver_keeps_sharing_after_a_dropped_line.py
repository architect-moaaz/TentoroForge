"""A driver whose connection dropped keeps sharing once it is back, even while standing still.

Notes that could not go out were retried only when a NEW GPS reading arrived. A phone that is not moving gives none, so
after a dropped connection nothing was sent again and the driver left the live map after two minutes of silence
(found testing a built ride-hailing app). The share hook now retries while notes wait, retries when the browser says it is
online, and says "still here" with the last known spot before the line reads as lost."""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SDK = (BACKEND / "templates" / "app-foundation" / "src" / "sdk" / "tracking.tsx").read_text(encoding="utf-8")
HUB = (BACKEND / "templates" / "runtime" / "tracking" / "hub.ts").read_text(encoding="utf-8")


def _num(name: str, text: str) -> int:
    return int(re.search(rf"{name}\s*=\s*([\d_]+)", text).group(1).replace("_", ""))


def test_failed_notes_are_retried_without_waiting_for_a_new_reading():
    assert "window.setInterval(" in SDK and "if (queue.length) { void run(); return; }" in SDK
    assert 'window.addEventListener("online", backOnline)' in SDK
    assert "window.clearInterval(beat)" in SDK and 'window.removeEventListener("online", backOnline)' in SDK


def test_a_still_driver_says_still_here_before_the_line_reads_as_lost():
    assert "STILL_HERE_MS" in SDK and "lastNote" in SDK
    # the heartbeat must come well inside the time after which a quiet line is called lost
    assert _num("STILL_HERE_MS", SDK) < _num("STALE_MS", HUB)
    assert _num("STILL_HERE_MS", SDK) < _num("FLEET_TTL_MS", HUB)
    assert _num("RETRY_MS", SDK) < _num("STILL_HERE_MS", SDK)
