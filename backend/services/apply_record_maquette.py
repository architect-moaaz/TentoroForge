"""Post-gen: rebuild record page schemas from persisted maquettes.

Runs AFTER page authoring. Reads
``<output>/src/contracts/record-maquettes.json`` (a list of
:class:`services.record_maquette.RecordMaquette` dicts) and rewrites
each targeted record page schema deterministically.

Authority pattern is the same as
:mod:`services.apply_dashboard_maquette` and
:mod:`services.apply_collection_maquette`: the maquette IS the content
contract; composer is mechanical; no LLM in the assembly.

Mode branch (from ``maquette.mode``):
  * ``view`` — read-only detail. Emits a `DescriptionList` per section
    binding each field to `{{record.<field>}}`. Composer wraps each
    section in a Card.
  * ``edit`` — form. Emits a `Form` with a `FormSection` per section
    grouping. Each field becomes a form field with the maquette's
    control-hint applied when present.
  * ``create`` — same shape as edit, but no default values and the
    submit navigates to the list view on success.

Slot honoring:
  * ``hero`` → page-header / status-led / media-lead / editorial /
    breadcrumbs variants (analogous to dashboard hero kinds).
  * ``section_grouping`` → the sections themselves.
  * ``field_ordering`` → fallback ordering when there is no section
    grouping (rare — the LLM prompt discourages this).
  * ``control_hints`` → per-field control override.
  * ``footer`` → timestamps / danger-zone / audit / related.
  * ``signature_moves`` → `data-signature-move` on root Stack.

Idempotent: rewriting an already-composed schema is a no-op.
Fails closed: any exception logs and leaves the existing schema alone.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _prefetch_page_compositions(root, entries, kind: str) -> None:
    """Warm the LLM page-composer cache for this whole batch at once.

    Best-effort by construction — a failure here costs nothing but
    speed, because every page still composes on demand inside
    ``_apply_one``. So it swallows rather than propagates.
    """
    try:
        from services.page_composer_pipeline import prefetch_maquette_pages
        stats = prefetch_maquette_pages(root, entries, kind)
        if stats.get("composed") or stats.get("cached"):
            logger.info(
                "[%s] page-composer prefetch: composed=%s cached=%s failed=%s",
                kind, stats.get("composed"), stats.get("cached"), stats.get("failed"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[%s] page-composer prefetch skipped: %s", kind, exc)



_MARKER_META_KEY = "record_maquette_composed"

_MAQUETTES_REL_PATH = ("src", "contracts", "record-maquettes.json")

# System/lifecycle columns the DB owns — never authorable in create mode.
_SYSTEM_COLS = frozenset({"id", "createdat", "updatedat", "deletedat"})


def _fold_col(name: str) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def _contains_workflow_form(node: Any) -> bool:
    """True when the schema tree has a Form wired to a workflow."""
    if not isinstance(node, dict):
        return False
    if node.get("type") == "Form" and \
            isinstance((node.get("props") or {}).get("workflow"), str):
        return True
    return any(_contains_workflow_form(c)
               for c in (node.get("children") or []) if isinstance(c, dict))


def apply_maquettes_to_records(output_dir: str) -> dict[str, Any]:
    """Rebuild each targeted record page from its persisted maquette.

    Returns ``{"applied": int, "skipped": int, "reasons": [str, ...]}``.
    Never raises. Multi-page: iterates every maquette entry independently.

    Phase 6b (Record Authority) — composer is the SOLE writer for
    record pages when :func:`services.artifact_authority.is_authority_enabled`
    is on for ``"record"``. Two extensions activate under that flag:

    1. **Bootstrap the schema when it doesn't exist** — LLM skipped it,
       so the file isn't on disk yet. Composer creates it fresh.
    2. **Recipe fallback** — when no maquette JSON exists, recipe-fill
       every record page in the plan via the deterministic form/detail
       builders.
    """
    root = Path(output_dir)
    _authority_on = _is_record_authority_enabled()
    maq_path = root.joinpath(*_MAQUETTES_REL_PATH)

    if not maq_path.is_file():
        if _authority_on:
            return _fallback_all_records_via_recipe(root, reason="no maquettes on disk")
        return {"applied": 0, "skipped": 0, "reasons": ["no maquettes on disk"]}

    try:
        raw = json.loads(maq_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[record-maquette] unreadable: %s", exc)
        if _authority_on:
            return _fallback_all_records_via_recipe(
                root, reason=f"maquettes unreadable: {exc}",
            )
        return {"applied": 0, "skipped": 0, "reasons": [f"maquettes unreadable: {exc}"]}

    entries = raw if isinstance(raw, list) else (raw.get("maquettes") if isinstance(raw, dict) else None)
    if not isinstance(entries, list):
        return {"applied": 0, "skipped": 0, "reasons": ["maquettes not a list"]}

    registry = _load_registry(root)

    # CREATIVE-6c — see the twin call in apply_collection_maquette: warm
    # the composer cache for the batch concurrently so the per-page loop
    # below hits cache instead of serialising one LLM call per record.
    _prefetch_page_compositions(root, entries, kind="detail")

    applied = 0
    skipped = 0
    reasons: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped += 1
            reasons.append(f"entry[{i}]: not a dict")
            continue
        result = _apply_one(root, entry, registry, allow_bootstrap=_authority_on)
        if result.get("applied"):
            applied += 1
        else:
            skipped += 1
            entity = entry.get("entity") or "?"
            reasons.append(f"{entity}: {result.get('reason') or 'unknown'}")

    if _authority_on:
        _tail = _fallback_missing_records_via_recipe(root, applied_routes={
            entry.get("route") for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("route"), str)
        })
        applied += _tail.get("applied", 0)
        reasons.extend(_tail.get("reasons", []))

    return {"applied": applied, "skipped": skipped, "reasons": reasons}


def _apply_one(root: Path, maquette: dict, registry: dict,
                *, allow_bootstrap: bool = False) -> dict[str, Any]:
    entity = maquette.get("entity")
    route = maquette.get("route")
    if not (isinstance(entity, str) and entity and
            isinstance(route, str) and route.startswith("/")):
        return {"applied": False, "reason": "missing/bad entity or route"}

    mode = maquette.get("mode") if isinstance(maquette.get("mode"), str) else "edit"
    if mode not in ("view", "edit", "create"):
        mode = "edit"

    # CREATIVE-6b — LLM page composer early-exit (see the sibling hook in
    # apply_collection_maquette._apply_one for the full rationale). Kind
    # here is "detail" for view / "form" for create+edit so the composer's
    # manifest subsetter picks the right categories.
    try:
        from services.page_composer_pipeline import (
            compose_page_via_pipeline_sync as _llm_compose,
            is_flag_on as _llm_flag_on,
            page_from_maquette as _page_from_maquette,
            _write_page_schema as _llm_write,
        )
        if _llm_flag_on():
            _plan_path = root / "src" / "contracts" / "plan.json"
            _plan = json.loads(_plan_path.read_text(encoding="utf-8")) \
                if _plan_path.is_file() else {}
            _kind = "detail" if mode == "view" else "form"
            _page = _page_from_maquette(maquette, _plan, _kind)
            from services.page_vocabulary import _load_brief as _lb
            _llm_schema, _llm_prov = _llm_compose(
                _page, _plan, root, brief=_lb(root))
            if _llm_schema is not None:
                _wrote = _llm_write(_page, _llm_schema, root)
                if _wrote is not None:
                    return {"applied": True, "reason": "ok (llm-composed)"}
    except Exception as _llm_exc:  # noqa: BLE001
        logger.debug("[record-maquette] llm composer skipped: %s", _llm_exc)
    # Slice-3 ledger contract: append-only entities are immutable at the
    # Data Engine (PUT/DELETE → 405). Rendering an edit/create form for
    # them produces a UI that always fails on save; instead force
    # view-only. If a Reversal action is authorised on the plan it lives
    # as its own workflow button on the detail page, not as an edit form.
    try:
        _reg_ent = _entity_meta(registry, entity)
        if isinstance(_reg_ent, dict) and str(_reg_ent.get("lifecycle") or "").strip() == "append_only":
            mode = "view"
    except Exception:  # noqa: BLE001
        pass

    schema_path = _find_record_schema(root, route)
    _bootstrapped = False
    if schema_path is None:
        if allow_bootstrap:
            slug = _route_to_slug(route)
            schema_path = root / "src" / "schemas" / f"{slug}.json"
            _bootstrapped = True
        else:
            return {"applied": False, "reason": f"no schema for route {route}"}

    if _bootstrapped:
        existing: dict = {}
    else:
        try:
            existing = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"applied": False, "reason": f"schema unreadable: {exc}"}

    if isinstance(existing, dict) and isinstance(existing.get("meta"), dict):
        if existing["meta"].get(_MARKER_META_KEY) is True:
            return {"applied": False, "reason": "already composed"}

    # Functional-kind gate: a page whose job is triggering a workflow is
    # a FORM, never a record — page kind is decided by function, not by
    # looks. Composing record anatomy around a trigger form produces
    # decorative section shells while the submission contract lives in a
    # subsystem this composer knows nothing about (the atb0m97x /upload
    # class). Refuse instead of rewriting.
    if _contains_workflow_form(existing.get("root") if isinstance(existing, dict) else None):
        return {"applied": False,
                "reason": "workflow trigger form — record anatomy not applicable"}

    # BOOTSTRAP ONLY. The maquette now reaches the page AUTHOR as a design
    # brief before the page is written (services.maquette_brief), so the
    # author already built this page from this maquette. Rewriting it here
    # would discard that work and re-impose one deterministic shape on
    # every app — the reason interior pages all looked alike. Compose only
    # when nothing exists at this route.
    if not _bootstrapped and isinstance(existing, dict) and existing.get("root"):
        return {"applied": False, "reason": "page already authored — not overwriting"}

    entity_meta = _entity_meta(registry, entity)
    columns = _column_type_map(entity_meta)

    root_id = existing.get("id") or f"{_route_to_slug(route)}-record"

    sections: list[dict] = []

    hero_node = _build_hero_node(maquette.get("hero"))
    if hero_node is not None:
        sections.append(hero_node)

    body_sections, data_sources = _build_body_sections(
        entity=entity,
        route=route,
        mode=mode,
        maquette=maquette,
        columns=columns,
        root=root,
    )
    sections.extend(body_sections)

    footer_node = _build_footer_node(maquette.get("footer"), mode=mode)
    if footer_node is not None:
        sections.append(footer_node)

    root_props: dict[str, Any] = {"gap": "tokens.spacing.6"}
    sig_moves = maquette.get("signature_moves") or []
    sig_moves = [s for s in sig_moves if isinstance(s, str) and s.strip()]
    if sig_moves:
        root_props["data-signature-move"] = " ".join(sig_moves[:8])
    root_props["data-mode"] = mode

    new_schema: dict = {
        "schemaVersion": existing.get("schemaVersion", "2"),
        "id": root_id,
        "route": route,
        "layout": existing.get("layout", "main"),
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": root_props, "children": sections},
    }
    prev_meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    new_schema["meta"] = {**prev_meta, _MARKER_META_KEY: True}

    try:
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path.write_text(json.dumps(new_schema, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"applied": False, "reason": f"write failed: {exc}"}

    logger.info(
        "[record-maquette] composed %s (%s mode, %d sections)%s",
        schema_path.name, mode, len(sections),
        " (bootstrap)" if _bootstrapped else "",
    )
    return {"applied": True,
            "reason": "ok (bootstrap)" if _bootstrapped else "ok"}


# ─────────────────────────── schema lookup ─────────────────────────────


def _find_record_schema(root: Path, route: str) -> Optional[Path]:
    """Find the schema file for a record route.

    Record routes typically embed a param (``/bookings/[id]``,
    ``/bookings/new``, ``/bookings/[id]/edit``). Schema filenames in
    the generated app can be exact, leaf-only, or bracket-normalised.
    """
    schema_dirs = [
        root / "src" / "schemas",
        root / "src" / "contracts" / "pages",
        root / "schemas" / "pages",
    ]
    slug = _route_to_slug(route)
    leaf = slug.split("/")[-1]

    candidates = {
        slug,
        leaf,
        # Bracket-stripped variants — some pipelines flatten [id] to id.
        slug.replace("[", "").replace("]", ""),
        leaf.replace("[", "").replace("]", ""),
    }

    for base in schema_dirs:
        if not base.is_dir():
            continue
        for cand in candidates:
            p = base / f"{cand}.json"
            if p.is_file():
                return p

    # Content-based fallback — match a schema whose ``route`` is exactly
    # the record route (with brackets preserved in either direction).
    _target = route.rstrip("/")
    _target_alt = _target.replace("[", "").replace("]", "")
    for base in schema_dirs:
        if not base.is_dir():
            continue
        for p in base.glob("**/*.json"):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            r = str(doc.get("route") or "").rstrip("/")
            if r in (_target, _target_alt):
                return p
    return None


def _route_to_slug(route: str) -> str:
    return route.strip("/") or "index"


# ─────────────────────────── registry helpers ──────────────────────────


def _load_registry(root: Path) -> dict:
    for candidate in (
        root / "src" / "contracts" / "registry.json",
        root / "src" / "contracts" / "plan.json",
    ):
        if candidate.is_file():
            try:
                _reg = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            # Clean at the boundary: a composer that never receives
            # ``passwordHash`` cannot emit it, so the output sweep does
            # not need a second pass to strip it back out.
            from services.sensitive_column_guard import (
                strip_sensitive_from_registry,
            )
            _reg, _n = strip_sensitive_from_registry(_reg)
            if _n:
                logger.info(
                    "record_maquette: %d sensitive column(s) withheld "
                    "from the composer", _n,
                )
            return _reg
    return {}


def _entity_meta(registry: dict, entity_name: str) -> dict:
    entities = registry.get("entities") if isinstance(registry, dict) else None
    if isinstance(entities, dict):
        meta = entities.get(entity_name)
        if isinstance(meta, dict):
            return meta
    return {}


def _column_type_map(entity_meta: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    fields = entity_meta.get("fields") or entity_meta.get("columns") or []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                name = f.get("name") or f.get("column")
                t = f.get("type") or f.get("sqlType") or ""
                if isinstance(name, str) and name:
                    out[name] = str(t).lower()
    elif isinstance(fields, dict):
        for name, meta in fields.items():
            t = ""
            if isinstance(meta, dict):
                t = meta.get("type") or meta.get("sqlType") or ""
            if isinstance(name, str):
                out[name] = str(t).lower()
    return out


# ─────────────────────────── body builders ─────────────────────────────


# Maps a maquette control-hint → renderer component name. When a field
# has no hint, the composer falls back to a type-driven default in
# _default_control_for.
_HINT_TO_COMPONENT = {
    "select": "Select",
    "combobox": "Combobox",
    "radio-group": "RadioGroup",
    "switch": "Switch",
    "date-picker": "DatePicker",
    "date-range": "DateRangePicker",
    "time-picker": "TimePicker",
    # ``DateTimePicker`` is NOT in the library registry (starter.json ships
    # ``DatePicker`` + ``TimePicker`` separately). Map both aliases to
    # ``DatePicker`` at the source so the renderer never drops the node.
    "datetime-picker": "DatePicker",
    "number-input": "NumberInput",
    "slider": "Slider",
    "rating": "Rating",
    "color-picker": "ColorPicker",
    "file-upload": "FileUpload",
    "camera-capture": "CameraCapture",
    "signature": "Signature",
    "rich-text": "RichTextEditor",
    "markdown": "MarkdownEditor",
    "code-block": "CodeBlock",
    "textarea": "Textarea",
    "masked-input": "MaskedInput",
    "otp": "InputOTP",
    "key-value": "KeyValueInput",
    "tags": "TagInput",
    "money": "MoneyInput",
    "phone": "PhoneInput",
    "url": "UrlInput",
    "email": "EmailInput",
}


def _build_body_sections(
    *,
    entity: str,
    route: str,
    mode: str,
    maquette: dict,
    columns: dict[str, str],
    root: Optional[Path] = None,
) -> tuple[list[dict], list[dict]]:
    """Build the body sections + data sources for a record page.

    Returns (sections, data_sources).
    """
    section_specs = maquette.get("section_grouping") or []
    control_hints = maquette.get("control_hints") or {}
    field_ordering = maquette.get("field_ordering") or []

    # Create mode never authors system/lifecycle columns: the user can't
    # meaningfully type id/createdAt/updatedAt and the DB owns them.
    # (Domain timestamps like startAt stay — the exclusion is an exact
    # set, not a suffix match.) A section that loses ALL its fields to
    # this is dropped by the empty-section skip below — no shell Cards.
    def _authorable(f: str) -> bool:
        if mode == "create" and _fold_col(f) in _SYSTEM_COLS:
            return False
        return True

    # Normalise section specs to (label, fields, tone, collapsible, subhead).
    groups: list[dict] = []
    for sec in section_specs:
        if not isinstance(sec, dict):
            continue
        label = sec.get("label")
        fields = sec.get("fields") or []
        if not (isinstance(label, str) and label.strip() and isinstance(fields, list)):
            continue
        clean_fields = [f for f in fields if isinstance(f, str) and f.strip()
                        and (not columns or f in columns) and _authorable(f)]
        if not clean_fields:
            continue
        groups.append({
            "label": label,
            "fields": clean_fields,
            "tone": sec.get("tone") if isinstance(sec.get("tone"), str) else "primary",
            "collapsible": bool(sec.get("collapsible")) if sec.get("collapsible") is not None else None,
            "subhead": sec.get("subhead") if isinstance(sec.get("subhead"), str) else None,
        })

    # If nothing usable in groups, synthesise a single primary section
    # from field_ordering (or all real columns).
    if not groups:
        fallback_fields = [f for f in field_ordering if isinstance(f, str) and f.strip()
                            and (not columns or f in columns) and _authorable(f)]
        if not fallback_fields and root is not None:
            # Before flattening everything into one "Details" card, ask the
            # domain how this record reads. A work order grouped into
            # Job / Customer / Parts is navigable; the same fields in one
            # undifferentiated column are a form to endure.
            try:
                from services.page_vocabulary import (
                    resolve_page_recipe, vocabulary_for_output_dir,
                )
                vocab = vocabulary_for_output_dir(root)
                recipe = resolve_page_recipe(
                    vocab, entity, {"fields": list(columns.keys())}) if vocab else {}
            except Exception:  # noqa: BLE001
                recipe = {}
            for sec in (recipe.get("detail_sections") or []):
                clean = [f for f in sec["fields"] if _authorable(f)]
                if clean:
                    groups.append({
                        "label": sec["label"], "fields": clean,
                        "tone": "primary", "collapsible": None, "subhead": None,
                    })
            if groups:
                logger.info("[record] %s sections from archetype recipe: %s",
                            entity, [g["label"] for g in groups])
        if not groups and not fallback_fields:
            fallback_fields = [n for n in columns.keys()
                               if n.lower() not in ("id", "createdat", "updatedat", "deletedat")]
        if not groups and fallback_fields:
            groups.append({
                "label": "Details", "fields": fallback_fields,
                "tone": "primary", "collapsible": None, "subhead": None,
            })

    data_sources: list[dict] = []
    if mode in ("view", "edit"):
        # Both need to READ the current record. The runtime resolves
        # {{record.<field>}} against the ``record`` dataSource with the
        # route's id param.
        data_sources.append({
            "name": "record",
            "entity": entity,
            "op": "get",
            "id": "{{route.id}}",
        })

    body: list[dict] = []
    if mode == "view":
        # Status-driven entities get a progress Stepper bound to the
        # record's status — the machine-state display (Queued →
        # Processing → Complete) that belongs on the DETAIL page, not
        # as pseudo-steps on the create form.
        stepper = _build_status_stepper(root, entity, columns)
        if stepper is not None:
            body.append(stepper)
        for g in groups:
            body.append(_build_view_section(g))
    else:
        # Create forms with real multi-section anatomy compose as a
        # Wizard (one step per maquette section). Falls back to the
        # stacked-Card Form below the threshold, when no Create
        # workflow exists to dispatch, or when any field can't be
        # expressed as a WizardField.
        if mode == "create" and root is not None:
            wizard = _build_wizard_node(groups, control_hints, columns,
                                        entity, root)
            if wizard is not None:
                body.append(wizard)
                return body, data_sources

        # edit / create — wrap sections in a single Form.
        form_children: list[dict] = []
        for g in groups:
            form_children.append(_build_form_section(g, control_hints, columns, mode))
        submit_target = _submit_target(entity, route, mode)
        form_node = {
            "type": "Form",
            "props": {
                "onSubmit": submit_target,
                "data-mode": mode,
                # A create form has no defaults; edit form binds to the record.
                **({"defaults": "{{record}}"} if mode == "edit" else {}),
            },
            "children": form_children,
        }
        body.append(form_node)

    return body, data_sources


# ─────────────────────────── wizard mode ───────────────────────────────

# A create form earns wizard anatomy when it has this many sections OR
# this many input fields — below that, a single scroll of cards reads
# better than forced Next-clicking.
_WIZARD_MIN_SECTIONS = 3
_WIZARD_MIN_FIELDS = 10

# Composer control → WizardField.kind. Controls absent here (FileUpload,
# KeyValueInput, …) can't be expressed as wizard fields — their presence
# vetoes the wizard and keeps the Form.
_CONTROL_TO_WIZARD_KIND = {
    "Input": "text",
    "UrlInput": "text",
    "EmailInput": "email",
    "PhoneInput": "text",
    "MaskedInput": "text",
    "Textarea": "textarea",
    "NumberInput": "number",
    "Slider": "number",
    "Select": "select",
    "Combobox": "select",
    "Checkbox": "checkbox",
    "Switch": "checkbox",
    "DatePicker": "date",
    "RadioGroup": "radio",
}


def _find_create_workflow(root: Path, entity: str) -> Optional[str]:
    """Name of the Create<Entity> workflow on disk, or None.

    The Wizard component submits by DISPATCHING a workflow
    (``onComplete``), unlike the Form's data-submit — so a wizard is
    only viable when the CRUD create workflow actually exists.
    """
    wf_dir = root / "workflows"
    if not wf_dir.is_dir():
        return None
    targets = {"create" + _fold_col(entity)}
    if entity and entity.lower().endswith("s"):
        targets.add("create" + _fold_col(entity[:-1]))
    for p in wf_dir.glob("*.json"):
        if _fold_col(p.stem) in targets:
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                name = doc.get("name")
                return name if isinstance(name, str) and name else p.stem
            except Exception:  # noqa: BLE001
                return p.stem
    return None


def _wizard_field(field_name: str, control_hints: dict,
                  columns: dict[str, str], plan: Any,
                  entity: str) -> Optional[dict]:
    """Map one section field to a WizardField, or None if inexpressible."""
    hint = control_hints.get(field_name) if isinstance(control_hints, dict) else None
    control = _control_for(field_name, hint, columns)
    kind = _CONTROL_TO_WIZARD_KIND.get(control)
    if kind is None:
        return None
    if kind == "text" and "email" in field_name.lower():
        kind = "email"
    field: dict[str, Any] = {"name": field_name,
                             "label": _humanize(field_name), "kind": kind}
    if kind == "select":
        try:
            from services.plan_field_lookup import get_enum_options
            opts = get_enum_options(plan, entity, field_name)
        except Exception:  # noqa: BLE001
            opts = None
        if not opts:
            return None  # a select with no options is a dead dropdown
        field["options"] = [{"value": str(o.get("value")),
                             "label": str(o.get("label"))} for o in opts]
    return field


def _build_wizard_node(groups: list[dict], control_hints: dict,
                       columns: dict[str, str], entity: str,
                       root: Path) -> Optional[dict]:
    """Emit a Wizard for a multi-section create form, or None."""
    total_fields = sum(len(g["fields"]) for g in groups)
    if len(groups) < _WIZARD_MIN_SECTIONS and total_fields < _WIZARD_MIN_FIELDS:
        return None
    workflow = _find_create_workflow(root, entity)
    if not workflow:
        return None
    try:
        from services.plan_field_lookup import load_plan
        plan = load_plan(root)
    except Exception:  # noqa: BLE001
        plan = None

    steps: list[dict] = []
    for i, g in enumerate(groups):
        fields: list[dict] = []
        for f in g["fields"]:
            wf_field = _wizard_field(f, control_hints, columns, plan, entity)
            if wf_field is None:
                return None
            fields.append(wf_field)
        step: dict[str, Any] = {
            "id": _fold_col(g["label"]) or f"step{i + 1}",
            "title": g["label"],
            "fields": fields,
        }
        if g.get("subhead"):
            step["description"] = g["subhead"]
        steps.append(step)

    return {"type": "Wizard", "props": {
        "steps": steps,
        "onComplete": workflow,
        "successRoute": "/" + entity.lower(),
    }}


# ─────────────────────────── status stepper ────────────────────────────

def _build_status_stepper(root: Optional[Path], entity: str,
                          columns: dict[str, str]) -> Optional[dict]:
    """Progress Stepper for a status-enum entity's detail page, or None.

    ``activeId`` binds the record's live status string; the library
    Stepper matches it against step ids to derive complete/current/
    pending states. Enum order = progression order (the plan's order).
    """
    if root is None:
        return None
    status_col = next((c for c in columns
                       if _fold_col(c) in ("status", "state")), "status")
    try:
        from services.plan_field_lookup import get_enum_values, load_plan
        values = get_enum_values(load_plan(root), entity, status_col)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(values, list):
        return None
    # Terminal failure values aren't progression stages — a stepper
    # shows the happy path; failure is the hero Badge's job.
    stages = [v for v in values
              if _fold_col(str(v)) not in ("failed", "error",
                                           "cancelled", "canceled")]
    if len(stages) < 2:
        return None
    return {"type": "Stepper", "props": {
        "steps": [{"id": str(v), "label": _humanize(str(v))} for v in stages],
        "activeId": f"{{{{record.{status_col}}}}}",
    }}


def _build_view_section(group: dict) -> dict:
    """Render a read-only Card with a DescriptionList inside."""
    items = [
        {"label": _humanize(f), "value": f"{{{{record.{f}}}}}"}
        for f in group["fields"]
    ]
    heading_children: list[dict] = [
        {"type": "Heading", "props": {"content": group["label"], "level": 2}},
    ]
    if group.get("subhead"):
        heading_children.append({"type": "Text",
                                  "props": {"content": group["subhead"], "variant": "caption"}})
    return {
        "type": "Card",
        "props": {
            "padding": "tokens.spacing.6",
            "data-section-tone": group["tone"],
        },
        "children": [
            *heading_children,
            {"type": "DescriptionList", "props": {"items": items}},
        ],
    }


def _build_form_section(group: dict, control_hints: dict, columns: dict[str, str], mode: str) -> dict:
    """Render an edit-mode form section wrapped in a Card."""
    children: list[dict] = [
        {"type": "Heading", "props": {"content": group["label"], "level": 2}},
    ]
    if group.get("subhead"):
        children.append({"type": "Text",
                          "props": {"content": group["subhead"], "variant": "caption"}})

    # Meta tone in edit mode = read-only display for timestamps/audit.
    read_only = (group["tone"] == "meta" and mode == "edit")

    for f in group["fields"]:
        hint = control_hints.get(f) if isinstance(control_hints, dict) else None
        control = _control_for(f, hint, columns)
        field_node: dict[str, Any] = {
            "type": control,
            "props": {
                "name": f,
                "label": _humanize(f),
            },
        }
        if read_only:
            field_node["props"]["readOnly"] = True
        children.append(field_node)

    card_props: dict[str, Any] = {
        "padding": "tokens.spacing.6",
        "data-section-tone": group["tone"],
    }
    if group.get("collapsible") or group["tone"] == "advanced":
        card_props["collapsible"] = True
    return {"type": "Card", "props": card_props, "children": children}


def _control_for(field_name: str, hint: str | None, columns: dict[str, str]) -> str:
    """Return the renderer component name for a form field."""
    if isinstance(hint, str) and hint in _HINT_TO_COMPONENT:
        return _HINT_TO_COMPONENT[hint]
    return _default_control_for(field_name, columns.get(field_name, ""))


def _default_control_for(name: str, sql_type: str) -> str:
    t = (sql_type or "").lower()
    lo = name.lower()
    if t.startswith("bool"):
        return "Switch"
    if any(k in t for k in ("int", "numeric", "decimal", "float", "double", "real")):
        return "NumberInput"
    if any(k in t for k in ("time", "date", "timestamp")):
        # Always ``DatePicker`` — the library registry has no combined
        # date+time widget; emitting ``DateTimePicker`` would be dropped
        # by the renderer as unknown. Time-of-day precision is fine for
        # timestamp columns via the DatePicker.
        return "DatePicker"
    if "json" in t:
        return "KeyValueInput"
    if lo.endswith("_url") or lo == "url" or lo.endswith("link"):
        return "UrlInput"
    if lo.endswith("_email") or lo == "email":
        return "EmailInput"
    if lo in ("description", "notes", "body", "content") or t == "text":
        return "Textarea"
    return "Input"


def _submit_target(entity: str, route: str, mode: str) -> dict:
    """Build the Form onSubmit action for edit/create modes."""
    if mode == "create":
        # Post to /api/data/<entity>, then navigate to the list.
        list_route = "/" + entity.lower()
        return {"kind": "data", "op": "insert", "entity": entity, "navigate": list_route}
    return {"kind": "data", "op": "update", "entity": entity,
            "id": "{{route.id}}", "navigate": route.rstrip("/").rsplit("/", 1)[0] or "/"}


# ─────────────────────────── slot helpers ──────────────────────────────


def _build_hero_node(hero: Any) -> Optional[dict]:
    """Emit the record-page hero based on its kind.

    Kinds:
      * ``page-header`` — default. Heading + optional subtitle.
      * ``status-led`` — leading `Badge` bound to `{{record.<status_field>}}`.
      * ``media-lead`` — leading `Image`/`Avatar` bound to
        `{{record.<media_field>}}` + heading beside it.
      * ``editorial`` — centred eyebrow + heading + subtitle.
      * ``breadcrumbs`` — small `Breadcrumbs` node above the heading.
    """
    if not isinstance(hero, dict):
        return None
    title = hero.get("title")
    if not (isinstance(title, str) and title.strip()):
        return None
    kind = hero.get("kind") if isinstance(hero.get("kind"), str) else "page-header"
    subtitle = hero.get("subtitle") if isinstance(hero.get("subtitle"), str) else None
    eyebrow = hero.get("eyebrow") if isinstance(hero.get("eyebrow"), str) else None
    status_field = hero.get("status_field") if isinstance(hero.get("status_field"), str) else None
    media_field = hero.get("media_field") if isinstance(hero.get("media_field"), str) else None

    if kind == "status-led" and status_field:
        return {
            "type": "Row",
            "props": {"gap": "tokens.spacing.3", "align": "center",
                      "data-slot": "record-hero", "data-hero-kind": "status-led"},
            "children": [
                {"type": "Badge", "props": {
                    "content": f"{{{{record.{status_field}}}}}", "tone": "auto"}},
                {"type": "Stack", "props": {"gap": "tokens.spacing.1"}, "children": _title_stack(title, subtitle)},
            ],
        }
    if kind == "media-lead" and media_field:
        return {
            "type": "Row",
            "props": {"gap": "tokens.spacing.4", "align": "center",
                      "data-slot": "record-hero", "data-hero-kind": "media-lead"},
            "children": [
                {"type": "Image", "props": {
                    "src": f"{{{{record.{media_field}}}}}",
                    "alt": title.strip(), "size": "lead"}},
                {"type": "Stack", "props": {"gap": "tokens.spacing.1"}, "children": _title_stack(title, subtitle)},
            ],
        }
    if kind == "editorial":
        children: list[dict] = []
        if eyebrow:
            children.append({"type": "Text",
                              "props": {"content": eyebrow, "variant": "eyebrow",
                                        "align": "center"}})
        children.append({"type": "Heading",
                          "props": {"content": title.strip(), "level": 1, "align": "center"}})
        if subtitle:
            children.append({"type": "Text",
                              "props": {"content": subtitle, "align": "center",
                                        "variant": "caption"}})
        return {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.2", "align": "center",
                      "data-slot": "record-hero", "data-hero-kind": "editorial"},
            "children": children,
        }
    if kind == "breadcrumbs":
        return {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.2",
                      "data-slot": "record-hero", "data-hero-kind": "breadcrumbs"},
            "children": [
                {"type": "Breadcrumbs", "props": {"items": []}},
                *_title_stack(title, subtitle),
            ],
        }

    # Default: page-header.
    return {
        "type": "Stack",
        "props": {"gap": "tokens.spacing.1",
                  "data-slot": "record-hero", "data-hero-kind": "page-header"},
        "children": _title_stack(title, subtitle),
    }


def _title_stack(title: str, subtitle: str | None) -> list[dict]:
    children: list[dict] = [
        {"type": "Heading", "props": {"content": title.strip(), "level": 1}},
    ]
    if subtitle:
        children.append({"type": "Text", "props": {"content": subtitle, "variant": "caption"}})
    return children


def _build_footer_node(footer: Any, *, mode: str) -> Optional[dict]:
    if not isinstance(footer, dict):
        return None
    kind = footer.get("kind")
    if not (isinstance(kind, str) and kind in ("timestamps", "danger-zone", "audit", "related")):
        return None
    content = footer.get("content") if isinstance(footer.get("content"), str) else None

    if kind == "timestamps":
        # Only shows meaningfully on view/edit modes (nothing to show
        # on create). Composer still emits the slot for structural
        # consistency; the runtime hides it when the record isn't loaded.
        return {
            "type": "DescriptionList",
            "props": {
                "items": [
                    {"label": "Created", "value": "{{record.createdAt}}"},
                    {"label": "Updated", "value": "{{record.updatedAt}}"},
                ],
                "data-slot": "record-footer",
                "data-footer-kind": "timestamps",
            },
        }
    if kind == "danger-zone":
        return {
            "type": "Card",
            "props": {
                "padding": "tokens.spacing.6",
                "tone": "danger",
                "data-slot": "record-footer",
                "data-footer-kind": "danger-zone",
            },
            "children": [
                {"type": "Heading", "props": {"content": "Danger zone", "level": 3}},
                {"type": "Text",
                 "props": {"content": content or "Deleting this is permanent."}},
                {"type": "Button",
                 "props": {"label": "Delete", "variant": "danger"}},
            ],
        }
    if kind == "audit":
        return {
            "type": "Row",
            "props": {"justify": "start", "align": "center",
                      "data-slot": "record-footer", "data-footer-kind": "audit"},
            "children": [
                {"type": "Text",
                 "props": {"content": content or "View change history",
                           "variant": "caption"}},
            ],
        }
    # related
    return {
        "type": "Row",
        "props": {"justify": "start", "align": "center", "gap": "tokens.spacing.3",
                  "data-slot": "record-footer", "data-footer-kind": "related"},
        "children": [
            {"type": "Text",
             "props": {"content": content or "Related items", "variant": "caption"}},
        ],
    }


# ─────────────────────────── humanize ──────────────────────────────────


def _humanize(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").strip()
    return " ".join(w.capitalize() for w in s.split())


# ─────────────────────────── authority helpers (Phase 6b) ──────────────


def _is_record_authority_enabled() -> bool:
    """Import-safe check for FORGE_RECORD_AUTHORITY."""
    try:
        from services.artifact_authority import is_authority_enabled
        return is_authority_enabled("record")
    except Exception:  # noqa: BLE001
        return False


def _plan_record_pages(root: Path) -> list[dict]:
    """Return the record-typed pages from ``plan.json``."""
    plan_path = root / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    try:
        from services.artifact_authority import is_page_of_kind
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for p in plan.get("pages") or []:
        if isinstance(p, dict) and is_page_of_kind(p, "record"):
            out.append(p)
    return out


def _fallback_all_records_via_recipe(root: Path, *, reason: str) -> dict[str, Any]:
    """Recipe-fill every record page when NO maquettes file exists."""
    pages = _plan_record_pages(root)
    if not pages:
        return {"applied": 0, "skipped": 0,
                "reasons": [f"{reason}; no record pages in plan"]}
    return _recipe_fill_record_pages(root, pages, reason_prefix=reason)


def _fallback_missing_records_via_recipe(
    root: Path, *, applied_routes: set[str | None],
) -> dict[str, Any]:
    """Recipe-fill record pages not covered by any maquette entry."""
    pages = [p for p in _plan_record_pages(root)
             if p.get("route") not in applied_routes]
    if not pages:
        return {"applied": 0, "reasons": []}
    return _recipe_fill_record_pages(root, pages, reason_prefix="tail-fill (no maquette entry)")


def _recipe_fill_record_pages(root: Path, pages: list[dict], *, reason_prefix: str) -> dict[str, Any]:
    """Deterministic-build each record page via
    :func:`services.deterministic_pages.build_form_page` /
    :func:`~services.deterministic_pages.build_detail_page`.

    Mode inference from route/type: /new → create, /[id]/edit → edit,
    /[id] → view (detail page).
    """
    registry = _load_registry(root)
    entities = registry.get("entities") if isinstance(registry, dict) else {}
    if not isinstance(entities, dict):
        entities = {}
    from services.deterministic_pages import build_form_page, build_detail_page
    applied = 0
    reasons: list[str] = []
    for page in pages:
        route = page.get("route")
        entity = page.get("entity") or page.get("primary_entity")
        if not (isinstance(route, str) and route.startswith("/")):
            continue
        if not (isinstance(entity, str) and entity):
            reasons.append(f"{route}: no entity")
            continue
        entity_meta = entities.get(entity) or {}
        columns = _column_type_map(entity_meta)
        if not columns:
            reasons.append(f"{route}: no entity columns")
            continue

        slug = _route_to_slug(route)
        target = root / "src" / "schemas" / f"{slug}.json"
        # Skip pages the maquette composer already wrote.
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(existing.get("meta"), dict):
                    if existing["meta"].get(_MARKER_META_KEY) is True:
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Infer mode from type+route.
        ptype = str(page.get("type") or page.get("archetype") or "").lower()
        r = route.rstrip("/").lower()
        if ptype in ("form", "create", "new") or r.endswith("/new"):
            mode = "create"
        elif ptype == "edit" or r.endswith("/edit"):
            mode = "edit"
        else:
            mode = "view"

        try:
            if mode == "view":
                schema = build_detail_page(entity, columns, route,
                                            design_spec=None, page_hint=page)
            else:
                op = "create" if mode == "create" else "update"
                schema = build_form_page(entity, columns, route,
                                          design_spec=None, op=op)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            applied += 1
            reasons.append(f"{route}: recipe-filled ({mode} — {reason_prefix})")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[record-maquette] recipe-fill failed for %s: %s", route, exc)
            reasons.append(f"{route}: recipe-fill failed: {exc}")
    return {"applied": applied, "skipped": 0, "reasons": reasons}
