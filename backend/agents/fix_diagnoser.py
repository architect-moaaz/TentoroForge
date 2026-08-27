"""Symptom → structured diagnosis (Slice-1, Task 1-B of the Fix-Assistant).

Given a PLAIN-LANGUAGE symptom ("scheduling an assessment fails to save",
"I can't upload a CV", "the calendar is empty") plus the app's recall context
and the closed-resource context, produce a STRUCTURED diagnosis that locates
the faulty artifact + node/pointer and proposes a fix targeted at a
DETERMINISTIC SEAM (a workflow-node config merge, a page-schema JSON-Patch, or —
last resort, low confidence — a free-form code edit).

Two steps, deterministic-first:

1. CHEAP LOCATE (:func:`cheap_locate`) — NO model. A symptom taxonomy routes the
   symptom to a candidate class ("save/create X fails" → the domain workflow
   whose ``db_insert`` targets X's table; "empty list/calendar" → the page that
   binds that entity; "can't upload" → the entity form's file control; "missing
   field" → the create form) and shortlists the REAL on-disk artifacts (registry
   + grep over ``workflows/`` and ``src/schemas/``), ranked by keyword overlap.

2. CAPABLE PATCH (:func:`diagnose`) — an LLM step through an INJECTABLE
   ``query_fn`` seam (mirrors ``agents/app_map_agent``): it receives the
   shortlisted artifacts' actual JSON + recall + resource ctx and returns the
   structured :data:`Diagnosis`. The default seam hits the real SDK; tests pass
   a fake returning canned structured output, so no model is ever called there.

A ``workflow_node_config`` fix is VALIDATED against
``services.workflow_value_types.analyze_workflow_values`` (the proposed merge is
applied to a copy and re-analyzed — it must come back clean); a dirty result
lowers ``confidence``.

The :data:`Diagnosis` shape is a hard contract shared with the applier (Task
1-C) — do not change it without updating that consumer:

    { "symptom": str, "feature": str, "rootCause": str,
      "artifact": {"kind": "workflow"|"page"|"schema", "path": str},  # rel to output_dir
      "locator": {"nodeId": str|None, "jsonPointer": str|None},
      "proposedFix": {"seam": "workflow_node_config"|"page_schema_patch"|"code_edit",
                      "patch": <object> },
      "confidence": float, "explanation": str,
      "validation": {"clean": bool|None, "remaining": [ ... ]} }

No wall-clock is read here; the module is pure/deterministic aside from the
injected LLM seam.
"""
from __future__ import annotations

import copy
import glob
import inspect
import json
import logging
import os
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

Diagnosis = dict  # documented shape above

_REGISTRY_REL = os.path.join("contracts", "resource-registry.json")
_MUTATION_ACTIONS = {"db_insert", "db_update"}
# Column-name / keyword hints that a column carries an uploaded file.
_FILE_KEYWORDS = (
    "cv", "resume", "file", "upload", "attachment", "attach", "document",
    "photo", "image", "avatar", "logo", "url", "doc",
)
# Data widgets whose emptiness is a binding problem.
_DATA_WIDGETS = (
    "calendar", "table", "list", "board", "grid", "chart", "timeline",
    "resourcetimeline", "kanban", "dashboard", "datatable",
)


# --------------------------------------------------------------------------- #
# Symptom taxonomy — ordered; first match wins.
# --------------------------------------------------------------------------- #

_CANT_UPLOAD_RES = [
    re.compile(r"(can'?t|cannot|unable to|couldn'?t|won'?t|fail\w*)\b[^.]*\b(upload|attach|import)", re.I),
    re.compile(r"\b(upload|attach)(ing|ed)?\b[^.]*\b(fail|not work|broke|error|doesn'?t)", re.I),
    re.compile(r"\b(upload|attach)\b", re.I),
]
_EMPTY_DATA_RES = [
    re.compile(r"\b(empty|blank|no data|nothing|not show\w*|not display\w*|missing)\b[^.]*\b(list|table|calendar|board|grid|dashboard|page|view|schedule|feed)", re.I),
    re.compile(r"\b(list|table|calendar|board|grid|dashboard|feed)\b[^.]*\b(empty|blank|no data|nothing|not show\w*|not load\w*)", re.I),
]
_MISSING_FIELD_RES = [
    re.compile(r"\b(missing|no|there'?s no)\b[^.]*\b(field|input|column|box)\b", re.I),
    re.compile(r"(can'?t|cannot|unable to|no way to)\b[^.]*\b(enter|set|fill|input|type|specify|choose)\b", re.I),
]
_SAVE_CREATE_RES = [
    re.compile(r"\b(save|saving|creat\w*|schedul\w*|submit\w*|add\w*|regist\w*|insert\w*|book\w*|new)\b[^.]*\b(fail|crash|error|not work|won'?t|can'?t|cannot|broke|reject|doesn'?t|nothing happen)", re.I),
    re.compile(r"\b(fail|crash|error|broke|reject|doesn'?t work)\b[^.]*\b(save|creat|schedul|submit|add|regist|insert|book)", re.I),
]

_TAXONOMY: list[tuple[str, list[re.Pattern]]] = [
    ("cant_upload", _CANT_UPLOAD_RES),
    ("empty_data", _EMPTY_DATA_RES),
    ("missing_field", _MISSING_FIELD_RES),
    ("save_create_fails", _SAVE_CREATE_RES),
]


def classify_symptom(symptom: str) -> Optional[str]:
    """Route a plain-language symptom to a taxonomy category (or None)."""
    text = symptom or ""
    for category, patterns in _TAXONOMY:
        if any(p.search(text) for p in patterns):
            return category
    return None


# --------------------------------------------------------------------------- #
# Raw-error parsing (Task 2-A) — a pasted Postgres / workflow / Next stack.
# --------------------------------------------------------------------------- #

# `column "candidate_id" is of type uuid but expression is of type timestamp
#  with time zone`
_PG_TYPE_RE = re.compile(
    r'column\s+"(?P<column>[^"]+)"\s+is of type\s+'
    r'(?P<columnType>[A-Za-z0-9_ ]+?)\s+but expression is of type\s+'
    r'(?P<exprType>[A-Za-z0-9_ ]+?)\s*(?:[.\n]|$)',
    re.I,
)
# `[workflow:assessmentschedulingworkflow] Create Assessment Record: PostgresError: …`
_WORKFLOW_PREFIX_RE = re.compile(r"\[workflow:(?P<wf>[^\]]+)\]\s*(?P<rest>.*)", re.S)
# The node label is the segment before the first `:` that is NOT itself an
# `*Error` token (which starts the error class).
_WF_LABEL_RE = re.compile(r"^\s*(?P<label>[^:\n]+?)\s*:")
# A JS/React stack frame: `at CandidateForm (../src/components/CandidateForm.tsx:42:15)`
_STACK_FRAME_RE = re.compile(
    r"\bat\s+(?P<comp>[A-Za-z0-9_$.]+)\s+"
    r"\((?P<path>[^)\n:]+?\.(?:tsx|jsx|ts|js))(?::\d+(?::\d+)?)?\)"
)
_ERROR_TOKEN_RE = re.compile(r"^\w*Error$")


def _normalize_component_path(raw: str) -> str:
    """Trim a stack-frame path down to an in-app source path.

    ``../src/components/Bar.tsx`` → ``src/components/Bar.tsx``; a path that has no
    ``src/`` segment is returned with any leading ``./`` / ``../`` stripped.
    """
    p = (raw or "").replace("\\", "/").strip()
    idx = p.find("src/")
    if idx >= 0:
        return p[idx:]
    return re.sub(r"^(?:\.\.?/)+", "", p)


def parse_error(error_text: Any) -> Optional[dict]:
    """Parse a RAW error string into a locator seed, or ``None`` if it does not
    look like a machine error (so the caller falls back to the NL taxonomy).

    Precedence: a Postgres value↔type error (``postgres_type_mismatch``) wins,
    then any other ``[workflow:X] …`` prefix (``workflow_error``), then a
    JS/React component stack (``component_stack``). Pure — no I/O, no wall-clock.

    Shape: ``{kind, workflow?, nodeLabel?, table?, column?, columnType?,
    exprType?, rawType?, component?, componentPath?}``.
    """
    if not isinstance(error_text, str):
        return None
    text = error_text.strip()
    if not text:
        return None

    result: dict = {}

    wf_m = _WORKFLOW_PREFIX_RE.search(text)
    if wf_m:
        result["workflow"] = wf_m.group("wf").strip()
        lbl = _WF_LABEL_RE.match(wf_m.group("rest") or "")
        if lbl:
            label = lbl.group("label").strip()
            # Skip a leading `PostgresError` / `TypeError` — that's the class,
            # not the node label.
            if label and not _ERROR_TOKEN_RE.match(label):
                result["nodeLabel"] = label

    pg_m = _PG_TYPE_RE.search(text)
    if pg_m:
        result["kind"] = "postgres_type_mismatch"
        result["column"] = pg_m.group("column").strip()
        result["columnType"] = pg_m.group("columnType").strip()
        result["exprType"] = pg_m.group("exprType").strip()
        result["rawType"] = result["exprType"]
        return result

    if "workflow" in result:
        result["kind"] = "workflow_error"
        return result

    # A component stack: prefer the first in-app (src/…) frame over framework
    # frames (node_modules/react-dom …).
    frames = list(_STACK_FRAME_RE.finditer(text))
    if frames:
        chosen = next((m for m in frames if "src/" in m.group("path")), frames[0])
        return {
            "kind": "component_stack",
            "component": chosen.group("comp"),
            "componentPath": _normalize_component_path(chosen.group("path")),
        }

    return None


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _canon(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _load_registry(output_dir: str) -> dict:
    reg = _read_json(os.path.join(output_dir, _REGISTRY_REL))
    return reg if isinstance(reg, dict) else {}


def _registry_entities(registry: dict) -> list[dict]:
    """Flatten registry entities into ``[{name, slug, table, columns:[...]}]``."""
    ents = registry.get("entities")
    out: list[dict] = []
    if not isinstance(ents, dict):
        return out
    for key, spec in ents.items():
        if not isinstance(spec, dict):
            continue
        out.append({
            "name": spec.get("name") or key,
            "slug": spec.get("slug"),
            "table": spec.get("table"),
            "columns": [c for c in (spec.get("columns") or []) if isinstance(c, dict)],
        })
    return out


def _symptom_stems(symptom: str) -> list[str]:
    """Canonicalized content words (len>=4) used for keyword-overlap ranking."""
    return [_canon(w) for w in re.findall(r"[A-Za-z]+", symptom or "") if len(w) >= 4]


def _match_entities(symptom: str, entities: list[dict]) -> list[dict]:
    """Entities whose name/slug/table (singular or plural) appears in the symptom."""
    canon_sym = _canon(symptom)
    hits: list[dict] = []
    for ent in entities:
        cands = {ent.get("name"), ent.get("slug"), ent.get("table")}
        matched = False
        for c in cands:
            cc = _canon(c)
            if not cc or len(cc) < 3:
                continue
            singular = cc[:-1] if cc.endswith("s") and len(cc) > 3 else cc
            if cc in canon_sym or singular in canon_sym:
                matched = True
                break
        if matched:
            hits.append(ent)
    return hits


def _walk_workflow_mutations(defn: dict):
    """Yield ``(node_id, table, label)`` for each db_insert/db_update node."""
    if not isinstance(defn, dict):
        return
    for node in defn.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        if config.get("actionType") in _MUTATION_ACTIONS:
            yield node.get("id"), config.get("table"), str(data.get("label") or "")


def _list_workflow_files(output_dir: str) -> list[str]:
    return sorted(glob.glob(os.path.join(output_dir, "workflows", "*.json")))


def _rel(output_dir: str, path: str) -> str:
    try:
        return os.path.relpath(path, output_dir).replace(os.sep, "/")
    except ValueError:
        return path


def _find_named_node_pointer(schema: Any, name: str) -> Optional[str]:
    """RFC-6901 JSON pointer to the first node whose ``props.name`` == ``name``.

    Returns e.g. ``/root/children/2`` (a structural path — never contains the
    field name itself), or None.
    """
    target = _canon(name)

    def _walk(node: Any, pointer: str) -> Optional[str]:
        if isinstance(node, dict):
            props = node.get("props")
            nm = None
            if isinstance(props, dict):
                nm = props.get("name")
            if nm is None:
                nm = node.get("name")
            if nm is not None and _canon(nm) == target and node.get("type"):
                return pointer or "/"
            for k, v in node.items():
                found = _walk(v, f"{pointer}/{_escape(k)}")
                if found:
                    return found
        elif isinstance(node, list):
            for i, v in enumerate(node):
                found = _walk(v, f"{pointer}/{i}")
                if found:
                    return found
        return None

    return _walk(schema, "")


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _entity_form_files(output_dir: str, ent: dict) -> list[str]:
    """Create/edit form + list schema files for an entity, if present on disk."""
    slug = ent.get("slug") or _canon(ent.get("name"))
    sdir = os.path.join(output_dir, "src", "schemas")
    candidates = [
        os.path.join(sdir, str(slug), "new.json"),
        os.path.join(sdir, str(slug), "[id].json"),
        os.path.join(sdir, f"{slug}.json"),
    ]
    return [p for p in candidates if os.path.isfile(p)]


# --------------------------------------------------------------------------- #
# Locators (one per taxonomy category)
# --------------------------------------------------------------------------- #

def _locate_save_create(symptom: str, entities: list[dict], output_dir: str) -> list[dict]:
    matched = _match_entities(symptom, entities)
    wanted_tables = {_canon(e.get("table")) for e in matched} if matched else None
    stems = _symptom_stems(symptom)

    artifacts: list[dict] = []
    for wf_path in _list_workflow_files(output_dir):
        wf = _read_json(wf_path)
        if not isinstance(wf, dict):
            continue
        defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
        wid = wf.get("id") or os.path.splitext(os.path.basename(wf_path))[0]
        wname = wf.get("name") or ""
        for node_id, table, label in _walk_workflow_mutations(defn):
            if not table:
                continue
            if wanted_tables is not None and _canon(table) not in wanted_tables:
                continue
            haystack = _canon(f"{wid} {wname} {label}")
            score = sum(1 for s in stems if s and s in haystack)
            artifacts.append({
                "kind": "workflow",
                "path": _rel(output_dir, wf_path),
                "nodeId": node_id,
                "jsonPointer": None,
                "table": table,
                "reason": f"db_insert/db_update into {table}",
                "_score": score,
            })
    # Rank: keyword overlap desc, then path for stability.
    artifacts.sort(key=lambda a: (-a["_score"], a["path"]))
    for a in artifacts:
        a.pop("_score", None)
    return artifacts


def _locate_upload(symptom: str, entities: list[dict], output_dir: str) -> list[dict]:
    canon_sym = _canon(symptom)
    stems = set(_symptom_stems(symptom)) | {_canon(w) for w in re.findall(r"[A-Za-z]+", symptom or "")}

    scored: list[tuple[int, dict, dict]] = []
    for ent in entities:
        for col in ent.get("columns", []):
            cname = col.get("name")
            if not cname:
                continue
            cc = _canon(cname)
            is_fileish = (
                any(kw in cc for kw in _FILE_KEYWORDS)
                or _canon(col.get("type")) in {"file"}
            )
            if not is_fileish:
                continue
            # Score: does a symptom token appear in the column name (e.g. "cv").
            score = 0
            for kw in _FILE_KEYWORDS:
                if kw in cc and kw in canon_sym:
                    score += 2
            if cc in canon_sym or any(s and s in cc for s in stems):
                score += 1
            scored.append((score, ent, col))

    scored.sort(key=lambda t: -t[0])

    artifacts: list[dict] = []
    for _score, ent, col in scored:
        for form_path in _entity_form_files(output_dir, ent):
            schema = _read_json(form_path)
            pointer = _find_named_node_pointer(schema, col["name"]) if schema else None
            if pointer is None:
                continue
            artifacts.append({
                "kind": "page",
                "path": _rel(output_dir, form_path),
                "nodeId": None,
                "jsonPointer": pointer,
                "entity": ent.get("name"),
                "column": col["name"],
                "reason": f"file control for {ent.get('name')}.{col['name']}",
            })
    return artifacts


def _walk_widgets(schema: Any, pointer: str = ""):
    if isinstance(schema, dict):
        t = schema.get("type")
        if t:
            yield _canon(t), pointer or "/", schema
        for k, v in schema.items():
            yield from _walk_widgets(v, f"{pointer}/{_escape(k)}")
    elif isinstance(schema, list):
        for i, v in enumerate(schema):
            yield from _walk_widgets(v, f"{pointer}/{i}")


def _locate_empty_data(symptom: str, entities: list[dict], output_dir: str) -> list[dict]:
    canon_sym = _canon(symptom)
    wanted_widgets = [w for w in _DATA_WIDGETS if w in canon_sym]
    matched = _match_entities(symptom, entities)
    matched_slugs = {_canon(e.get("slug")) for e in matched}

    artifacts: list[dict] = []
    for page_path in sorted(glob.glob(os.path.join(output_dir, "src", "schemas", "**", "*.json"), recursive=True)):
        schema = _read_json(page_path)
        if not isinstance(schema, dict):
            continue
        for wtype, pointer, node in _walk_widgets(schema):
            if wanted_widgets and wtype not in wanted_widgets:
                continue
            if not wanted_widgets and wtype not in _DATA_WIDGETS:
                continue
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            ds = props.get("dataSource") or props.get("optionsFrom") or props.get("rows")
            score = 2 if wanted_widgets else 0
            if matched_slugs and _canon(ds) in matched_slugs:
                score += 1
            artifacts.append({
                "kind": "page",
                "path": _rel(output_dir, page_path),
                "nodeId": None,
                "jsonPointer": pointer,
                "widget": wtype,
                "dataSource": ds,
                "reason": f"{wtype} data binding",
                "_score": score,
            })
    artifacts.sort(key=lambda a: (-a["_score"], a["path"]))
    for a in artifacts:
        a.pop("_score", None)
    return artifacts


def _locate_missing_field(symptom: str, entities: list[dict], output_dir: str) -> list[dict]:
    matched = _match_entities(symptom, entities) or entities
    artifacts: list[dict] = []
    for ent in matched:
        for form_path in _entity_form_files(output_dir, ent):
            artifacts.append({
                "kind": "page",
                "path": _rel(output_dir, form_path),
                "nodeId": None,
                "jsonPointer": None,
                "entity": ent.get("name"),
                "reason": f"create/edit form completeness for {ent.get('name')}",
            })
    return artifacts


_LOCATORS: dict[str, Callable[[str, list[dict], str], list[dict]]] = {
    "save_create_fails": _locate_save_create,
    "cant_upload": _locate_upload,
    "empty_data": _locate_empty_data,
    "missing_field": _locate_missing_field,
}


# --------------------------------------------------------------------------- #
# Error-seeded locators (Task 2-A) — higher precision than the NL taxonomy.
# --------------------------------------------------------------------------- #

def _locate_error_workflow(parsed: dict, output_dir: str) -> list[dict]:
    """Locate the workflow + db_insert/db_update node a parsed workflow/Postgres
    error points at. Prefers the node whose ``config.values`` writes the errored
    column; falls back to the node label, then the first mutation node."""
    wf_id = parsed.get("workflow")
    col_canon = _canon(parsed.get("column")) if parsed.get("column") else None
    label_canon = _canon(parsed.get("nodeLabel")) if parsed.get("nodeLabel") else None

    registry = _load_registry(output_dir)
    try:
        from services.workflow_value_types import (
            analyze_workflow_values,
            columns_by_table_from_registry,
        )
        cbt = columns_by_table_from_registry(registry)
    except Exception:  # noqa: BLE001
        analyze_workflow_values = None  # type: ignore[assignment]
        cbt = {}

    artifacts: list[dict] = []
    for wf_path in _list_workflow_files(output_dir):
        wf = _read_json(wf_path)
        if not isinstance(wf, dict):
            continue
        wid = wf.get("id") or os.path.splitext(os.path.basename(wf_path))[0]
        if wf_id and _canon(wid) != _canon(wf_id) and _canon(wf.get("name")) != _canon(wf_id):
            continue
        defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}

        best: Optional[tuple[int, Any, Any, Any]] = None  # (score, node_id, table, col_key)
        for node in defn.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            config = data.get("config") if isinstance(data.get("config"), dict) else {}
            if config.get("actionType") not in _MUTATION_ACTIONS:
                continue
            values = config.get("values") if isinstance(config.get("values"), dict) else {}
            col_key = None
            score = 0
            if col_canon:
                for k in values:
                    if _canon(k) == col_canon:
                        col_key = k
                        score += 3
                        break
            if label_canon and _canon(data.get("label")) == label_canon:
                score += 1
            if best is None or score > best[0]:
                best = (score, node.get("id"), config.get("table"), col_key)

        if best is None:
            continue
        _score, node_id, table, col_key = best
        art = {
            "kind": "workflow",
            "path": _rel(output_dir, wf_path),
            "nodeId": node_id,
            "jsonPointer": None,
            "table": table,
            "column": col_key,
            "reason": (
                f"{parsed.get('kind')}: {col_key or parsed.get('column') or 'node'}"
                + (f" ({parsed.get('rawType')} into {parsed.get('columnType')})"
                   if parsed.get("columnType") else "")
            ),
        }
        # Bonus: cross-check with the value↔type analyzer so the fix is
        # pre-validated (the same mismatch class the applier re-verifies).
        if analyze_workflow_values is not None:
            try:
                findings = analyze_workflow_values(defn, cbt)
                related = [
                    f for f in findings
                    if col_canon and _canon(f.get("column")) == col_canon
                ] or findings
                if related:
                    art["analysis"] = related
            except Exception:  # noqa: BLE001
                pass
        artifacts.append(art)

    return artifacts


def _locate_component_stack(parsed: dict, output_dir: str) -> list[dict]:
    """Locate the page/component artifact a JS/React stack points at."""
    comp_path = parsed.get("componentPath")
    if not comp_path:
        return []
    exists = os.path.isfile(os.path.join(output_dir, comp_path))
    return [{
        "kind": "page",
        "path": comp_path,
        "nodeId": None,
        "jsonPointer": None,
        "component": parsed.get("component"),
        "reason": f"component stack frame {parsed.get('component') or comp_path}",
        "exists": exists,
    }]


def _locate_from_error(parsed: dict, output_dir: str) -> list[dict]:
    kind = parsed.get("kind")
    try:
        if kind == "component_stack":
            return _locate_component_stack(parsed, output_dir)
        return _locate_error_workflow(parsed, output_dir)
    except Exception:  # noqa: BLE001 — an error-locator bug must not crash diagnosis
        logger.exception("fix_diagnoser: error locator %s failed", kind)
        return []


def cheap_locate(symptom: str, output_dir: str, *, resource_ctx: str | None = None) -> dict:
    """Deterministically shortlist candidate artifacts for a symptom — NO model.

    Returns ``{"category", "entity", "artifacts": [ {kind, path, nodeId,
    jsonPointer, ...}, ... ]}`` ranked best-first. ``resource_ctx`` is accepted
    for signature symmetry with :func:`diagnose` but is not required — the real
    entities are read straight from the resource registry.

    A message that IS a raw error string (Postgres / ``[workflow:X]`` / a JS
    stack) is routed through :func:`parse_error` FIRST for a higher-precision
    locate; it falls back to the NL symptom taxonomy when the error yields no
    on-disk artifact.
    """
    registry = _load_registry(output_dir)
    entities = _registry_entities(registry)

    parsed = parse_error(symptom)
    if parsed:
        err_artifacts = _locate_from_error(parsed, output_dir)
        if err_artifacts:
            return {
                "category": parsed.get("kind"),
                "entity": None,
                "artifacts": err_artifacts,
                "parsedError": parsed,
            }

    category = classify_symptom(symptom)

    matched = _match_entities(symptom, entities)
    entity_name = matched[0].get("name") if matched else None

    artifacts: list[dict] = []
    if category and category in _LOCATORS:
        try:
            artifacts = _LOCATORS[category](symptom, entities, output_dir)
        except Exception:  # noqa: BLE001 — a locator bug must not crash diagnosis
            logger.exception("fix_diagnoser: locator %s failed", category)
            artifacts = []

    return {"category": category, "entity": entity_name, "artifacts": artifacts}


# --------------------------------------------------------------------------- #
# Workflow-patch validation (analyze-clean check)
# --------------------------------------------------------------------------- #

def _find_wf_node(defn: dict, node_id: str) -> Optional[dict]:
    for n in (defn.get("nodes") or []):
        if isinstance(n, dict) and (n.get("id") == node_id or (n.get("data") or {}).get("id") == node_id):
            return n
    return None


def validate_workflow_patch(
    output_dir: str,
    workflow_path: str,
    node_id: str,
    patch: dict,
) -> dict:
    """Apply a ``workflow_node_config`` merge to a COPY and re-analyze.

    Mirrors the applier's shallow ``config.update(patch)`` merge (the same
    semantics as ``routers/workflows.py`` node PATCH), then runs
    ``analyze_workflow_values`` over the patched definition. Returns
    ``{"clean": bool, "remaining": [findings]}``. Never raises.
    """
    from services.workflow_value_types import (
        analyze_workflow_values,
        columns_by_table_from_registry,
    )

    try:
        wf_abs = workflow_path if os.path.isabs(workflow_path) else os.path.join(output_dir, workflow_path)
        wf = _read_json(wf_abs)
        if not isinstance(wf, dict):
            return {"clean": False, "remaining": [{"reason": "workflow not readable"}]}
        defn = copy.deepcopy(wf.get("definition") or {})
        node = _find_wf_node(defn, node_id)
        if node is None:
            return {"clean": False, "remaining": [{"reason": f"node {node_id} not found"}]}
        cfg = node.setdefault("data", {}).setdefault("config", {})
        if isinstance(patch, dict):
            cfg.update(patch)  # shallow merge — same as the node-PATCH seam

        registry = _load_registry(output_dir)
        cbt = columns_by_table_from_registry(registry)
        findings = analyze_workflow_values(defn, cbt)
        return {"clean": not findings, "remaining": findings}
    except Exception:  # noqa: BLE001
        logger.exception("fix_diagnoser: workflow patch validation error")
        return {"clean": False, "remaining": [{"reason": "validation error"}]}


# --------------------------------------------------------------------------- #
# Capable-patch prompt + LLM seam
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """You are a senior engineer diagnosing a defect in a GENERATED
application. You are given a plain-language SYMPTOM, the app's generation recall
(its intent, entities, workflows), the closed set of REAL backend resources, and
the ACTUAL JSON of the artifact(s) a deterministic locator already shortlisted.

Return a SINGLE JSON object (no prose, no markdown fences) with EXACTLY this shape:

{
  "feature": "<what this feature is meant to do, from recall>",
  "rootCause": "<the precise defect>",
  "artifact": {"kind": "workflow"|"page"|"schema", "path": "<path from the shortlist>"},
  "locator": {"nodeId": "<workflow node id or null>", "jsonPointer": "<RFC-6901 pointer or null>"},
  "proposedFix": {
     "seam": "workflow_node_config" | "page_schema_patch" | "code_edit",
     "patch": <object>
  },
  "confidence": <0..1>,
  "explanation": "<plain-language, for the END USER>"
}

RULES:
- Target a DETERMINISTIC SEAM. For a workflow node bug use seam
  "workflow_node_config" and a patch that is a CONFIG-MERGE dict, e.g.
  {"values": { ...the FULL corrected values map... }}. The merge REPLACES the
  node's `values`, so include every column that should be written — rebind a
  wrong literal to its "{{input}}" binding; never invent a uuid; drop a column
  you cannot correct so it takes its DB default.
- For a page/form control or binding bug use seam "page_schema_patch" and a
  patch that is a LIST of RFC-6902 operations against the page schema.
- "code_edit" is the LAST RESORT — only when neither structured seam fits; set a
  LOW confidence.
- Bind ONLY to resources that exist in the closed resource set. Never invent a
  column, entity, or workflow id.
"""


def _default_query(system_prompt: str, user_prompt: str) -> str:  # pragma: no cover - network
    """Default LLM boundary — a single headless Anthropic call. Injected over in
    tests via ``query_fn``; never hit there."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "diagnose requires ANTHROPIC_API_KEY (or an injected query_fn)."
        )
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(b.text for b in msg.content if hasattr(b, "text"))


def _artifact_json_block(output_dir: str, artifacts: list[dict], limit: int = 2) -> str:
    """Embed the actual JSON of the top shortlisted artifacts for the prompt."""
    blocks: list[str] = []
    for a in artifacts[:limit]:
        abs_path = os.path.join(output_dir, a["path"])
        content = _read_json(abs_path)
        if content is None:
            continue
        blocks.append(
            f"### Artifact: {a['path']} (kind={a['kind']}"
            + (f", node={a['nodeId']}" if a.get("nodeId") else "")
            + (f", pointer={a['jsonPointer']}" if a.get("jsonPointer") else "")
            + ")\n```json\n"
            + json.dumps(content, indent=2)
            + "\n```"
        )
    return "\n\n".join(blocks)


def _extract_json_object(text: str) -> Optional[dict]:
    """Parse the first top-level JSON object out of an LLM response."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    # find the first balanced object
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[start:i + 1])
                except ValueError:
                    return None
    return None


# --------------------------------------------------------------------------- #
# diagnose — the public two-step entry point
# --------------------------------------------------------------------------- #

def _fallback_diagnosis(symptom: str, category: Optional[str]) -> Diagnosis:
    return {
        "symptom": symptom,
        "feature": "unknown",
        "rootCause": "Could not localize the fault from the symptom + artifacts.",
        "artifact": {"kind": "code", "path": None},
        "locator": {"nodeId": None, "jsonPointer": None},
        "proposedFix": {"seam": "code_edit", "patch": {}},
        "confidence": 0.15,
        "explanation": (
            "I could not pin this down to a specific workflow or page from the "
            "description. Could you share the exact screen or the error you see?"
        ),
        "validation": {"clean": None, "remaining": []},
        "category": category,
    }


def diagnose(
    symptom: str,
    output_dir: str,
    *,
    recall: Any = None,
    resource_ctx: str | None = None,
    query_fn: Callable[[str, str], Any] | None = None,
) -> Diagnosis:
    """Diagnose a plain-language symptom into a structured, seam-targeted fix.

    Step 1 cheap-locates candidate artifacts deterministically; step 2 asks the
    injectable ``query_fn`` (default: real SDK) to author the structured
    diagnosis against those artifacts' actual JSON. A ``workflow_node_config``
    fix is validated with ``analyze_workflow_values``; a dirty result lowers the
    confidence. When nothing can be located, returns a low-confidence
    ``code_edit`` fallback WITHOUT calling the model.
    """
    loc = cheap_locate(symptom, output_dir, resource_ctx=resource_ctx)
    artifacts = loc["artifacts"]
    if not artifacts:
        return _fallback_diagnosis(symptom, loc["category"])

    # Assemble recall / resource ctx if the caller did not supply them.
    recall_block = ""
    if recall is not None and hasattr(recall, "to_prompt_block"):
        recall_block = recall.to_prompt_block()
    elif recall is None:
        try:
            from services.app_recall import assemble_recall
            recall_block = assemble_recall(output_dir).to_prompt_block()
        except Exception:  # noqa: BLE001
            recall_block = ""
    if resource_ctx is None:
        try:
            from services.resource_registry_context import build_resource_context
            resource_ctx = build_resource_context(output_dir)
        except Exception:  # noqa: BLE001
            resource_ctx = ""

    shortlist = "\n".join(
        f"- {a['kind']} {a['path']}"
        + (f" node={a['nodeId']}" if a.get("nodeId") else "")
        + (f" pointer={a['jsonPointer']}" if a.get("jsonPointer") else "")
        + (f" ({a['reason']})" if a.get("reason") else "")
        for a in artifacts[:4]
    )
    user_prompt = (
        f"SYMPTOM: {symptom}\n"
        f"TAXONOMY CLASS: {loc['category']}\n\n"
        f"## Generation recall\n{recall_block or '(none)'}\n\n"
        f"{resource_ctx or ''}\n\n"
        f"## Shortlisted artifacts (cheap-locate)\n{shortlist}\n\n"
        f"{_artifact_json_block(output_dir, artifacts)}\n\n"
        "Return the diagnosis JSON now."
    )

    fn = query_fn or _default_query
    result = fn(_SYSTEM_PROMPT, user_prompt)
    if inspect.isawaitable(result):
        import asyncio
        result = asyncio.run(result)

    raw = result if isinstance(result, dict) else _extract_json_object(result)
    if not isinstance(raw, dict):
        logger.warning("fix_diagnoser: unparseable diagnosis response")
        return _fallback_diagnosis(symptom, loc["category"])

    return _normalize_diagnosis(symptom, raw, loc, output_dir)


def _normalize_diagnosis(symptom: str, raw: dict, loc: dict, output_dir: str) -> Diagnosis:
    """Coerce the LLM object into the exact Diagnosis contract, defaulting
    missing fields from the cheap-locate shortlist, then validate."""
    top = loc["artifacts"][0]

    artifact = raw.get("artifact") if isinstance(raw.get("artifact"), dict) else {}
    artifact = {
        "kind": artifact.get("kind") or top["kind"],
        "path": artifact.get("path") or top["path"],
    }
    locator = raw.get("locator") if isinstance(raw.get("locator"), dict) else {}
    locator = {
        "nodeId": locator.get("nodeId", top.get("nodeId")),
        "jsonPointer": locator.get("jsonPointer", top.get("jsonPointer")),
    }
    fix = raw.get("proposedFix") if isinstance(raw.get("proposedFix"), dict) else {}
    seam = fix.get("seam") or _default_seam(top["kind"])
    patch = fix.get("patch")
    if patch is None:
        patch = {} if seam != "page_schema_patch" else []

    try:
        confidence = float(raw.get("confidence", 0.6))
    except (TypeError, ValueError):
        confidence = 0.6

    diag: Diagnosis = {
        "symptom": symptom,
        "feature": raw.get("feature") or "unknown",
        "rootCause": raw.get("rootCause") or "",
        "artifact": artifact,
        "locator": locator,
        "proposedFix": {"seam": seam, "patch": patch},
        "confidence": confidence,
        "explanation": raw.get("explanation") or "",
        "validation": {"clean": None, "remaining": []},
        "category": loc["category"],
    }

    # Validate a workflow-config fix against the value↔type checker.
    if seam == "workflow_node_config" and locator.get("nodeId"):
        validation = validate_workflow_patch(
            output_dir, artifact["path"], locator["nodeId"],
            patch if isinstance(patch, dict) else {},
        )
        diag["validation"] = validation
        if not validation["clean"]:
            diag["confidence"] = min(confidence, 0.25)
            diag["explanation"] = (
                (diag["explanation"] + " ").strip()
                + "(Heads up: the proposed change still leaves a type mismatch — "
                "review before applying.)"
            )

    # code_edit is last-resort — never present it as high confidence.
    if seam == "code_edit":
        diag["confidence"] = min(diag["confidence"], 0.3)

    return diag


def _default_seam(kind: str) -> str:
    if kind == "workflow":
        return "workflow_node_config"
    if kind in ("page", "schema"):
        return "page_schema_patch"
    return "code_edit"
