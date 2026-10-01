"""One language switch, in the frame — Test2 (2026-09-28).

Asked for English and Hindi, every page rolled its own EN/हिं toggle, none
agreed with the next, and nothing loaded a font that draws Devanagari.
Held here: the Blueprint declares the languages; the app gets them as one
projected list, one switch in its frame, a face for each script, and a page
writer told to write every string in each and never draw a switch.
"""
from __future__ import annotations

from pathlib import Path

from services.blueprint import languages as lang
from services.blueprint.projection import project_design_tokens
from services.blueprint.ui_engineer import system_prompt

TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src"


def _doc(locale="en", others=()):
    return {"application": {"name": "Areas"}, "product": {"locale": locale, "languages": list(others)},
            "designSystem": {"colors": {"primary": "#1f6feb"}, "typography": {"fontFamilyBase": "Inter"}}}


def test_the_languages_are_the_primary_then_each_other_once():
    assert lang.languages(_doc("en", ["hi", "hi-IN", "en"])) == ["en", "hi"]
    assert lang.languages({"product": {}}) == ["en"]


def test_the_app_gets_one_list_of_its_languages(tmp_path):
    out = lang.project_languages(_doc("en", ["hi", "ar"]), tmp_path)
    text = (tmp_path / "src/lib/languages.ts").read_text()
    assert out["files"] == ["src/lib/languages.ts"]
    assert 'export const PRIMARY: string = "en"' in text
    assert '"tag": "hi"' in text and '"tag": "ar"' in text and '"dir": "rtl"' in text
    assert lang.project_languages(_doc("en", ["hi", "ar"]), tmp_path)["files"] == []   # unchanged, unwritten


def test_each_script_gets_a_face_that_draws_it(tmp_path):
    project_design_tokens(_doc("en", ["hi"]), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert "family=Noto+Sans+Devanagari" in css and "family=Inter" in css
    assert ':lang(hi), :lang(hi) h1' in css and 'font-family: "Noto Sans Devanagari"' in css
    project_design_tokens(_doc("en"), tmp_path)
    assert "Noto" not in (tmp_path / "src/app/tokens.css").read_text()


def test_the_page_writer_writes_every_string_in_each_and_draws_no_switch():
    prompt = system_prompt(_doc("en", ["hi"]))
    assert "# Its language" in prompt and "useT()" in prompt and "Never write a language switch" in prompt
    assert "# Its language" not in system_prompt(_doc("en"))
    assert "written in `ar`" in system_prompt(_doc("ar"))


def test_the_frame_holds_the_one_switch():
    assert "export function LanguageSwitch" in (TEMPLATES / "sdk/i18n.tsx").read_text()
    for frame in ("app/(dashboard)/layout.tsx", "components/PublicPageFrame.tsx"):
        text = (TEMPLATES / frame).read_text()
        assert 'import { LanguageSwitch } from "@/sdk/i18n"' in text and "<LanguageSwitch" in text, frame


def test_the_language_list_belongs_to_the_projection():
    from services.blueprint.assembly import PROJECTED_PATHS
    assert "src/lib/languages.ts" in PROJECTED_PATHS


def test_a_language_added_is_projected_and_the_screens_still_to_rewrite_are_said(tmp_path, monkeypatch):
    import json as _json
    from services.blueprint.service import BlueprintService
    from services.smith import definition_change as dc
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Areas", domain="places")
    svc.save()
    reply = {"name": "Areas", "description": "", "objectives": [], "locale": "en", "languages": ["hi"],
             "changed": ["languages"]}
    out = dc.edit_product(svc, "show it in Hindi too", app_root=str(tmp_path / "app"),
                          client=lambda **k: _json.dumps(reply))
    assert svc.doc["product"]["languages"] == ["hi"]
    assert "src/lib/languages.ts" in out["edited_paths"] and "src/app/tokens.css" in out["edited_paths"]
    said = dc.summary_of("edit_product", out)
    assert "switch is in the application's frame" in said and "rewrite" in said
