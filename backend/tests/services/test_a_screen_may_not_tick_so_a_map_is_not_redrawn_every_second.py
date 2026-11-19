"""Found on the emulator: the generated driver screen kept a `now` it set from a one-second `setInterval`. A map screen is heavy,
so every tick redrew the map, the sheet and the panels, a slow phone fell behind and drew without rest (the JS thread sat at
100% and the screen never left its loading sheet). Clocks now live in the kit's small parts, and a screen with a timer of its
own is refused."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import native_engineer

NATIVE = Path(__file__).resolve().parents[2] / "templates" / "native"
PAGE = {"id": "PAGE-001", "name": "Home", "route": "/", "pattern": "dashboard"}
DOC = {"application": {"name": "A"}, "pages": [PAGE], "workflows": []}


def test_a_screen_with_a_timer_of_its_own_is_sent_back():
    ticking = "const [now, setNow] = useState(0);\nuseEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); }, []);"
    text = " ".join(native_engineer._page_findings(DOC, PAGE, ticking))
    assert "setInterval" in text and "Countdown" in text and "useExpired" in text
    assert not [f for f in native_engineer._page_findings(DOC, PAGE, "export default function S() { return null; }") if "setInterval" in f]


def test_the_kit_has_the_clocks_a_screen_needs_and_the_guide_says_not_to_tick():
    clock = (NATIVE / "src" / "ui" / "Clock.tsx").read_text(encoding="utf-8")
    assert "export function Countdown" in clock and "export function Elapsed" in clock and "export function useExpired" in clock
    index = (NATIVE / "src" / "ui" / "index.ts").read_text(encoding="utf-8")
    assert "Countdown, Elapsed, useExpired" in index
    assert "NEVER TICK IN A SCREEN" in (NATIVE / "README.md").read_text(encoding="utf-8")
    assert "NEVER keep a ticking clock" in native_engineer.MAP_FIRST_RULES


def test_a_number_formatter_is_made_once_not_on_every_render():
    # found in the same profile: Hermes spends milliseconds on each `new Intl.NumberFormat`, and every Money on a screen built one per draw
    fmt = (NATIVE / "src" / "sdk" / "format.ts").read_text(encoding="utf-8")
    assert "const formatters = new Map" in fmt
    assert fmt.count("new Intl.NumberFormat") == 1
