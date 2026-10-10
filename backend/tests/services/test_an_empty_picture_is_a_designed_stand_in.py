"""Ecom L1 (2026-10-11): image fields are seeded empty on purpose, and every
product and category card showed a bare image box with its alt text. The
SDK's Picture shows the stored picture, or a designed stand-in; the writer
is told to use it; the reviewer treats a broken picture as high severity."""
from pathlib import Path

from services.blueprint import app_sdk, page_review, ui_engineer

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "sdk" / "picture.tsx"


def test_the_sdk_ships_and_exports_picture():
    src = TEMPLATE.read_text("utf-8")
    assert "export function Picture" in src and "fileUrl(src)" in src
    assert 'role="img"' in src and "onError" in src, "a stand-in when empty, and when the picture fails"
    assert 'export * from "./picture";' in app_sdk.emit_index()


def test_the_page_writer_is_told_to_use_it_and_the_reviewer_to_refuse_a_bare_img():
    notes = ui_engineer.SDK_NOTES if hasattr(ui_engineer, "SDK_NOTES") else open(ui_engineer.__file__, encoding="utf-8").read()
    assert "<Picture src={row.x}" in notes and "Never a bare <img>" in notes
    system = page_review.__file__ and open(page_review.__file__, encoding="utf-8").read()
    assert "shows only its alt text" in system and "high-severity" in system


def test_live_refresh_opens_the_stream_only_when_it_is_its_own():
    """Ecom L1 (2026-10-11): the gated stream, opened signed out, answered the
    sign-in page; EventSource logged a MIME error on every public screen,
    and the trials counted it against every control."""
    src = (TEMPLATE.parent.parent / "lib" / "LiveRefresh.tsx").read_text("utf-8")
    assert "streamIsOurs" in src and 'includes("text/event-stream")' in src
    assert 'new EventSource(STREAM_URL)' in src and "NEXT_PUBLIC_BASE_PATH" in src
    assert 'new EventSource("/api/events/stream")' not in src
