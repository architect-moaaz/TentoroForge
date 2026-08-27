"""Spec E Wave 2 — accessibility_audit unit tests (heuristic mode).

The axe-runner path requires Node + a headless browser we can't rely
on in CI; these tests exercise the pure-Python fallback that walks
emitted schemas + shell TSX for obvious a11y gaps.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.accessibility_audit import run_axe_audit


def _stub_output(tmp_path: Path, *, with_skip_link: bool, with_main: bool) -> Path:
    root = tmp_path / "app"
    (root / "src" / "app").mkdir(parents=True, exist_ok=True)
    (root / "src" / "lib").mkdir(parents=True, exist_ok=True)
    (root / "src" / "schemas").mkdir(parents=True, exist_ok=True)

    layout = (
        'import { SkipLink } from "@tentoroforge/library";'
        if with_skip_link
        else "// bare layout — no a11y primitives"
    )
    (root / "src" / "app" / "layout.tsx").write_text(layout, encoding="utf-8")

    schema_page = "<main id=\"main\">x</main>" if with_main else "<div>x</div>"
    (root / "src" / "lib" / "schema-page.tsx").write_text(schema_page, encoding="utf-8")

    # An image with no alt — should be flagged.
    (root / "src" / "schemas" / "home.json").write_text(
        json.dumps({
            "component": "Section",
            "children": [
                {"component": "Image", "props": {"src": "/foo.png"}},
                {"component": "IconButton", "props": {}},
            ],
        }),
        encoding="utf-8",
    )
    return root


def test_heuristic_flags_missing_skip_link_and_landmark(tmp_path):
    out = _stub_output(tmp_path, with_skip_link=False, with_main=False)
    result = run_axe_audit(str(out), urls=[], write_report=True)
    assert result["ok"] is True
    assert result["engine"] == "heuristic"
    violations = result["pages"][0]["violations"]
    rules = {v["rule"] for v in violations}
    assert "landmark-main" in rules
    assert "skip-link" in rules


def test_heuristic_flags_image_without_alt(tmp_path):
    out = _stub_output(tmp_path, with_skip_link=True, with_main=True)
    result = run_axe_audit(str(out), urls=[], write_report=False)
    violations = result["pages"][0]["violations"]
    rules = {v["rule"] for v in violations}
    assert "image-alt" in rules
    assert "button-name" in rules  # IconButton missing aria-label


def test_heuristic_clean_shell_reports_no_shell_gaps(tmp_path):
    out = _stub_output(tmp_path, with_skip_link=True, with_main=True)
    # remove the noisy page schema so we can assert cleanliness
    (out / "src" / "schemas" / "home.json").unlink()
    result = run_axe_audit(str(out), urls=[], write_report=False)
    violations = result["pages"][0]["violations"]
    rules = {v["rule"] for v in violations}
    assert "landmark-main" not in rules
    assert "skip-link" not in rules


def test_writes_report_to_verify_run_directory(tmp_path):
    out = _stub_output(tmp_path, with_skip_link=True, with_main=True)
    run_axe_audit(str(out), urls=[], write_report=True)
    report_path = out / "verify-run" / "accessibility.json"
    assert report_path.is_file()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["engine"] == "heuristic"
    assert "pages" in data
