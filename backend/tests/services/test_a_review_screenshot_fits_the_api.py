"""wz7a99ir (local, 2026-10-04): the build's page reviewer sent a long admin
list's full-page screenshot, the API refused it ("At least one of the image
dimensions exceed max allowed size: 8000 pixels"), and the page's first
attempt died on the 400. Both shooters cap the height under the limit."""
import struct
from pathlib import Path

import pytest

from services.blueprint import page_look

ROOT = Path(__file__).resolve().parents[2]


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return struct.unpack(">II", head[16:24])


def test_both_shooters_cap_the_height_under_the_apis_limit():
    assert page_look.MAX_SHOT_PX < 8000
    shots = (ROOT / "scripts/page_shots.mjs").read_text()
    assert "const MAX_SHOT_PX = 7800;" in shots and "Math.min(Math.max(tall, viewport.height), MAX_SHOT_PX)" in shots
    look = (ROOT / "services/blueprint/page_look.py").read_text()
    assert '"height": min(max(tall, h), MAX_SHOT_PX)' in look


@pytest.mark.parametrize("content_px,expected", [(12000, page_look.MAX_SHOT_PX), (300, 900)])
def test_a_long_page_is_cut_and_a_short_one_is_a_screen(tmp_path, content_px, expected):
    sync = pytest.importorskip("playwright.sync_api")
    try:
        with sync.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            tab = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
            tab.set_content(f'<body style="margin:0"><div style="height:{content_px}px;background:#eee"></div></body>')
            tall = int(tab.evaluate("document.documentElement.scrollHeight") or 900)
            file = tmp_path / "shot.png"
            tab.screenshot(path=str(file), full_page=True,
                           clip={"x": 0, "y": 0, "width": 1280, "height": min(max(tall, 900), page_look.MAX_SHOT_PX)})
            browser.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Chromium here: {exc}")
    assert _png_size(file) == (1280, expected)
