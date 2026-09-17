"""Smith is handed the attached file, because it can never name one.

A logo is the one thing a verb needs that the MODEL cannot supply. It sees
"Attached file: logo.png" in its content blocks and never the id the file is
stored under, so an `attachment_id` argument would be a field it had to invent.
The loop — the only layer that knows what came in with the turn — hands the
records to `set_logo` instead (`smith_tools.TURN_FILE_TOOLS`).

Everything that can go wrong with that is a sentence, not a silence: nothing
attached, several images attached, a file that has gone. None of them guesses.
"""
import io
import json
import zlib

import pytest
from PIL import Image

from services import smith_tools
from services.blueprint.service import BlueprintService


def _png(size=(96, 32)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 170, 120)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def output_dir(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="APP-1",
                                  name="Bright Care", domain="care")
    svc.doc["designSystem"] = {"colors": {"primary": "#0a7"}}
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Home", "route": "/home",
                         "purpose": "where the day starts", "access": "authenticated"}]
    svc.doc["navigation"] = {"tree": [{"label": "Home", "page": "PAGE-001"}]}
    svc.save()
    return str(tmp_path)


def _attached(tmp_path, name="logo.png", data=None, kind="image",
              media="image/png"):
    """One record in the shape `chat_attachments.locate` returns."""
    p = tmp_path / f"attach-{name}"
    p.write_bytes(data if data is not None else _png())
    return {"id": "a" * 32, "filename": name, "kind": kind,
            "media_type": media, "bytes": p.stat().st_size, "path": str(p)}


def test_the_attached_image_becomes_the_application_s_mark(output_dir, tmp_path):
    out = smith_tools.READONLY_HANDLERS["set_logo"](
        output_dir, {"files": [_attached(tmp_path)], "alt": "Bright Care"})

    assert out["applied"], out.get("reason")
    doc = BlueprintService.load(output_dir=output_dir).doc
    assert doc["designSystem"]["logo"]["alt"] == "Bright Care"
    shell = json.loads((tmp_path / "app/src/schemas/shell.json").read_text())
    assert shell["children"][0]["props"]["logoSrc"].startswith("/brand/")


def test_nothing_attached_asks_for_the_file(output_dir):
    out = smith_tools.READONLY_HANDLERS["set_logo"](output_dir, {"files": []})
    assert out["applied"] is False
    assert "attach" in out["reason"].lower()
    assert BlueprintService.load(output_dir=output_dir).doc["designSystem"].get("logo") is None


def test_a_pdf_on_the_turn_is_not_an_image_to_use(output_dir, tmp_path):
    """The kind is read off the record the composer already classified, so a
    spec attached alongside the ask is not mistaken for the mark."""
    out = smith_tools.READONLY_HANDLERS["set_logo"](
        output_dir, {"files": [_attached(tmp_path, "spec.pdf", b"%PDF-1.4",
                                         kind="pdf", media="application/pdf")]})
    assert out["applied"] is False and "attach" in out["reason"].lower()


def test_several_images_are_asked_about_rather_than_guessed(output_dir, tmp_path):
    files = [_attached(tmp_path, "one.png"), _attached(tmp_path, "two.png")]
    out = smith_tools.READONLY_HANDLERS["set_logo"](output_dir, {"files": files})
    assert out["applied"] is False
    assert "one.png" in out["reason"] and "two.png" in out["reason"]


def test_a_file_that_has_gone_says_so_rather_than_crashing(output_dir, tmp_path):
    rec = _attached(tmp_path)
    (tmp_path / f"attach-logo.png").unlink()
    out = smith_tools.READONLY_HANDLERS["set_logo"](output_dir, {"files": [rec]})
    assert out["applied"] is False and out["edited_paths"] == []


def test_removing_is_its_own_tool_and_takes_nothing(output_dir, tmp_path):
    smith_tools.READONLY_HANDLERS["set_logo"](
        output_dir, {"files": [_attached(tmp_path)]})
    out = smith_tools.READONLY_HANDLERS["remove_logo"](output_dir, {})
    assert out["applied"], out.get("reason")
    assert BlueprintService.load(output_dir=output_dir).doc["designSystem"].get("logo") is None


def test_the_loop_knows_which_tools_want_the_turn_s_files():
    """If this frozenset stops naming `set_logo`, the dispatch in
    `agents/smith_agent.py` stops passing the files and the tool silently asks
    for an attachment the person already sent."""
    assert "set_logo" in smith_tools.TURN_FILE_TOOLS
    assert all(name in smith_tools.READONLY_HANDLERS
               for name in smith_tools.TURN_FILE_TOOLS)


def test_both_logo_verbs_are_dispatchable():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
    for verb in ("set_logo", "remove_logo"):
        assert verb in REQUIRED_BY_VERB and verb in VERB_HELP
        assert REQUIRED_BY_VERB[verb] == set(), (
            "neither takes a field: the file is the request")
        assert verb in smith_tools.READONLY_HANDLERS
