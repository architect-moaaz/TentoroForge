"""Give form fields the RIGHT input control for their data.

The page agent tends to emit every field as a plain text `Input`. This
deterministic pass re-types each form field from what we actually know about the
column + seed plan:

  - enum-ish columns (status, category, type, gender, …) → `Select` with real
    options, sourced from the seed plan's faker `arrayElement[...]` recipes and,
    for status fields, the entity's status workflow.
  - numeric columns / names (dailyRate, price, quantity, …) → `NumberInput`
    (a stepper) with min/step.
  - date columns/names → `DatePicker`; booleans → `Switch`; long text → `Textarea`.

Best-effort + idempotent: relational FK dropdowns (props.optionsFrom, wired by the
binding pass) are left untouched, and a field already of the right type is skipped.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any

from services.workflow_action_mapper import _ent_key, index_status_workflows

_NUMERIC_TYPES = {
    "integer", "int", "int2", "int4", "int8", "bigint", "smallint", "serial",
    "bigserial", "numeric", "decimal", "real", "double", "double precision",
    "float", "float4", "float8", "money",
}
_DATE_TYPES = {"timestamp", "timestamptz", "date", "time", "datetime"}
_TEXT_TYPES = {"text"}

# A foreign-key column ("candidateId", "recruitmentDriveId") is a RELATIONAL picker,
# never a scalar control. Case-sensitive `Id` suffix (a letter/digit then "Id" at the
# end) — matches the deterministic builder's `endsWith("Id")` FK convention. Detecting
# it FIRST stops "candidateId" (contains "date") falling through to a DatePicker.
_re_fk = re.compile(r"[A-Za-z0-9]Id$")

_ENUM_RE = re.compile(
    r"(status|category|categories|type|tier|priority|state|role|method|condition|"
    r"gender|stage|kind|plan|frequency|department|region|currency|severity|grade|"
    r"classification|mode|format|source|channel|specialization|membership)", re.I)

# Name-fallback regexes — matched against the SPACE-SEPARATED word tokens of a name
# ("pipelineStage" -> "pipeline stage"), so `\b` boundaries can't fire mid-word:
# "age" won't match inside "stage"/"message"/"image", "date" won't match "candidate".
_NAME_MONEY_RE = re.compile(
    r"\b(rate|price|amount|cost|fee|total|salary|balance|budget|revenue|charge|"
    r"subtotal|tax|discount|wage|payment)\b")
_NAME_QTY_RE = re.compile(
    r"\b(qty|quantity|count|units?|stock|hours?|days?|minutes?|duration|weight|"
    r"height|age|points?|capacity|seats?|number|num|score|level|floor|rooms?)\b")
_NAME_DATE_RE = re.compile(
    r"\b(date|dob|birthday|deadline|due|scheduled|expires?)\b|\bat$")
# Boolean name heuristic — anchored to whole word tokens (see `_is_bool_name`), not a
# raw regex on the column name (which false-positived "candidateName"/"cancelReason"
# because a case-insensitive `[A-Z_]` matched a lowercase letter after "is"/"can").
_BOOL_VERB_TOKENS = {
    "is", "has", "can", "should", "are", "was", "does", "did", "allow", "allows",
    "enable", "enables", "require", "requires", "include", "includes"}
_BOOL_ADJ_TOKENS = {
    "active", "inactive", "enabled", "disabled", "paid", "unpaid", "verified",
    "completed", "archived", "published", "unpublished", "deleted", "featured",
    "required", "visible", "hidden", "approved", "rejected", "locked", "default",
    "primary"}
_NAME_TEXT_RE = re.compile(
    r"\b(description|notes?|bio|comments?|address|summary|content|body|"
    r"messages?|remarks?|details?|instructions?)\b")

_NAME_PASSWORD_RE = re.compile(r"\b(password|passwd|pwd|secret)\b")


def _is_password_name(name: str) -> bool:
    """Column whose name reads as a credential — must render masked, never
    plain-text. Matches on tokenized name so ``passwordHash`` fires but a
    ``lastPassed`` doesn't."""
    return bool(_NAME_PASSWORD_RE.search(_name_tokens(name)))

# Document / file / image columns are stored as a text or varchar URL (or storage
# key/path) but must render a FileUpload, never a Textarea. Matches a document/file
# noun as a WHOLE token — optionally followed by a storage-suffix token
# (url/file/key/path/uri) — so `cvUrl` ("cv url"), `resumeFile`, `avatarKey`, and a
# bare `document`/`photo` all fire, while a long-text column (description/notes/
# summary/bio/content/message/address) and a non-document `*Url` (profileUrl/
# websiteUrl) do NOT. Anchored to whole word tokens (matched against `_name_tokens`
# output) so a substring can never fire mid-word. `file` is both a noun and a
# suffix, which is fine.
_NAME_FILE_RE = re.compile(
    r"\b(cv|resume|resumé|résumé|attachment|document|file|photo|avatar|image|logo|"
    r"upload|headshot|scan)\b(\s+(url|file|key|path|uri))?")

# Field nodes we're willing to re-type (never touch layout/display nodes). FileUpload
# is included so the re-typer treats a document/file node as authoritative — it derives
# FileUpload again via `resolve_control` and never downgrades it to a Textarea/Input.
_FIELD_TYPES = {"Input", "Textarea", "Select", "NumberInput", "DatePicker", "Switch",
                "Combobox", "FileUpload", "MoneyInput", "MoneyDisplay"}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _label(name: str) -> str:
    s = re.sub(r"(_|(?<=[a-z])(?=[A-Z]))", " ", str(name or "")).strip()
    return (s[:1].upper() + s[1:]) if s else str(name or "")


def harvest_seed_options(output_dir: str) -> dict[str, dict[str, list[str]]]:
    """{entity_key -> {norm_col -> [values]}} from the seed plan's faker
    `arrayElement[a,b,c]` recipes — the declared enum values per column."""
    out: dict[str, dict[str, list[str]]] = {}
    path = os.path.join(output_dir, "contracts", "seed-plan.json")
    try:
        with open(path, encoding="utf-8") as fh:
            plan = json.load(fh)
    except Exception:
        return out
    fg = plan.get("field_generators") or {}
    for table, cols in fg.items():
        if not isinstance(cols, dict):
            continue
        cmap: dict[str, list[str]] = {}
        for col, recipe in cols.items():
            if not isinstance(recipe, str):
                continue
            m = re.search(r"arrayElement\[([^\]]+)\]", recipe)
            if m:
                vals = [v.strip() for v in m.group(1).split(",") if v.strip()]
                if vals:
                    cmap[_norm(col)] = vals
        if cmap:
            out[_ent_key(table)] = cmap
    return out


# Columns whose values read as a bounded state machine (a status/stage/phase enum),
# NOT free text. We only harvest a workflow's literal assignments/comparisons for
# these — so a `{recruiterNotes: "Great candidate"}` never becomes a Select option.
_ENUMISH_COLS = {
    "status", "stage", "pipelinestage", "state", "phase", "priority",
    "severity", "type", "kind", "tier", "category",
}


def _is_enumish_col(col: Any) -> bool:
    c = str(col or "").strip().lower()
    return c in _ENUMISH_COLS or c.endswith(("status", "stage", "state"))


_EXPR_LITERAL_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:==?|=)\s*'([^']+)'")

# A state-setting node's label names its transition TARGET ("Set Returned",
# "Mark as Cancelled", "Update Shipped"). Stripping the leading verb yields the
# status literal — the real vocabulary that `values:{status:"{{status}}"}` templates
# hide from the literal harvester.
_LABEL_VERB_RE = re.compile(
    r"^\s*(?:set|mark|update|change|move|transition|flag)(?:\s+(?:as|to))?\s+", re.I)


def _status_from_label(label: Any) -> str | None:
    """"Set Returned" -> "Returned", "Mark as Cancelled" -> "Cancelled". Returns None
    when the text has no recognized leading verb (so a free-form label isn't harvested)."""
    s = str(label or "").strip()
    if not s:
        return None
    m = _LABEL_VERB_RE.match(s)
    if not m:
        return None
    rest = s[m.end():].strip()
    return rest or None


def harvest_workflow_statuses(output_dir: str) -> dict[str, list[str]]:
    """{column -> [literal values]} harvested from generated workflows — the real
    enum source for faithful-gen apps, whose status/stage vocabulary lives in the
    workflow that assigns/compares those columns, not in the (plain varchar) schema.

    Only LITERAL strings are collected (skips `{{template}}` refs, empty, and
    passthrough variable bindings where the value equals its column name). Loose
    `values`/expression sources are gated to enum-ish columns so free text isn't
    mistaken for an enum. Column keys are lowercased; values dedupe first-seen."""
    out: dict[str, list[str]] = {}

    def add(col: Any, val: Any) -> None:
        key = str(col or "").strip().lower()
        v = str(val).strip()
        if not key or not v or v.startswith("{{"):
            return
        lst = out.setdefault(key, [])
        if v not in lst:
            lst.append(v)

    for fp in sorted(glob.glob(os.path.join(output_dir, "workflows", "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                wf = json.load(fh)
        except Exception:
            continue
        defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else wf
        nodes = defn.get("nodes") if isinstance(defn, dict) else None
        if not isinstance(nodes, list):
            nodes = wf.get("nodes") if isinstance(wf.get("nodes"), list) else []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            # Config may live under `data.config` (relay workflows) or directly on the
            # node (`config`) — accept both.
            cfg = n["data"].get("config") if isinstance(n.get("data"), dict) else None
            if not isinstance(cfg, dict):
                cfg = n.get("config")
            if not isinstance(cfg, dict):
                cfg = {}

            # (a) explicit status assignment — always a status literal.
            sv = cfg.get("statusValue")
            if isinstance(sv, str) and sv.strip() and not sv.startswith("{{"):
                add(cfg.get("column") or cfg.get("field") or "status", sv)

            # (b) db_insert/db_update `values` map — enum-ish columns only, and never
            #     a passthrough binding ({col: 'col'}), which is a variable ref.
            vals = cfg.get("values")
            status_col = None  # the enum-ish column this node sets (for label harvest)
            if isinstance(vals, dict):
                for col, val in vals.items():
                    if _is_enumish_col(col) and status_col is None:
                        status_col = col
                    if not isinstance(val, str):
                        continue
                    v = val.strip()
                    if not v or v.startswith("{{"):
                        continue
                    if v.lower() == str(col).strip().lower():
                        continue  # passthrough variable binding, not a literal
                    if _is_enumish_col(col):
                        add(col, v)

            # (c) gateway/condition expression: `col == 'Literal'` — enum-ish only.
            for ek in ("expression", "condition"):
                expr = cfg.get(ek)
                if isinstance(expr, str) and expr:
                    for m in _EXPR_LITERAL_RE.finditer(expr):
                        if _is_enumish_col(m.group(1)):
                            add(m.group(1), m.group(2))

            # (d) State-setting node label/title → status literal. Faithful-gen apps
            #     write transition targets as `values:{status:"{{status}}"}` (a template,
            #     skipped by (b)) and put the real target in the node label ("Set
            #     Returned"). Harvest it whenever the node sets a status column.
            if status_col is None and isinstance(sv, str) and sv.strip():
                status_col = cfg.get("column") or cfg.get("field") or "status"
            if status_col is not None:
                for lk in ("label", "title"):
                    raw = n.get(lk)
                    if raw is None and isinstance(n.get("data"), dict):
                        raw = n["data"].get(lk)
                    lit = _status_from_label(raw)
                    if lit:
                        add(status_col, lit)

    return out


def _registry_enum_values(output_dir: str) -> dict[str, dict[str, list[str]]]:
    """{entity_key -> {norm_col -> [values]}} from registry `enum_values`
    (Drizzle `.$type<>()` / pgEnum) — the schema-declared enum source."""
    out: dict[str, dict[str, list[str]]] = {}
    try:
        with open(os.path.join(output_dir, "registry.json"), encoding="utf-8") as fh:
            reg = json.load(fh)
    except Exception:
        return out
    for name, ent in (reg.get("entities") or {}).items():
        fields = (ent or {}).get("fields") or {}
        if not isinstance(fields, dict):
            continue
        cmap: dict[str, list[str]] = {}
        for col, meta in fields.items():
            if not isinstance(meta, dict):
                continue
            ev = meta.get("enum_values") or meta.get("enumValues")
            if isinstance(ev, list):
                vals = [str(v) for v in ev if v not in (None, "")]
                if vals:
                    cmap[_norm(col)] = vals
        if cmap:
            out[_ent_key(name)] = cmap
    return out


def _registry_types(output_dir: str) -> dict[str, dict[str, str]]:
    """{entity_key -> {norm_col -> sql_type}} from registry.json."""
    out: dict[str, dict[str, str]] = {}
    try:
        with open(os.path.join(output_dir, "registry.json"), encoding="utf-8") as fh:
            reg = json.load(fh)
    except Exception:
        return out
    for name, ent in (reg.get("entities") or {}).items():
        fields = (ent or {}).get("fields") or {}
        if isinstance(fields, dict):
            out[_ent_key(name)] = {
                _norm(c): str((m or {}).get("type", "")).lower() for c, m in fields.items()
            }
    return out


_GENERIC_STEMS = {"new", "edit", "create", "detail", "details", "id", "[id]", "form", "view", "show"}


def _entity_key_for_file(path: str, known: set[str]) -> str | None:
    """Infer a schema file's entity from its name (rentals-new → rental) — or, for
    a nested form like `bookings/new.json` / `bookings/[id]/edit.json`, from the
    parent directory ('bookings') since the basename is generic."""
    base = os.path.basename(path)[:-5]
    stem = re.sub(r"[-_/](new|edit|create|detail|details|list|form|view|show|page)$", "", base)
    stem = stem.rsplit("/", 1)[-1].rsplit("-", 1)[0] if "-" in stem else stem
    for cand in (stem, base):
        k = _ent_key(cand)
        if k and k in known:
            return k
    # Nested form pages: the meaningful segment is the parent dir, not "new"/"[id]".
    if _ent_key(base) in {_ent_key(s) for s in _GENERIC_STEMS} or not stem:
        parts = [p for p in os.path.dirname(path).replace("\\", "/").split("/")
                 if p and _ent_key(p) not in {_ent_key(s) for s in _GENERIC_STEMS}]
        for seg in reversed(parts):
            k = _ent_key(seg)
            if k in known:
                return k
    return None


def _entity_from_form_workflow(schema: dict, known) -> str | None:
    """Resolve a form's entity KEY from its Create/Update<Entity> Form workflow —
    unambiguous, unlike a short route segment ('bookings' → Booking? ClassBooking?).
    `known` is any iterable of entity names/keys (a registry dict or a key set)."""
    known_keys = {_ent_key(n) for n in known}
    for n in _iter_nodes(schema):
        if n.get("type") != "Form":
            continue
        wf = (n.get("props") or {}).get("workflow")
        m = re.match(r"^(Create|Update)([A-Z]\w+)$", str(wf or ""))
        if m:
            k = _ent_key(m.group(2))
            if k in known_keys:
                return k
    return None


def _iter_nodes(schema: dict):
    stack = [schema.get("root") or schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)


def _name_tokens(name: str) -> str:
    """Lowercase, space-separated word tokens from a camelCase / snake / kebab name
    ("pipelineStage" -> "pipeline stage", "startDate" -> "start date"), so anchored
    `\\b` name regexes match whole words only — never a substring like "age" in
    "stage" or "date" in "candidate"."""
    s = re.sub(r"[^A-Za-z0-9]+", " ", str(name or ""))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)      # fooBar -> foo Bar
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)     # HTTPServer -> HTTP Server
    return s.lower().strip()


def _is_money(name: str, sql_type: str) -> bool:
    """True when a numeric field represents CURRENCY — a `money` SQL type or a
    money-named column (price/rate/cost/amount/fee/total/balance/salary/…). Matched on
    whole word tokens so `*Rate`/`*Cost`/`*Price`/`*Amount` (dailyRate → "daily rate")
    fire without a mid-word substring firing. Currency fields get a plain number control
    (no +/- stepper); quantity/count numerics keep the stepper."""
    if (sql_type or "").strip().lower() == "money":
        return True
    return bool(_NAME_MONEY_RE.search(_name_tokens(name)))


def _is_bool_name(name: str) -> bool:
    """True when a name reads as a boolean by convention, matched on whole word
    tokens (never a substring): a leading boolean verb followed by more tokens
    ("is active", "has access") or any boolean-adjective token ("is published",
    "featured"). Anchoring to tokens avoids the old raw-regex false positives
    ("candidateName", "cancelReason", "issueTitle")."""
    toks = _name_tokens(name).split()
    if not toks:
        return False
    if toks[0] in _BOOL_VERB_TOKENS and len(toks) > 1:
        return True
    return any(t in _BOOL_ADJ_TOKENS for t in toks)


# Curated, conservative value sets for a HANDFUL of well-known small-value-set fields
# whose vocabulary isn't otherwise recoverable (plain varchar, no registry enum_values,
# no workflow-status literals). Deliberately tiny — only fields with a safe, universal
# small set. Open-ended fields (nationality, country, type, notes, title, name, email,
# any `*Id`) are ABSENT on purpose, so they stay a plain Input; we never invent values
# for them. Keyed by the field name's LAST word token (see `curated_enum_options`).
_CURATED_ENUM_VALUES: dict[str, list[str]] = {
    "status": ["Active", "Inactive", "Pending", "Archived"],
    "priority": ["Low", "Medium", "High", "Urgent"],
    # `stage` is a LAST-RESORT fallback only: apply_semantic_field_types and
    # ensure_enum_selects prefer harvested workflow stages / declared enum_values and
    # only reach this generic pipeline when no real stage vocabulary exists.
    "stage": ["New", "In Progress", "In Review", "Completed"],
}


def curated_enum_options(name: str) -> list[str] | None:
    """Curated Select options for a well-known enum-ish field, or None to leave it as a
    plain Input. Matched on the field name's LAST word token so `status`/`currentStage`/
    `pipelineStage` hit but `statusReport`/`stageNotes` (last token report/notes) don't —
    the anchored `_name_tokens` split means a substring like "status" inside another word
    never fires. Never returns values for open-ended fields (they're not in the dict)."""
    toks = _name_tokens(name).split()
    if not toks:
        return None
    vals = _CURATED_ENUM_VALUES.get(toks[-1])
    return list(vals) if vals else None


def _decide(name: str, sql_type: str, options: list[str] | None):
    """Return (node_type, extra_props) for a field, or (None, None) to leave it.

    Order (FK-aware, type-first, anchored — protects LLM-built forms too):
      1. enum (declared options, or a curated fallback for well-known text fields) -> Select
      2. FK (`Id` suffix)                      -> None  (leave for the relational builder)
      3. real SQL type wins over the name      -> NumberInput/DatePicker/Switch/Textarea
      4. only when the type is unknown/varchar/char, fall to ANCHORED name regexes
      5. otherwise leave it (plain Input).
    """
    n = name or ""
    t = sql_type or ""

    # 0. First-class money: a plan-declared `type: "money"` (or `semantic_type: "money"`)
    #    is authoritative — banking demands a MoneyInput, not a naked NumberInput that
    #    silently drops the currency half. Must run BEFORE the enum/numeric/date/varchar
    #    branches so a money column typed as `numeric` in the registry still lands on
    #    MoneyInput (the plan wins). No sibling `_currency` column here — the schema
    #    builder already emits it; the form's MoneyInput carries the currency alongside
    #    the amount via its `currency` prop.
    if (sql_type or "").strip().lower() in ("money", "currency"):
        return "MoneyInput", {}

    # Curated fallback: only for TEXT-ish columns with no real options, so a numeric
    # `priority` (integer) stays a NumberInput and only a varchar/unknown one becomes a
    # Select. Real declared/harvested options (passed in `options`) always take priority.
    if not options and t in ("varchar", "char", ""):
        options = curated_enum_options(n)

    # 1. Declared (or curated) enum values → Select.
    if options and (_ENUM_RE.search(n) or t in ("varchar", "char", "") or len(options) <= 12):
        return "Select", {"options": [{"value": v, "label": v} for v in options]}

    # 2. Foreign key → relational picker; never retype it to a scalar control here.
    if _re_fk.search(n):
        return None, None

    # 3. Trust the real SQL column type over any name heuristic.
    if t in _NUMERIC_TYPES:
        if _is_money(n, t):
            # Currency: plain number, no +/- stepper (steppers read as "increment by
            # a unit", nonsensical for money). Keep a $ prefix + cents step.
            return "NumberInput", {"min": 0, "step": 0.01, "prefix": "$", "showSteppers": False}
        # Quantity/count and other numerics keep the stepper (unit increments).
        return "NumberInput", {"min": 0, "step": 1}
    if t in _DATE_TYPES:
        return "DatePicker", {}
    if t == "boolean":
        return "Switch", {}
    if t in _TEXT_TYPES:
        # Postgres `text` is often used for short strings too (name/email/
        # password/title/slug) — the type alone doesn't distinguish
        # single-line from long-form. Only promote to Textarea when the
        # NAME reads as long-form; short names get an explicit Input so
        # a previously-wrong Textarea gets rewritten (returning None
        # would signal "leave as-is" and the bad control would survive).
        if _NAME_TEXT_RE.search(_name_tokens(n)):
            return "Textarea", {}
        # `password` is text-typed but must be masked.
        if _is_password_name(n):
            return "Input", {"type": "password"}
        return "Input", {}

    # 4. Name fallback — ONLY when the SQL type is unknown/text-ish, and anchored to
    #    whole-word tokens so mid-word substrings ("stAGE", "candiDATE") can't fire.
    if t in ("varchar", "char", ""):
        toks = _name_tokens(n)
        if _NAME_MONEY_RE.search(toks):
            return "NumberInput", {"min": 0, "step": 0.01, "prefix": "$", "showSteppers": False}
        if _NAME_QTY_RE.search(toks):
            return "NumberInput", {"min": 0, "step": 1}
        if _NAME_DATE_RE.search(toks):
            return "DatePicker", {}
        if _is_bool_name(n):
            return "Switch", {}
        if _NAME_TEXT_RE.search(toks):
            return "Textarea", {}

    # 5. Leave as-is.
    return None, None


def apply_semantic_field_types(output_dir: str) -> dict:
    """Re-type form fields across src/schemas/*.json. Returns {retyped, files}.

    AUTHORITY (not guess-fix): for every form field this DERIVES the control from the
    registry column via `resolve_control` and applies it, overwriting whatever control
    the LLM emitted — the LLM's control choice is never consulted, so a wrong control
    can't survive. The LLM's LAYOUT is preserved (name/label/className/validators/
    placeholder). Relational FK Selects (props.optionsFrom, wired by the binding pass)
    are the one exception: their control + source are left untouched.
    """
    # Local import: field_controls imports helpers from THIS module, so importing it at
    # module scope would be circular. resolve_control is the single control authority.
    from services.field_controls import resolve_control
    # Spec D W2 — the plan reader is now the shared
    # ``plan_column_semantics`` helper so ``fk_semantics`` and every
    # downstream caller ask the same question in the same way and can't
    # drift on name-matching / precedence rules. ``load_plan`` is still
    # imported from ``plan_field_lookup`` (it owns file I/O + the mtime
    # cache) and the legacy ``get_field`` / ``get_semantic_type`` remain
    # available for the (few) inline reads below.
    from services.plan_field_lookup import (
        get_field,
        load_plan,
    )
    from services.plan_column_semantics import (
        get_enum_values as _plan_get_enum_values,
        get_semantic as _plan_get_semantic,
    )

    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"retyped": 0, "files": 0}

    # Plan is the semantic-type authority — its `semantic_type` beats whatever
    # `semanticType` the LLM emitted on the field prop. This kills the class
    # where a field name accidentally triggers a wrong heuristic (Bug 1: the
    # "Based At (Airport/City)" column got a DatePicker because "at" tripped
    # _NAME_DATE_RE, even though the plan clearly modelled it as a place).
    plan = load_plan(output_dir)
    reg_types = _registry_types(output_dir)
    seed_opts = harvest_seed_options(output_dir)
    reg_enums = _registry_enum_values(output_dir)
    status_idx = index_status_workflows(output_dir)
    # Literal statuses assigned/compared in the workflows — a global {norm_col ->
    # [values]} map (workflow columns aren't reliably tied to one entity).
    wf_statuses = {_norm(c): v for c, v in harvest_workflow_statuses(output_dir).items()}
    known = (set(reg_types) | set(seed_opts) | set(reg_enums)
             | {_ent_key(k) for k in status_idx})

    retyped = 0
    touched_files = 0
    # Recursive — nested create/edit forms (foo/new.json) need typing too.
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
        base = os.path.basename(fp)
        if base in ("shell.json", "nav-flow.json") or base.startswith(("login", "signup", "register")):
            continue
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue

        # Prefer the Form's Create/Update<Entity> workflow (unambiguous) — critical
        # for synthesized nested forms (bookings/new) whose path segment doesn't
        # match the real entity ('bookings' vs 'ClassBooking').
        ent = _entity_from_form_workflow(schema, known) or _entity_key_for_file(fp, known)
        cols = reg_types.get(ent or "", {})
        # Merge every deterministic enum source into one {norm_col -> [values]} map
        # (own list copies so we never mutate a cached source). Union, first-seen order.
        opts: dict[str, list[str]] = {}

        def _union(col: str, values: list[str]) -> None:
            lst = opts.setdefault(col, [])
            for v in values:
                if v not in lst:
                    lst.append(v)

        for _c, _v in seed_opts.get(ent or "", {}).items():
            _union(_c, list(_v))
        for _c, _v in reg_enums.get(ent or "", {}).items():
            _union(_c, list(_v))
        # Status options: the entity's status workflow index.
        st = status_idx.get(ent or "")
        if st and st.get("statuses"):
            _union("status", list(st["statuses"]))
        # Literal statuses harvested from the generated workflows (global map).
        for _c, _v in wf_statuses.items():
            _union(_c, list(_v))

        file_changed = False
        for node in _iter_nodes(schema):
            if node.get("type") not in _FIELD_TYPES:
                continue
            p = node.get("props")
            if not isinstance(p, dict) or not p.get("name"):
                continue
            if p.get("optionsFrom"):
                continue  # relational FK dropdown — control stays Select, source owned by the binding pass
            nkey = _norm(p["name"])
            sql_type = cols.get(nkey, "")
            # Vocabulary for a potential enum Select: our harvested options (seed/registry/
            # workflow union) FIRST, then — only when we harvested none — an existing Select's
            # OWN authored options, so a legit enum whose vocabulary we can't otherwise source
            # stays a Select. An OPTION-LESS Select gets no vocabulary and is demoted to its
            # real control (the g2ter02v empty-Select-on-firstName bug).
            harvested = opts.get(nkey)
            node_opts = None
            if node.get("type") in ("Select", "Combobox") and isinstance(p.get("options"), list):
                node_opts = [o.get("value") for o in p["options"]
                             if isinstance(o, dict) and o.get("value") not in (None, "")] or None
            options = harvested or node_opts

            # Plan-declared semantic_type beats the LLM's authored semanticType
            # (the plan is the source of truth for what a field's SHAPE is; the
            # LLM's per-field prop is the fallback for legacy plans that don't
            # carry semantic_type). Entity name comes from _entity_from_form_workflow
            # or the file's path convention.
            ent_name = None
            if ent:
                # Find the pretty entity name whose _ent_key matches `ent`.
                ent_name = next((n for n in known if _ent_key(n) == ent), None) if not isinstance(ent, str) else ent
            # Plan-first semantic hint via the shared helper. `get_semantic`
            # returns the Spec D W2 blob's `control` (if a recognisable string
            # is set), otherwise the legacy per-field `semantic_type`. Callers
            # still fall back to the LLM's authored `semanticType` when the
            # plan is silent — that path is unchanged.
            plan_sem = _plan_get_semantic(plan, ent_name, p["name"]) if ent_name else None
            eff_sem = plan_sem or p.get("semanticType")

            # Spec D W2 — planner-authored `field.semantic` blob takes
            # precedence over resolve_control. The blob shape is
            # ``{control?, enum_values?, format?}``. When ``control`` names
            # a valid _FIELD_TYPES entry we use it verbatim; ``enum_values``
            # (via the shared helper — reads the blob then falls back to
            # ``fields[].enum_values``) unions into the options for
            # Select/Combobox; ``format`` passes through as a prop for
            # downstream renderers. Missing / malformed blobs fall through
            # to the resolve_control classifier below.
            plan_field = (
                get_field(plan, ent_name, p["name"]) if ent_name else None
            )
            sem_blob = None
            if isinstance(plan_field, dict):
                sb = plan_field.get("semantic")
                if isinstance(sb, dict):
                    sem_blob = sb
            planner_control: str | None = None
            planner_props: dict[str, Any] = {}
            # Plan-authored enum vocabulary (blob-first, top-level fallback).
            plan_enum = _plan_get_enum_values(plan, ent_name, p["name"]) if ent_name else None
            if plan_enum:
                merged = list(options or [])
                for v in plan_enum:
                    if v and v not in merged:
                        merged.append(v)
                options = merged
            if sem_blob:
                sc = sem_blob.get("control")
                if isinstance(sc, str) and sc in _FIELD_TYPES:
                    planner_control = sc
                sf = sem_blob.get("format")
                if isinstance(sf, str) and sf:
                    planner_props["format"] = sf

            if planner_control is not None:
                control = planner_control
                cprops = dict(planner_props)
                # For Select/Combobox, materialize options if we have any.
                if control in ("Select", "Combobox") and options:
                    cprops.setdefault(
                        "options",
                        [{"value": v, "label": v} for v in options],
                    )
            else:
                # THE AUTHORITY: derive the control from the column; the LLM's control is ignored.
                control, cprops = resolve_control(
                    name=p["name"],
                    sql_type=str(sql_type or ""),
                    options=options,
                    semantic_type=eff_sem,
                )
                if planner_props:
                    cprops = {**(cprops or {}), **planner_props}

            if control == node.get("type"):
                # Control already correct — don't clobber the LLM's other props; only
                # backfill harvested Select options when they're missing (enum Select still
                # gets its vocabulary). Preserves the prior option-backfill behavior.
                if node.get("type") == "Select" and harvested and not p.get("options"):
                    p["options"] = [{"value": v, "label": v} for v in harvested]
                    retyped += 1
                    file_changed = True
                continue

            # Control changed → apply it, preserving the LLM's layout (label/className/
            # validators/placeholder) and applying the derived control's props verbatim.
            new_props: dict[str, Any] = {"name": p["name"], "label": p.get("label") or _label(p["name"])}
            if p.get("className"):
                new_props["className"] = p["className"]
            if p.get("validators"):
                new_props["validators"] = p["validators"]
            if p.get("placeholder"):
                new_props["placeholder"] = p["placeholder"]
            new_props.update(cprops or {})
            node["type"] = control
            node["props"] = new_props
            retyped += 1
            file_changed = True

        if file_changed:
            touched_files += 1
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)

    return {"retyped": retyped, "files": touched_files}
