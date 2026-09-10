"""Tests for services.apply_record_maquette."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_record_maquette import (
    _build_footer_node,
    _build_hero_node,
    _control_for,
    _default_control_for,
    _humanize,
    _route_to_slug,
    _submit_target,
    apply_maquettes_to_records,
)


# ─────────────────────────── fixtures ──────────────────────────────────


def _write_registry(root: Path, entities: dict) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8",
    )


def _write_maquettes(root: Path, entries: list) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "record-maquettes.json").write_text(
        json.dumps(entries), encoding="utf-8",
    )


def _write_schema(root: Path, slug: str, doc: dict) -> Path:
    p = root / "src" / "schemas" / f"{slug}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _bookings_entity() -> dict:
    return {
        "bookings": {
                "fields": [
                    {"name": "id", "type": "uuid"},
                    {"name": "email", "type": "text", "required": True},
                    {"name": "phone", "type": "text"},
                    {"name": "notes", "type": "text"},
                    {"name": "status", "type": "text"},
                    {"name": "capacity", "type": "int"},
                    {"name": "startAt", "type": "timestamp"},
                    {"name": "createdAt", "type": "timestamp"},
                    {"name": "updatedAt", "type": "timestamp"},
                ],
        },
    }


def _base_edit_maq(route: str = "/bookings/[id]/edit") -> dict:
    return {
        "entity": "bookings",
        "route": route,
        "mode": "edit",
        "section_grouping": [
            {"label": "Contact", "fields": ["email", "phone"]},
            {"label": "Booking", "fields": ["startAt", "capacity"]},
            {"label": "Notes", "fields": ["notes"], "tone": "secondary"},
        ],
    }


def _base_create_maq() -> dict:
    return {
        "entity": "bookings",
        "route": "/bookings/new",
        "mode": "create",
        "section_grouping": [
            {"label": "Contact", "fields": ["email", "phone"]},
        ],
    }


def _base_view_maq() -> dict:
    return {
        "entity": "bookings",
        "route": "/bookings/[id]",
        "mode": "view",
        "section_grouping": [
            {"label": "Details", "fields": ["email", "phone", "status"]},
        ],
    }


# ─────────────────────────── entry-point ───────────────────────────────


class TestEntryPoint:
    def test_no_maquettes_zero(self, tmp_path: Path):
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 0

    def test_missing_schema_reports_reason_without_authority(self, tmp_path, monkeypatch: Path):
        # Legacy path: under authority the composer BOOTSTRAPS the page
        # instead of reporting "no schema" — that is the point of being
        # sole writer. Pin this test to the pre-authority behaviour.
        monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_edit_maq()])
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 0
        assert any("no schema" in r for r in result["reasons"])

    def test_bad_entries_skip_but_dont_stop_batch(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [
            "not-a-dict",
            {"entity": "bookings", "route": "no-slash"},
            _base_create_maq(),
        ])
        # Only the create maquette has a schema to target.
        _write_schema(tmp_path, "bookings/new",
                       {"id": "x", "route": "/bookings/new", "root": {}})
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 1
        assert result["skipped"] == 2


class TestFunctionalKindGate:
    """A page whose job is triggering a workflow is a FORM, never a
    record — the composer must refuse it instead of wrapping it in
    record anatomy (the atb0m97x upload-page class: decorative
    Processing/Diagnostics/Record Meta shells around a trigger form)."""

    def test_workflow_trigger_form_refused(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_create_maq()])
        _write_schema(tmp_path, "bookings/new", {
            "id": "x", "route": "/bookings/new",
            "root": {"type": "Stack", "children": [
                {"type": "Form",
                 "props": {"workflow": "ProcessBookingWorkflow"},
                 "children": [{"type": "FileUpload",
                               "props": {"name": "filePath"}}]},
            ]},
        })
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 0
        assert any("workflow trigger" in r for r in result["reasons"])

    def test_plain_resource_form_still_composed(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_create_maq()])
        _write_schema(tmp_path, "bookings/new",
                      {"id": "x", "route": "/bookings/new", "root": {}})
        result = apply_maquettes_to_records(str(tmp_path))
        assert result["applied"] == 1


class TestSystemColumnExclusion:
    """Create-mode sections never author system/lifecycle columns —
    the user cannot meaningfully type id/createdAt/updatedAt, and the
    DB owns them. (`startAt`-style domain timestamps stay.)"""

    def test_create_mode_drops_lifecycle_columns(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_create_maq()
        maq["section_grouping"] = [
            {"label": "Contact", "fields": ["email", "phone"]},
            {"label": "Meta", "fields": ["id", "createdAt", "updatedAt"],
             "tone": "meta"},
            {"label": "Schedule", "fields": ["startAt"]},
        ]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/new",
                          {"id": "x", "route": "/bookings/new", "root": {}})
        assert apply_maquettes_to_records(str(tmp_path))["applied"] == 1
        doc = json.loads(p.read_text(encoding="utf-8"))
        names = []
        def walk(n):
            if not isinstance(n, dict):
                return
            name = (n.get("props") or {}).get("name")
            if isinstance(name, str):
                names.append(name)
            for c in (n.get("children") or []):
                walk(c)
        walk(doc["root"])
        assert "email" in names and "startAt" in names
        assert not {"id", "createdAt", "updatedAt"} & set(names)
        # the Meta section lost ALL its fields → no empty shell emitted
        headings = json.dumps(doc)
        assert '"Meta"' not in headings


def _write_plan(root: Path, data_models: list) -> None:
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(
        json.dumps({"data_models": data_models}), encoding="utf-8",
    )


def _write_workflow(root: Path, name: str) -> None:
    (root / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "workflows" / f"{name}.json").write_text(
        json.dumps({"name": name, "definition": {"nodes": [], "edges": []}}),
        encoding="utf-8",
    )


def _find_node(doc: dict, node_type: str) -> dict | None:
    def walk(n):
        if not isinstance(n, dict):
            return None
        if n.get("type") == node_type:
            return n
        for c in (n.get("children") or []):
            hit = walk(c)
            if hit is not None:
                return hit
        return None
    return walk(doc.get("root"))


def _multi_section_create_maq() -> dict:
    maq = _base_create_maq()
    maq["section_grouping"] = [
        {"label": "Contact", "fields": ["email", "phone"]},
        {"label": "Booking", "fields": ["startAt", "capacity"]},
        {"label": "Notes", "fields": ["notes"]},
    ]
    return maq


class TestWizardMode:
    """Create forms with real multi-section anatomy compose as a Wizard
    — the component built for exactly this (E-W3) was unreachable from
    the composer, which flattened everything to stacked Cards."""

    def _compose(self, tmp_path: Path, maq: dict) -> dict:
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/new",
                          {"id": "x", "route": "/bookings/new", "root": {}})
        assert apply_maquettes_to_records(str(tmp_path))["applied"] == 1
        return json.loads(p.read_text(encoding="utf-8"))

    def test_multi_section_create_becomes_wizard(self, tmp_path: Path):
        _write_workflow(tmp_path, "CreateBooking")
        doc = self._compose(tmp_path, _multi_section_create_maq())
        wiz = _find_node(doc, "Wizard")
        assert wiz is not None
        assert _find_node(doc, "Form") is None
        steps = wiz["props"]["steps"]
        assert [s["title"] for s in steps] == ["Contact", "Booking", "Notes"]
        assert wiz["props"]["onComplete"] == "CreateBooking"
        assert wiz["props"]["successRoute"] == "/bookings"
        kinds = {f["name"]: f["kind"] for s in steps for f in s["fields"]}
        assert kinds["email"] == "email"
        assert kinds["startAt"] == "date"
        assert kinds["capacity"] == "number"

    def test_below_threshold_stays_form(self, tmp_path: Path):
        _write_workflow(tmp_path, "CreateBooking")
        doc = self._compose(tmp_path, _base_create_maq())
        assert _find_node(doc, "Wizard") is None
        assert _find_node(doc, "Form") is not None

    def test_no_create_workflow_stays_form(self, tmp_path: Path):
        doc = self._compose(tmp_path, _multi_section_create_maq())
        assert _find_node(doc, "Wizard") is None
        assert _find_node(doc, "Form") is not None

    def test_select_without_options_stays_form(self, tmp_path: Path):
        _write_workflow(tmp_path, "CreateBooking")
        maq = _multi_section_create_maq()
        maq["section_grouping"][2]["fields"] = ["status"]
        maq["control_hints"] = {"status": "select"}
        # no plan.json → no enum options → a select step field would be
        # a dead dropdown → wizard vetoed
        doc = self._compose(tmp_path, maq)
        assert _find_node(doc, "Wizard") is None
        assert _find_node(doc, "Form") is not None

    def test_select_with_plan_enums_gets_options(self, tmp_path: Path):
        _write_workflow(tmp_path, "CreateBooking")
        _write_plan(tmp_path, [{"name": "bookings", "fields": [
            {"name": "status", "enum_values": ["draft", "confirmed"]}]}])
        maq = _multi_section_create_maq()
        maq["section_grouping"][2]["fields"] = ["status"]
        maq["control_hints"] = {"status": "select"}
        doc = self._compose(tmp_path, maq)
        wiz = _find_node(doc, "Wizard")
        assert wiz is not None
        status = next(f for s in wiz["props"]["steps"]
                      for f in s["fields"] if f["name"] == "status")
        assert [o["value"] for o in status["options"]] == ["draft", "confirmed"]


class TestStatusStepper:
    """View pages for status-driven entities get a progress Stepper
    bound to the record's status — the display the doc-intel flow's
    'numbered steps' were reaching for, in the right place."""

    def _compose_view(self, tmp_path: Path) -> dict:
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_view_maq()])
        p = _write_schema(tmp_path, "bookings/[id]",
                          {"id": "x", "route": "/bookings/[id]", "root": {}})
        assert apply_maquettes_to_records(str(tmp_path))["applied"] == 1
        return json.loads(p.read_text(encoding="utf-8"))

    def test_status_enum_emits_stepper(self, tmp_path: Path):
        _write_plan(tmp_path, [{"name": "bookings", "fields": [
            {"name": "status",
             "enum_values": ["draft", "confirmed", "complete"]}]}])
        doc = self._compose_view(tmp_path)
        stepper = _find_node(doc, "Stepper")
        assert stepper is not None
        assert [s["id"] for s in stepper["props"]["steps"]] == \
            ["draft", "confirmed", "complete"]
        assert stepper["props"]["activeId"] == "{{record.status}}"

    def test_no_enum_no_stepper(self, tmp_path: Path):
        doc = self._compose_view(tmp_path)
        assert _find_node(doc, "Stepper") is None


# ─────────────────────────── mode branches ─────────────────────────────


class TestEditMode:
    def test_emits_form_with_sections(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_edit_maq()])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        form = _find(out, "Form")
        assert form is not None
        # Form has 3 section Cards (one per group).
        cards = [c for c in form["children"] if c.get("type") == "Card"]
        assert len(cards) == 3
        assert cards[0]["children"][0]["props"]["content"] == "Contact"

    def test_data_source_binds_record(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_edit_maq()])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        ds = out["dataSources"]
        assert len(ds) == 1
        assert ds[0]["name"] == "record"
        assert ds[0]["op"] == "get"
        assert ds[0]["id"] == "{{route.id}}"

    def test_form_defaults_bound_to_record(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_edit_maq()])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        form = _find(out, "Form")
        assert form["props"]["defaults"] == "{{record}}"


class TestCreateMode:
    def test_no_record_data_source(self, tmp_path: Path):
        # Nothing to prefill in create mode.
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_create_maq()])
        p = _write_schema(tmp_path, "bookings/new",
                           {"id": "x", "route": "/bookings/new", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        assert out["dataSources"] == []

    def test_no_defaults_bound(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_create_maq()])
        p = _write_schema(tmp_path, "bookings/new",
                           {"id": "x", "route": "/bookings/new", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        form = _find(out, "Form")
        assert "defaults" not in form["props"]

    def test_submit_is_insert(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_create_maq()])
        p = _write_schema(tmp_path, "bookings/new",
                           {"id": "x", "route": "/bookings/new", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        form = _find(out, "Form")
        assert form["props"]["onSubmit"]["op"] == "insert"


class TestViewMode:
    def test_emits_description_list_per_section(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_view_maq()])
        p = _write_schema(tmp_path, "bookings/[id]",
                           {"id": "x", "route": "/bookings/[id]", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # No Form in view mode.
        assert _find(out, "Form") is None
        dl = _find(out, "DescriptionList")
        assert dl is not None
        items = dl["props"]["items"]
        assert [i["label"] for i in items] == ["Email", "Phone", "Status"]
        assert items[0]["value"] == "{{record.email}}"


class TestUnknownModeFallsBackToEdit:
    def test_publish_mode_becomes_edit(self, tmp_path: Path):
        # from_dict already normalises this, but the composer also
        # has a belt-and-braces guard.
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [{
            **_base_create_maq(), "mode": "publish",
        }])
        p = _write_schema(tmp_path, "bookings/new",
                           {"id": "x", "route": "/bookings/new", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # Edit mode binds record and has defaults; check the data-mode attr.
        assert out["root"]["props"]["data-mode"] == "edit"


# ─────────────────────────── control hints ─────────────────────────────


class TestControlHints:
    def test_hint_overrides_default(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["control_hints"] = {"notes": "rich-text"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # Find the notes field in the form.
        rte = _find(out, "RichTextEditor")
        assert rte is not None
        assert rte["props"]["name"] == "notes"

    def test_default_control_for_text_field(self):
        # Name-shape checks WIN over pure type for the well-known "email"
        # name so a text-typed email column still lands on EmailInput
        # (fewer surprises for a domain owner scanning the form).
        assert _default_control_for("email", "text") == "EmailInput"
        assert _default_control_for("email", "varchar") == "EmailInput"
        # A phone_number without a phone hint still lands on plain Input —
        # phone masking needs the explicit "phone" control-hint.
        assert _default_control_for("phone_number", "varchar") == "Input"
        # Bare `text` column with a domain-shaped name (notes/description) → Textarea.
        assert _default_control_for("description", "text") == "Textarea"
        assert _default_control_for("body", "varchar") == "Textarea"

    def test_url_field_default(self):
        assert _default_control_for("website_url", "varchar") == "UrlInput"

    def test_bool_default(self):
        assert _default_control_for("is_active", "bool") == "Switch"

    def test_numeric_default(self):
        assert _default_control_for("capacity", "int") == "NumberInput"

    def test_timestamp_default(self):
        # ``DateTimePicker`` is not in the library registry — timestamps
        # collapse to ``DatePicker`` (see apply_record_maquette._default_control_for).
        assert _default_control_for("startAt", "timestamp") == "DatePicker"

    def test_date_default(self):
        assert _default_control_for("dueDate", "date") == "DatePicker"

    def test_json_default(self):
        assert _default_control_for("config", "jsonb") == "KeyValueInput"

    def test_control_for_uses_hint_when_valid(self):
        assert _control_for("x", "signature", {"x": "text"}) == "Signature"

    def test_control_for_falls_back_when_no_hint(self):
        assert _control_for("x", None, {"x": "int"}) == "NumberInput"


# ─────────────────────────── hero variants ─────────────────────────────


class TestHeroVariants:
    def test_page_header_default(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["hero"] = {"kind": "page-header", "title": "Edit booking"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        first = out["root"]["children"][0]
        assert first["props"]["data-hero-kind"] == "page-header"
        assert _find(first, "Heading")["props"]["content"] == "Edit booking"

    def test_status_led_binds_status_field(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_view_maq()
        maq["hero"] = {"kind": "status-led", "title": "Booking",
                        "status_field": "status"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]",
                           {"id": "x", "route": "/bookings/[id]", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        first = out["root"]["children"][0]
        assert first["props"]["data-hero-kind"] == "status-led"
        badge = _find(first, "Badge")
        assert badge is not None
        assert badge["props"]["content"] == "{{record.status}}"

    def test_media_lead_binds_media_field(self, tmp_path: Path):
        _write_registry(tmp_path, {
            "products": {"fields": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "text"},
                {"name": "photo_url", "type": "text"},
            ]},
        })
        _write_maquettes(tmp_path, [{
            "entity": "products", "route": "/products/[id]", "mode": "view",
            "section_grouping": [{"label": "Info", "fields": ["title"]}],
            "hero": {"kind": "media-lead", "title": "Edit product",
                     "media_field": "photo_url"},
        }])
        p = _write_schema(tmp_path, "products/[id]",
                           {"id": "x", "route": "/products/[id]", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        first = out["root"]["children"][0]
        assert first["props"]["data-hero-kind"] == "media-lead"
        img = _find(first, "Image")
        assert img is not None
        assert img["props"]["src"] == "{{record.photo_url}}"

    def test_editorial_hero(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_create_maq()
        maq["hero"] = {"kind": "editorial", "title": "Book your class",
                        "eyebrow": "Welcome"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/new",
                           {"id": "x", "route": "/bookings/new", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        first = out["root"]["children"][0]
        assert first["props"]["data-hero-kind"] == "editorial"
        # First child of the editorial hero is the eyebrow Text.
        assert first["children"][0]["props"]["content"] == "Welcome"

    def test_missing_title_drops_hero(self):
        assert _build_hero_node({"kind": "page-header"}) is None

    def test_status_led_without_status_field_falls_back_to_page_header(self):
        # Composer only branches to status-led if status_field is set.
        # Missing → default page-header behaviour keeps the hero visible.
        node = _build_hero_node({"kind": "status-led", "title": "T"})
        assert node["props"]["data-hero-kind"] == "page-header"

    def test_media_lead_without_media_field_falls_back(self):
        node = _build_hero_node({"kind": "media-lead", "title": "T"})
        assert node["props"]["data-hero-kind"] == "page-header"


# ─────────────────────────── footer variants ───────────────────────────


class TestFooterVariants:
    def test_timestamps_footer(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_view_maq()
        maq["footer"] = {"kind": "timestamps"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]",
                           {"id": "x", "route": "/bookings/[id]", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        footer = _find_by_data_slot(out, "record-footer")
        assert footer is not None
        assert footer["props"]["data-footer-kind"] == "timestamps"

    def test_danger_zone_footer_edit_mode(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["footer"] = {"kind": "danger-zone", "content": "Deleting is permanent"}
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        footer = _find_by_data_slot(out, "record-footer")
        assert footer["type"] == "Card"
        assert footer["props"]["tone"] == "danger"

    def test_unknown_footer_kind_dropped(self):
        assert _build_footer_node({"kind": "kitchen-sink"}, mode="edit") is None


# ─────────────────────────── signature moves + idempotency ─────────────


class TestSignatureMovesAttr:
    def test_moves_emitted_as_root_data_attr(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["signature_moves"] = ["sticky-save-bar", "field-focus-guide"]
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        assert out["root"]["props"]["data-signature-move"] == "sticky-save-bar field-focus-guide"


class TestIdempotency:
    def test_second_apply_is_a_noop(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        _write_maquettes(tmp_path, [_base_edit_maq()])
        _write_schema(tmp_path, "bookings/[id]/edit",
                       {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        first = apply_maquettes_to_records(str(tmp_path))
        assert first["applied"] == 1
        second = apply_maquettes_to_records(str(tmp_path))
        assert second["applied"] == 0
        assert any("already composed" in r for r in second["reasons"])


# ─────────────────────────── meta section read-only ────────────────────


class TestMetaSectionReadOnly:
    def test_meta_tone_in_edit_mode_marks_read_only(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["section_grouping"].append({
            "label": "Meta", "fields": ["createdAt", "updatedAt"], "tone": "meta",
        })
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # Find the Meta section — walk the form.
        form = _find(out, "Form")
        meta_card = None
        for card in form["children"]:
            if card.get("props", {}).get("data-section-tone") == "meta":
                meta_card = card
                break
        assert meta_card is not None
        # createdAt / updatedAt fields have readOnly=True.
        field_nodes = [c for c in meta_card["children"] if c.get("props", {}).get("name")]
        assert len(field_nodes) == 2
        assert all(f["props"].get("readOnly") is True for f in field_nodes)

    def test_meta_tone_in_view_mode_is_not_treated_specially(self, tmp_path: Path):
        # View mode has no editable fields at all — DescriptionList only.
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_view_maq()
        maq["section_grouping"].append({
            "label": "Meta", "fields": ["createdAt"], "tone": "meta",
        })
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]",
                           {"id": "x", "route": "/bookings/[id]", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        assert _find(out, "Form") is None


# ─────────────────────────── advanced collapsible ──────────────────────


class TestAdvancedSectionCollapsible:
    def test_advanced_tone_marks_card_collapsible(self, tmp_path: Path):
        _write_registry(tmp_path, _bookings_entity())
        maq = _base_edit_maq()
        maq["section_grouping"].append({
            "label": "Advanced", "fields": ["notes"], "tone": "advanced",
        })
        _write_maquettes(tmp_path, [maq])
        p = _write_schema(tmp_path, "bookings/[id]/edit",
                           {"id": "x", "route": "/bookings/[id]/edit", "root": {}})
        apply_maquettes_to_records(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        form = _find(out, "Form")
        adv = None
        for card in form["children"]:
            if card.get("props", {}).get("data-section-tone") == "advanced":
                adv = card
                break
        assert adv is not None
        assert adv["props"].get("collapsible") is True


# ─────────────────────────── submit target ─────────────────────────────


class TestSubmitTarget:
    def test_create_target(self):
        t = _submit_target("bookings", "/bookings/new", "create")
        assert t == {"kind": "data", "op": "insert", "entity": "bookings",
                     "navigate": "/bookings"}

    def test_edit_target(self):
        t = _submit_target("bookings", "/bookings/[id]/edit", "edit")
        assert t["op"] == "update"
        assert t["id"] == "{{route.id}}"
        # Navigate back to the detail page.
        assert t["navigate"] == "/bookings/[id]"


# ─────────────────────────── humanize + slug ───────────────────────────


class TestHumanize:
    def test_camel(self):
        assert _humanize("createdAt") == "Created At"

    def test_snake(self):
        assert _humanize("phone_number") == "Phone Number"


class TestRouteToSlug:
    def test_strips_slashes(self):
        assert _route_to_slug("/bookings/new") == "bookings/new"

    def test_preserves_brackets(self):
        assert _route_to_slug("/bookings/[id]/edit") == "bookings/[id]/edit"


# ─────────────────────────── shared traversal ──────────────────────────


def _find(node, kind: str):
    if isinstance(node, dict):
        if node.get("type") == kind:
            return node
        for k in ("children", "root"):
            v = node.get(k)
            if v is not None:
                hit = _find(v, kind)
                if hit is not None:
                    return hit
    elif isinstance(node, list):
        for x in node:
            hit = _find(x, kind)
            if hit is not None:
                return hit
    return None


def _find_by_data_slot(node, slot: str):
    if isinstance(node, dict):
        if node.get("props", {}).get("data-slot") == slot:
            return node
        for k in ("children", "root"):
            v = node.get(k)
            if v is not None:
                hit = _find_by_data_slot(v, slot)
                if hit is not None:
                    return hit
    elif isinstance(node, list):
        for x in node:
            hit = _find_by_data_slot(x, slot)
            if hit is not None:
                return hit
    return None
