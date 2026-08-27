"""NT-2 — Smith's edit_page dispatch handler delegates to
services.llm_edit.smart_edit_page (not the old JSON-Patch applier)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from services.smith_tools import TOOL_CATALOG, READONLY_HANDLERS


def _catalog(name: str) -> dict | None:
    return next((t for t in TOOL_CATALOG if t["name"] == name), None)


def test_edit_page_signature_is_path_and_intent():
    entry = _catalog("edit_page")
    assert entry is not None, "edit_page missing from catalog"
    sig = entry["signature"]
    assert "path" in sig
    assert "intent" in sig
    # The old JSON-Patch signature must NOT appear — no `patch` arg.
    assert "patch)" not in sig
    assert "RFC-6902" not in entry["desc"]


def test_edit_page_handler_routes_to_smart_edit(tmp_path):
    handler = READONLY_HANDLERS["edit_page"]
    with patch("services.llm_edit.smart_edit_page") as m:
        m.return_value = {
            "applied": True, "edited_paths": ["src/schemas/x.json"],
            "diff_summary": "…", "model": "canned",
        }
        result = handler(str(tmp_path), {
            "path": "src/schemas/x.json",
            "intent": "change CV Upload to FileUpload",
        })
    assert result["applied"] is True
    assert m.call_count == 1
    kw = m.call_args.kwargs
    assert kw["target_path"] == "src/schemas/x.json"
    assert "CV Upload" in kw["intent"]


def test_edit_page_handler_rejects_missing_intent(tmp_path):
    handler = READONLY_HANDLERS["edit_page"]
    r = handler(str(tmp_path), {"path": "src/schemas/x.json"})
    assert r["applied"] is False
    assert "intent" in r["reason"].lower()


def test_edit_page_handler_rejects_empty_intent(tmp_path):
    handler = READONLY_HANDLERS["edit_page"]
    r = handler(str(tmp_path), {"path": "src/schemas/x.json", "intent": "   "})
    assert r["applied"] is False


def test_edit_page_handler_rejects_missing_path(tmp_path):
    handler = READONLY_HANDLERS["edit_page"]
    r = handler(str(tmp_path), {"intent": "do the thing"})
    assert r["applied"] is False
