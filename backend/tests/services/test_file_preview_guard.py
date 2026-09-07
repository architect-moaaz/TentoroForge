"""Tests for services.file_preview_guard — no recursive-app iframes."""
from __future__ import annotations

import json
from pathlib import Path

from services.file_preview_guard import apply_file_preview_guard


def _mk_app(tmp_path: Path, html: str, *, preview_route: bool = True) -> Path:
    root = tmp_path / "app"
    p = root / "src" / "schemas" / "documents" / "[id].json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"root": {"type": "Stack", "children": [
        {"type": "CustomBlock", "props": {"html": html,
                                          "label": "PDF Viewer"}}]}}),
                 encoding="utf-8")
    if preview_route:
        (root / "src" / "app" / "api" / "files" / "preview").mkdir(
            parents=True, exist_ok=True)
    return root


def _html(root: Path) -> str:
    p = root / "src" / "schemas" / "documents" / "[id].json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    return doc["root"]["children"][0]["props"]["html"]


_NAIVE = ('<iframe src="{{document.filePath}}" '
          'style="width: 100%; height: 600px; border: none;"></iframe>')


def test_naive_iframe_rewritten_to_object_via_preview_route(tmp_path: Path):
    """The atb0m97x case: bound iframe → object + preview route + fallback."""
    root = _mk_app(tmp_path, _NAIVE)
    rep = apply_file_preview_guard(root)
    html = _html(root)
    assert "<iframe" not in html
    assert 'type="application/pdf"' in html
    assert "/api/files/preview?src={{document.filePath}}" in html
    assert "Inline preview unavailable" in html
    assert rep["summary"]["rewritten"] == 1


def test_no_preview_route_keeps_direct_binding(tmp_path: Path):
    root = _mk_app(tmp_path, _NAIVE, preview_route=False)
    apply_file_preview_guard(root)
    html = _html(root)
    assert "<iframe" not in html
    assert '<object data="{{document.filePath}}"' in html


def test_idempotent_rerun(tmp_path: Path):
    root = _mk_app(tmp_path, _NAIVE)
    apply_file_preview_guard(root)
    rep2 = apply_file_preview_guard(root)
    assert rep2["summary"]["rewritten"] == 0


def test_static_iframe_untouched(tmp_path: Path):
    """An iframe with a literal (non-binding) src is intentional — leave it."""
    html = '<iframe src="https://maps.example.com/embed"></iframe>'
    root = _mk_app(tmp_path, html)
    rep = apply_file_preview_guard(root)
    assert _html(root) == html
    assert rep["summary"]["rewritten"] == 0


def test_reference_pattern_untouched(tmp_path: Path):
    """The safe object pattern the reference app ships must pass through."""
    html = ('<object data="/api/files/preview?src={{document.fileUrl}}" '
            'type="application/pdf"><div>Inline preview unavailable'
            "</div></object>")
    root = _mk_app(tmp_path, html)
    rep = apply_file_preview_guard(root)
    assert _html(root) == html
    assert rep["summary"]["rewritten"] == 0


def test_missing_schemas_dir_no_crash(tmp_path: Path):
    assert apply_file_preview_guard(tmp_path / "nope")["summary"] \
        == {"rewritten": 0}
