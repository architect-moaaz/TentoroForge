"""The page composer looks at the montage, not just the paragraph.

Before this, nine reference screens were read once by a vision call,
compressed to ~15 lines of prose, and the images dropped. Everything
downstream saw only the prose. These tests pin the new path: the images
reach the model, they change the cache identity, and every way of not
having them degrades to the old behaviour rather than failing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from schemas.design_brief import VisualLock
from services import page_composer, page_composer_pipeline as pcp


def _img(data: str = "AAAA", media: str = "image/png") -> dict:
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": data}}


def _label(text: str = "Reference 1") -> dict:
    """The attachment loader emits one of these before each image."""
    return {"type": "text", "text": text}


class _Vocab:
    """Stand-in for an ArchetypeVocabulary in the cheap tests.

    The prompt-block tests below use the real model instead — the
    summarizer reads more of it than is worth stubbing.
    """
    id = "v"

    def model_dump(self):
        return {"id": self.id}


def _real_vocab():
    from services.archetype_vocabulary import ArchetypeVocabulary
    return ArchetypeVocabulary(id="banking-platform")


class _Preset:
    preset_name = "p"

    def model_dump(self):
        return {"preset_name": self.preset_name}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(pcp.VISION_ENV, raising=False)
    pcp._reset_manifest_cache_for_tests()
    page_composer._reset_cache_for_tests()
    yield
    pcp._reset_manifest_cache_for_tests()
    page_composer._reset_cache_for_tests()


# ── cache identity ──────────────────────────────────────────────────

class TestCacheKey:
    def _key(self, images):
        return page_composer.cache_key(
            {"route": "/x", "kind": "list"}, {}, _Vocab(), _Preset(),
            {"components": {"Table": {}}}, reference_images=images,
        )

    def test_images_change_the_key(self):
        """Otherwise a prose-only result would be served to a vision run
        and the A/B would compare a thing against itself."""
        assert self._key(None) != self._key([_img()])

    def test_different_montages_differ(self):
        assert self._key([_img("AAAA")]) != self._key([_img("BBBB")])

    def test_same_montage_is_stable(self):
        assert self._key([_img("AAAA")]) == self._key([_img("AAAA")])

    def test_image_count_matters(self):
        assert self._key([_img()]) != self._key([_img(), _img()])

    def test_a_changed_label_changes_the_key(self):
        """The loader labels each screen; relabelling is a reference change."""
        assert (self._key([_label("Reference 1"), _img()])
                != self._key([_label("Homepage"), _img()]))

    def test_empty_list_is_the_same_as_none(self):
        """No images is no images, however it's spelled."""
        assert self._key([]) == self._key(None)


# ── the images actually reach the model ─────────────────────────────

class TestImagesReachTheCall:
    @pytest.mark.asyncio
    async def test_images_lead_the_message_content(self, monkeypatch):
        seen: dict = {}

        class _Msgs:
            async def create(self, **kw):
                seen.update(kw)
                raise RuntimeError("stop after capture")

        class _Client:
            messages = _Msgs()

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        import services.llm_client as lc
        monkeypatch.setattr(lc, "AsyncAnthropic", lambda **kw: _Client())

        with pytest.raises(RuntimeError):
            await page_composer._call_llm(
                "PROMPT", model="m", timeout_s=5,
                images=[_label(), _img()])   # loader's real shape

        content = seen["messages"][0]["content"]
        assert isinstance(content, list), "images must make content a block list"
        assert content[-1] == {"type": "text", "text": "PROMPT"}, \
            "the instruction must come last, after the screens"
        assert any(b.get("type") == "image" for b in content[:-1]), \
            "at least one screen must precede the instruction"

    @pytest.mark.asyncio
    async def test_no_images_keeps_plain_string_content(self, monkeypatch):
        """The old shape stays byte-identical when there's no montage."""
        seen: dict = {}

        class _Msgs:
            async def create(self, **kw):
                seen.update(kw)
                raise RuntimeError("stop")

        class _Client:
            messages = _Msgs()

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        import services.llm_client as lc
        monkeypatch.setattr(lc, "AsyncAnthropic", lambda **kw: _Client())

        with pytest.raises(RuntimeError):
            await page_composer._call_llm("PROMPT", model="m", timeout_s=5)
        assert seen["messages"][0]["content"] == "PROMPT"


# ── loading them from the app dir ───────────────────────────────────

def _app(tmp_path: Path, reference: dict | None) -> Path:
    root = tmp_path / "app"
    (root / "src" / "contracts").mkdir(parents=True)
    if reference is not None:
        (root / "src" / "contracts" / "composition-reference.json").write_text(
            json.dumps(reference), encoding="utf-8")
    return root


class TestLoadReferenceImages:
    def test_loads_blocks_for_the_recorded_project(self, tmp_path, monkeypatch):
        root = _app(tmp_path, {"layout": "x", "project_id": "proj-1"})
        monkeypatch.setattr("services.chat_attachments.attachments_root",
                            lambda: str(tmp_path))
        monkeypatch.setattr("services.design_reference.load_design_reference_blocks",
                            lambda _root, pid: [_img()] if pid == "proj-1" else [])
        assert len(pcp._load_reference_images(root)) == 1

    def test_reference_without_project_id_yields_nothing(self, tmp_path):
        """The built-in default reference has no montage behind it."""
        root = _app(tmp_path, {"layout": "x", "source": "built-in"})
        assert pcp._load_reference_images(root) == []

    def test_missing_reference_yields_nothing(self, tmp_path):
        assert pcp._load_reference_images(_app(tmp_path, None)) == []

    def test_attachment_store_failure_degrades(self, tmp_path, monkeypatch):
        root = _app(tmp_path, {"project_id": "proj-1"})
        def _boom(*a, **k):
            raise RuntimeError("store down")
        monkeypatch.setattr("services.design_reference.load_design_reference_blocks", _boom)
        assert pcp._load_reference_images(root) == []

    def test_flag_off_skips_loading_entirely(self, tmp_path, monkeypatch):
        root = _app(tmp_path, {"project_id": "proj-1"})
        called = {"n": 0}
        def _count(*a, **k):
            called["n"] += 1
            return [_img()]
        monkeypatch.setattr("services.design_reference.load_design_reference_blocks", _count)
        monkeypatch.setenv(pcp.VISION_ENV, "0")
        assert pcp._load_reference_images(root) == []
        assert called["n"] == 0, "flag off must not even reach the store"

    @pytest.mark.parametrize("val", ["0", "false", "no", "off", "OFF"])
    def test_off_vocabulary(self, val, monkeypatch):
        monkeypatch.setenv(pcp.VISION_ENV, val)
        assert pcp._vision_enabled() is False

    @pytest.mark.parametrize("val", ["", "1", "true", "yes", "anything"])
    def test_on_by_default_and_for_anything_else(self, val, monkeypatch):
        monkeypatch.setenv(pcp.VISION_ENV, val)
        assert pcp._vision_enabled() is True


# ── end to end through the pipeline ─────────────────────────────────

class TestPipelineThreading:
    def test_composer_receives_the_images(self, tmp_path, monkeypatch):
        root = _app(tmp_path, {"project_id": "proj-1"})
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps({"pages": []}), encoding="utf-8")

        monkeypatch.setenv(pcp.FLAG_ENV, "1")
        monkeypatch.setattr(pcp, "_get_library_manifest",
                            lambda: {"components": {"Table": {}}})
        monkeypatch.setattr(pcp, "_load_vocab_and_preset",
                            lambda *a, **k: (_Vocab(), _Preset()))
        monkeypatch.setattr("services.chat_attachments.attachments_root",
                            lambda: str(tmp_path))
        monkeypatch.setattr("services.design_reference.load_design_reference_blocks",
                            lambda _r, _p: [_img(), _img("BBBB")])

        got: dict = {}

        async def _capture(page, plan, vocab, preset, manifest, **kw):
            got["images"] = kw.get("reference_images")
            return {"root": {"type": "Stack"}}, {"source": "composed", "changes": {}}

        monkeypatch.setattr(pcp, "compose_page", _capture)
        schema, prov = pcp.compose_page_via_pipeline_sync(
            {"route": "/x", "kind": "list"}, {}, root)

        assert prov["source"] == "composed"
        assert got["images"] is not None and len(got["images"]) == 2

    def test_no_montage_falls_back_to_the_curated_reference(self, tmp_path, monkeypatch):
        """Before the fixtures were wired, this case composed on prose
        alone — which was every build, since designating a montage is
        rare. Now the page kind picks a curated screen instead."""
        root = _app(tmp_path, {"source": "built-in"})
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
        monkeypatch.setenv(pcp.FLAG_ENV, "1")
        monkeypatch.setattr(pcp, "_get_library_manifest",
                            lambda: {"components": {"Table": {}}})
        monkeypatch.setattr(pcp, "_load_vocab_and_preset",
                            lambda *a, **k: (_Vocab(), _Preset()))

        got: dict = {}

        async def _capture(page, plan, vocab, preset, manifest, **kw):
            got["images"] = kw.get("reference_images")
            return {"root": {}}, {"source": "composed", "changes": {}}

        monkeypatch.setattr(pcp, "compose_page", _capture)
        pcp.compose_page_via_pipeline_sync({"route": "/x", "kind": "list"}, {}, root)
        assert got["images"], "a list page should still get the list reference"
        assert any(b["type"] == "image" for b in got["images"])

    def test_a_kind_with_no_reference_composes_on_prose_alone(self, tmp_path, monkeypatch):
        """The old no-images path still exists and still works."""
        root = _app(tmp_path, {"source": "built-in"})
        (root / "src" / "contracts" / "plan.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
        monkeypatch.setenv(pcp.FLAG_ENV, "1")
        monkeypatch.setattr(pcp, "_get_library_manifest",
                            lambda: {"components": {"Table": {}}})
        monkeypatch.setattr(pcp, "_load_vocab_and_preset",
                            lambda *a, **k: (_Vocab(), _Preset()))

        got: dict = {}

        async def _capture(page, plan, vocab, preset, manifest, **kw):
            got["images"] = kw.get("reference_images")
            return {"root": {}}, {"source": "composed", "changes": {}}

        monkeypatch.setattr(pcp, "compose_page", _capture)
        pcp.compose_page_via_pipeline_sync(
            {"route": "/settings", "kind": "settings"}, {}, root)
        assert not got["images"]


# ── the prompt names them ───────────────────────────────────────────

class TestPromptBlock:
    def _prompt(self, has_images: bool) -> str:
        return page_composer._build_prompt(
            {"route": "/x", "kind": "list", "entity": "Booking"}, {},
            _real_vocab(), VisualLock(), {"components": {"Table": {}}},
            patterns=None, variance_seed=None, brief=None,
            has_reference_images=has_images,
        )

    def test_reference_block_appears_with_images(self):
        """Unannounced images read as decoration; the model composes from
        the text and nothing changes."""
        assert "REFERENCE DESIGN" in self._prompt(True)

    def test_no_block_without_images(self):
        assert "REFERENCE DESIGN" not in self._prompt(False)

    def test_block_scopes_them_to_layout_not_content(self):
        """Copying labels off a montage is the failure mode to avoid —
        the reference is someone else's product."""
        p = self._prompt(True).lower()
        assert "layout" in p and "not the content" in p


# ── built-in curated references ─────────────────────────────────────

class TestBuiltinReferences:
    """Almost no project uploads a montage, so this is the path that
    actually runs. The fixtures were already in the repo, read only by
    the fidelity scorer — grading pages against a bar the composer had
    never been shown."""

    def _resolve(self, kind: str, domain: str = "saas", designated=None):
        return pcp._reference_images_for(
            {"reference_images": designated}, {"kind": kind}, {"domain": domain})

    def test_list_page_gets_a_list_reference(self):
        blocks = self._resolve("list")
        assert [b["type"] for b in blocks] == ["text", "image"]
        assert "list" in blocks[0]["text"]
        assert blocks[1]["source"]["data"], "image must carry base64 payload"

    @pytest.mark.parametrize("kind,expected", [
        ("collection", "list"), ("record", "detail"), ("create", "form"),
        ("edit", "form"), ("dashboard", "dashboard"), ("signup", "login"),
    ])
    def test_kind_aliases_map_to_the_right_reference(self, kind, expected):
        assert expected in self._resolve(kind)[0]["text"]

    def test_unmapped_kind_gets_nothing(self):
        """A wrong reference is worse than none — the model is told to
        follow whatever it is shown."""
        assert self._resolve("settings") == []
        assert self._resolve("kanban") == []

    def test_domain_resolution_is_the_scorers(self):
        """Author-time and score-time must never disagree about which
        reference applies, so both go through normalize_domain."""
        from services.fidelity_scorer import normalize_domain
        assert normalize_domain("E-Commerce & Retail") == "ecommerce"
        assert self._resolve("list", domain="E-Commerce & Retail") != []

    def test_unknown_domain_still_resolves(self):
        assert self._resolve("list", domain="underwater basket weaving") != []

    def test_a_designated_montage_wins(self):
        """The project's own designer chose it; a stock fixture doesn't
        get to override that."""
        mine = [_img("MINE")]
        assert self._resolve("list", designated=mine) == mine

    def test_flag_off_suppresses_the_builtin_too(self, monkeypatch):
        monkeypatch.setenv(pcp.VISION_ENV, "0")
        assert self._resolve("list") == []

    def test_recipe_form_is_absent_and_degrades(self):
        """index.json documents form.png as not yet curated for recipe."""
        assert self._resolve("form", domain="recipe") == []

    def test_repeated_lookups_reuse_the_decode(self):
        """~600 KB of base64 per screen; decoding once per page on an
        85-page app would be pure waste."""
        pcp._builtin_reference_block.cache_clear()
        self._resolve("list"); self._resolve("list"); self._resolve("list")
        assert pcp._builtin_reference_block.cache_info().hits >= 2


# ── per-row templates are not dataSource bindings ───────────────────

class TestPerRowTemplateExemption:
    """`{{id}}` in a rowAction navigate is resolved against the ROW by
    Table.applyTemplate, whose regex accepts both `{id}` and `{{id}}`.
    The validator read it as a dataSource reference and failed the page —
    and a failed composition is discarded wholesale, so list and detail
    pages fell back to the deterministic composer."""

    def _validate(self, root, sources=("products",)):
        return page_composer._validate_page_schema(
            {"schemaVersion": "2", "id": "p", "route": "/products", "root": root,
             "dataSources": [{"name": s, "entity": "Product"} for s in sources]},
            {"entities": [{"name": "Product", "fields": [{"name": "id"}]}]},
            {"components": {k: {} for k in ("Stack", "Table", "Button")}})

    def _table(self, **props):
        return {"type": "Stack", "children": [{"type": "Table", "props": props}]}

    def test_row_action_navigate_is_accepted(self):
        ok, errors, _ = self._validate(
            self._table(rowActions=[{"label": "View", "navigate": "/products/{{id}}"}]))
        assert ok, errors

    def test_single_brace_row_action_also_accepted(self):
        ok, errors, _ = self._validate(
            self._table(rowActions=[{"label": "View", "navigate": "/products/{id}"}]))
        assert ok, errors

    def test_row_href_is_accepted(self):
        ok, errors, _ = self._validate(self._table(rowHref="/products/{{id}}"))
        assert ok, errors

    def test_a_plain_button_navigate_still_validates(self):
        """The exemption must not become a blanket hole — a Button has no
        row to resolve against."""
        ok, errors, _ = self._validate(
            {"type": "Stack",
             "children": [{"type": "Button",
                           "props": {"label": "Go", "navigate": "/x/{{nope}}"}}]})
        assert not ok
        assert any("nope" in e for e in errors)

    def test_real_dataSource_bindings_still_validate(self):
        ok, errors, _ = self._validate(self._table(rows="{{ghost}}"))
        assert not ok
        assert any("ghost" in e for e in errors)


# ── `bind` means three different things ─────────────────────────────

class TestInertFormBind:
    """`props.bind` on a form control is a DEAD prop — Input/Textarea/
    DatePicker destructure it as `bind: _bind` and drop it, and the Form
    collects values by `name` through FormData. Failing a page over a
    string no renderer reads cost 10 of 12 form pages in the A/B.

    Unlike the rowActions case this is NOT a resolved-but-misread binding,
    so the exemption is narrower: `bind` is a REAL binding on Text and on
    Repeat, and blinding the validator there would hide the empty-table
    class it exists to catch.
    """

    MANIFEST = {"components": {
        "Stack": {"category": "layout"}, "Form": {"category": "input"},
        "Input": {"category": "input"}, "Text": {"category": "display"},
        "Repeat": {"category": "data"}, "Table": {"category": "data"},
    }}

    def _validate(self, root):
        return page_composer._validate_page_schema(
            {"schemaVersion": "2", "id": "p", "route": "/x", "root": root,
             "dataSources": [{"name": "products", "entity": "Product"}]},
            {"entities": [{"name": "Product", "fields": [{"name": "id"}]}]},
            self.MANIFEST)

    def test_form_control_bind_is_not_validated(self):
        ok, errors, _ = self._validate(
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "title",
                                            "bind": "{{form.title}}"}}]})
        assert ok, errors

    def test_a_bare_field_name_is_fine_too(self):
        ok, errors, _ = self._validate(
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "title", "bind": "title"}}]})
        assert ok, errors

    def test_text_bind_is_STILL_validated(self):
        """Text.bind goes through resolveBinding — a bad one renders empty,
        which is the failure this validator is for."""
        ok, errors, _ = self._validate(
            {"type": "Stack", "children": [
                {"type": "Text", "bind": "{{ghost.name}}"}]})
        assert not ok
        assert any("ghost" in e for e in errors)

    def test_repeat_bind_is_STILL_validated(self):
        ok, errors, _ = self._validate(
            {"type": "Stack", "children": [
                {"type": "Repeat", "bind": "{{phantom}}", "children": []}]})
        assert not ok
        assert any("phantom" in e for e in errors)

    def test_other_props_on_the_same_input_still_validate(self):
        """The exemption is the `bind` key only, not the whole node."""
        ok, errors, _ = self._validate(
            {"type": "Stack", "children": [
                {"type": "Input", "props": {"name": "t", "bind": "{{form.t}}",
                                            "label": "{{nope.x}}"}}]})
        assert not ok
        assert any("nope" in e for e in errors)

    def test_prompt_states_the_contract(self):
        p = page_composer._build_prompt(
            {"route": "/x", "kind": "form", "entity": "Product"}, {},
            _real_vocab(), VisualLock(), self.MANIFEST,
            patterns=None, variance_seed=None, brief=None)
        assert "NOT a binding" in p and "no `form` scope" in p
