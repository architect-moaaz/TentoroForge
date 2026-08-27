"""Heal button-/manual-triggered workflow mutations into EXECUTABLE literals.

DEFECT this cures: dashboard buttons like "Confirm Pickup" / "Process Return" /
"Cancel" appear to do nothing. Their workflow `db_update` (or `db_insert`) node
carries *self-referential* values, e.g.:

    {"id":"set_picked_up", "data":{"label":"Set Picked Up",
        "config":{"actionType":"db_update", "table":"rentals",
                  "where":{"id":"{{id}}"},
                  "values":{"status":"{{status}}", "pickedUpAt":"{{pickedUpAt}}"}}}}

The button dispatch supplies only `{id}`; there is no trigger input for `status`
or `pickedUpAt`, so at runtime `{{status}}` → "" → NULL and the UPDATE *wipes* the
column instead of setting the intended state. The intended literal ("Picked Up")
lives in the node's `label` ("Set Picked Up") but is never used as the value.

This pass rewrites those unresolvable values into real literals, deterministically:
  * a STATUS-like column  → the literal derived from the node label
    ("Set Picked Up" → "Picked Up", "Mark as Cancelled" → "Cancelled").
  * a lifecycle TIMESTAMP column (`*At`, or a date/time-named column) →
    `"CURRENT_TIMESTAMP"`. The runtime (`templates/runtime/workflows/index.ts`)
    resolves that token to `new Date()` in `_resolveRef`, and `_resolveValueMap`
    explicitly whitelists it so it is NOT dropped as an unresolved var.
  * anything else (a genuinely user-supplied field) is LEFT as `{{var}}` and
    flagged — it is meant to come from a form/input, not be invented here.

Pure + deterministic + idempotent + never raises. Sibling of the workflow guards
in post_generate_fixes; also reused by workflow_executability (the gate) and by
workflow_step_translator (the source emitter) so author / heal / validate share
one set of rules and cannot drift.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Runtime-recognised "now" literal. `_resolveRef` maps CURRENT_TIMESTAMP → new Date();
# `_resolveValueMap` whitelists it so it survives the unresolved-var drop. See
# backend/templates/runtime/workflows/index.ts.
NOW_LITERAL = "CURRENT_TIMESTAMP"

# Special tokens / literals the runtime resolves without a process variable.
_SPECIAL_TOKENS = {"CURRENT_TIMESTAMP", "NOW()", "true", "false"}

# A value that is exactly / contains a `{{ var }}` template.
_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

# Verb prefixes stripped from a node label to recover the intended status literal.
# Ordered longest-first so "Mark as " wins over "Mark ".
_LABEL_VERB_PREFIXES = (
    "change to ", "mark as ", "set to ", "set ", "mark ", "update ", "change ",
    "move to ", "transition to ",
    # CRUD verbs. Without these, "Edit Candidate" stripped nothing and the
    # WHOLE label was written into the status column as if it were a state
    # (register T3-11). Stripping them leaves the record name, which
    # `_names_the_record` then rejects — so these labels correctly yield no
    # literal at all rather than a wrong one.
    "edit ", "save ", "create ", "add ", "new ", "delete ", "remove ",
    "view ", "open ", "submit ",
)

# Status-column name signals (case-insensitive substring match).
_STATUS_TOKENS = ("status", "state", "stage")
# A derived literal equal to one of these bare words is not a real state value.
_STATUS_STOPWORDS = {"status", "state", "stage", "the status", "status to"}

# Timestamp-column name signals (for columns NOT ending in the camelCase `At`).
# Short, common words ("date"/"time") are matched only as whole camelCase/snake
# WORD SEGMENTS — matching them as bare substrings misfires on unrelated columns
# ("date" ⊂ "candidateId", "time" ⊂ "runtimeId"), which wrongly rewrites a uuid FK
# to CURRENT_TIMESTAMP.
_TIMESTAMP_WORD_TOKENS = ("date", "time", "timestamp", "when")
# Distinctive lifecycle verbs are safe to match as substrings (they don't hide in
# unrelated column names).
_TIMESTAMP_SUBSTR_TOKENS = (
    "pickedup", "returned", "completed", "shipped", "delivered", "approved",
    "rejected", "cancelled", "canceled", "resolved", "closed", "confirmed",
    "started", "finished", "processed", "fulfilled", "expired",
)


# ---------------------------------------------------------------------------
# Shared, pure classification helpers (imported by executability + translator)
# ---------------------------------------------------------------------------
def is_status_col(col: str) -> bool:
    c = str(col or "").lower()
    return any(tok in c for tok in _STATUS_TOKENS)


def _word_segments(raw: str) -> set[str]:
    """Lowercase word segments of a column name, splitting camelCase + snake_case
    (`completedDate` → {completed, date}, `candidateId` → {candidate, id})."""
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw).lower()
    return {seg for seg in re.split(r"[^a-z0-9]+", snake) if seg}


def is_timestamp_col(col: str) -> bool:
    """True for a lifecycle timestamp column: a camelCase `*At` name (pickedUpAt,
    returnedAt, completedAt) or a date/time-named column. Short signals match only
    on a word boundary so `candidateId`/`updateId` are NOT misread as timestamps."""
    raw = str(col or "")
    if not raw:
        return False
    # camelCase `...At` (but not a word merely ending in 'at' like "format")
    if re.search(r"[a-z0-9]At$", raw) or raw.lower().endswith("_at"):
        return True
    if _word_segments(raw) & set(_TIMESTAMP_WORD_TOKENS):
        return True
    c = raw.lower()
    return any(tok in c for tok in _TIMESTAMP_SUBSTR_TOKENS)


def derive_status_literal(label: str, entity: str | None = None) -> str | None:
    """Recover the intended status literal from a node label.

    "Set Picked Up" → "Picked Up"; "Mark as Cancelled" → "Cancelled";
    "Mark Returned" → "Returned". Returns None when nothing meaningful is left
    (e.g. a bare "Update Status" → "Status" is not a real state value).

    ``entity`` — the table/entity being written. Supply it wherever it is known:
    it lets the guard reject a label that merely names the record ("Update
    Order" → "Order"), which would otherwise be written into the status column
    as if it were a state."""
    text = str(label or "").strip()
    if not text:
        return None
    # A transition phrase names the target state after " to " / " as "
    # ("Mark applicant as Hired" → "Hired", "Set status to Approved" → "Approved").
    # Take the tail after the LAST such connector.
    conn = re.search(r"(?i)\s(?:to|as)\s(?!.*\s(?:to|as)\s)(.+)$", text)
    if conn:
        tail = conn.group(1).strip()
        return tail if tail and tail.lower() not in _STATUS_STOPWORDS else None
    # No connector: strip a leading verb ("Set Picked Up" → "Picked Up").
    low = text.lower()
    for pref in _LABEL_VERB_PREFIXES:
        if low.startswith(pref):
            text = text[len(pref):].strip()
            break
    if not text or text.lower() in _STATUS_STOPWORDS:
        return None
    # A label that just names the RECORD is not a state (register T3-11).
    #
    # "Update Order" strips its verb to "Order", which is the entity, not a
    # status — and it was written straight into the status column, so the row's
    # state became the word "Order". Same for "Edit Candidate", "Save Booking".
    # A status literal has to look like a STATE; when all that is left is the
    # thing being acted on, we know nothing and must not invent.
    if entity and _names_the_record(text, entity):
        return None
    return text


def _names_the_record(text: str, entity: str) -> bool:
    """Is `text` just the entity/table name (in any spelling)?"""
    from services.entity_names import EntityNameError, entity_key
    try:
        return entity_key(text) == entity_key(entity)
    except EntityNameError:
        return False


def is_literal_value(ref: Any) -> bool:
    """True when `ref` is a CONCRETE authored literal — a value that resolves at
    runtime WITHOUT any process variable: a number/bool, a special token
    (CURRENT_TIMESTAMP/NOW()/true/false), or a non-empty plain string carrying no
    `{{var}}` template. An empty string or an embedded/self-referential template is
    NOT concrete."""
    if isinstance(ref, bool) or isinstance(ref, (int, float)):
        return True
    if not isinstance(ref, str):
        return False
    if ref in _SPECIAL_TOKENS:
        return True
    if not ref.strip():
        return False
    return not _TEMPLATE_RE.search(ref)


def has_explicit_literal(values: Any) -> bool:
    """True when a db_update/db_insert `values` map carries at least one concrete
    authored literal (A2 — the planner's judgment about the target state, e.g.
    `{"status":"Approved"}`). Such a map is written VERBATIM by the author path
    (highest priority, ahead of label-derivation and self-refs) and the healing pass
    finds nothing to heal in it — the guard becomes a pure safety net."""
    if not isinstance(values, dict) or not values:
        return False
    return any(is_literal_value(v) for v in values.values())


def template_vars(ref: Any) -> list[str]:
    """All `{{var}}` root names inside a value (the part before any dot)."""
    if not isinstance(ref, str):
        return []
    return [m.split(".")[0] for m in _TEMPLATE_RE.findall(ref)]


def value_resolves(ref: Any, provided: set[str]) -> bool:
    """True when `ref` will resolve to a real value at runtime: a literal, a
    special token (CURRENT_TIMESTAMP/NOW()/true/false), or a `{{var}}` whose root
    var is provided (trigger input, upstream node output, or `id`)."""
    if not isinstance(ref, str):
        return True  # a raw number/bool/None literal resolves as-is
    if ref in _SPECIAL_TOKENS:
        return True
    vars_ = template_vars(ref)
    if not vars_:
        return True  # plain literal string, no template
    return all(v in provided for v in vars_)


# ---------------------------------------------------------------------------
# Provided-variable collection (what the trigger + upstream nodes make available)
# ---------------------------------------------------------------------------
_OUTPUT_VAR_KEYS = ("variableName", "outputVar", "assignTo", "resultVar", "outputVariable")


def _trigger_input_names(wf: dict) -> set[str]:
    out: set[str] = set()
    # top-level declared process variables (the deterministic trigger-input contract)
    for pv in _as_list(wf.get("processVariables")):
        if isinstance(pv, dict) and pv.get("name"):
            out.add(str(pv["name"]))
        elif isinstance(pv, str):
            out.add(pv)
    definition = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    for pv in _as_list(definition.get("processVariables")):
        if isinstance(pv, dict) and pv.get("name"):
            out.add(str(pv["name"]))
        elif isinstance(pv, str):
            out.add(pv)
    # explicit trigger inputMapping / inputs on the trigger node
    for node in _iter_nodes(wf):
        cfg = _node_config(node)
        if str(node.get("type") or cfg.get("nodeType") or "").lower() != "trigger":
            continue
        for key in ("inputMapping", "inputs", "inputSchema"):
            im = cfg.get(key)
            if isinstance(im, dict):
                out.update(str(k) for k in im.keys())
            elif isinstance(im, list):
                for it in im:
                    if isinstance(it, dict) and it.get("name"):
                        out.add(str(it["name"]))
                    elif isinstance(it, str):
                        out.add(it)
    return out


def collect_provided_vars(wf: dict) -> set[str]:
    """Every variable a mutation may legitimately reference: trigger inputs +
    upstream node output vars + the always-present `id` (button dispatch supplies
    the target row's id)."""
    provided: set[str] = {"id"}
    provided |= _trigger_input_names(wf)
    for node in _iter_nodes(wf):
        cfg = _node_config(node)
        for k in _OUTPUT_VAR_KEYS:
            if cfg.get(k):
                provided.add(str(cfg[k]))
        # a set_variable node also exposes `name`
        if str(cfg.get("actionType") or "").strip() == "set_variable" and cfg.get("name"):
            provided.add(str(cfg["name"]))
    return provided


# ---------------------------------------------------------------------------
# Node/config traversal helpers (tolerant of the two shapes: nodes[] and steps[])
# ---------------------------------------------------------------------------
def _as_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _iter_nodes(wf: dict) -> list[dict]:
    definition = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    out: list[dict] = []
    for n in _as_list(definition.get("nodes")):
        if isinstance(n, dict):
            out.append(n)
    for s in _as_list(definition.get("steps")):
        if isinstance(s, dict):
            out.append(s)
    return out


def _node_config(node: dict) -> dict:
    """Return the config dict for either a runtime node ({data:{config}}) or a raw
    planner step ({config})."""
    data = node.get("data")
    if isinstance(data, dict) and isinstance(data.get("config"), dict):
        return data["config"]
    if isinstance(node.get("config"), dict):
        return node["config"]
    return {}


def _node_label(node: dict) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cfg = _node_config(node)
    for src in (data, cfg, node):
        for key in ("label", "title", "name"):
            v = src.get(key) if isinstance(src, dict) else None
            if isinstance(v, str) and v.strip():
                return v
    return ""


# ---------------------------------------------------------------------------
# Core: is a mutation node's SET clause resolvable? (used by the gate)
# ---------------------------------------------------------------------------
def _definitely_null(col: str, ref: Any, provided: set[str]) -> bool:
    """True when this value WILL resolve to NULL at runtime with certainty.

    A backed/literal/token value never does. A plain unbacked `{{field}}` is NOT
    counted — a create form's dispatch populates ctx.variables from its payload
    without declaring processVariables, so we cannot statically prove it null. Only
    a SELF-referential `{{col}}` on a STATUS or TIMESTAMP column is a certain NULL:
    those machine-state columns are never submitted by a user, so an unbacked
    self-ref is the "Confirm Pickup wipes the column" fingerprint."""
    if value_resolves(ref, provided):
        return False
    m = re.fullmatch(r"\s*\{\{\s*([\w.]+)\s*\}\}\s*", ref) if isinstance(ref, str) else None
    if not m:
        return False
    var = m.group(1).split(".")[0]
    if var in provided:
        return False
    return var == col and (is_status_col(col) or is_timestamp_col(col))


def mutation_all_null(config: dict, provided: set[str]) -> bool:
    """True when this is a db_update/db_insert whose `values` map is present but
    resolves to ALL NULL — every entry is a certain-NULL self-referential state/time
    `{{col}}`. Such a SET clause is a no-op (or destructive UPDATE) → non-executable.
    Conservative: a single resolvable or form-suppliable value keeps it executable so
    legitimate create inserts are never false-flagged."""
    at = str(config.get("actionType") or "").strip()
    if at not in ("db_update", "db_insert"):
        return False
    values = config.get("values")
    if not isinstance(values, dict) or not values:
        return False  # absence is handled by the _REQUIRED presence check
    return all(_definitely_null(col, ref, provided) for col, ref in values.items())


# ---------------------------------------------------------------------------
# Core healing of one mutation config in place
# ---------------------------------------------------------------------------
def _heal_config(config: dict, label: str, provided: set[str]) -> tuple[int, list[str]]:
    """Heal a single db_update/db_insert config's `values` in place.

    Returns (healed_count, unresolved_cols)."""
    at = str(config.get("actionType") or "").strip()
    if at not in ("db_update", "db_insert"):
        return 0, []
    values = config.get("values")
    if not isinstance(values, dict) or not values:
        return 0, []

    healed = 0
    unresolved: list[str] = []
    for col, ref in list(values.items()):
        # Only act on a PURE single-template self-referential/unresolvable value.
        if not isinstance(ref, str):
            continue
        m = re.fullmatch(r"\s*\{\{\s*([\w.]+)\s*\}\}\s*", ref)
        if not m:
            continue  # literal or embedded-text template — leave it
        var = m.group(1).split(".")[0]
        if var in provided:
            continue  # a real trigger input / upstream output / id — leave it

        if is_status_col(col):
            lit = derive_status_literal(label)
            if lit:
                values[col] = lit
                healed += 1
            else:
                unresolved.append(col)
        elif is_timestamp_col(col):
            values[col] = NOW_LITERAL
            healed += 1
        else:
            # a genuinely user-supplied field — leave the {{var}}, flag for an input
            unresolved.append(col)
    return healed, unresolved


def heal_workflow_dict(wf: dict) -> tuple[int, list[str]]:
    """Heal every mutation node in a single workflow dict in place. Returns
    (values_healed, unresolved_cols). Pure/idempotent — a second pass finds only
    literals and real vars, so it heals nothing further."""
    if not isinstance(wf, dict):
        return 0, []
    provided = collect_provided_vars(wf)
    total_healed = 0
    unresolved: list[str] = []
    for node in _iter_nodes(wf):
        cfg = _node_config(node)
        at = str(cfg.get("actionType") or "").strip()
        if at not in ("db_update", "db_insert"):
            continue
        healed, unres = _heal_config(cfg, _node_label(node), provided)
        total_healed += healed
        unresolved.extend(unres)
    return total_healed, unresolved


def heal_workflow_mutations(output_dir: str | Path) -> dict:
    """Scan output/<slug>/workflows/*.json and make button/manual-triggered
    mutations executable: replace self-referential/unresolvable `values` with real
    literals (status from label, lifecycle *At = CURRENT_TIMESTAMP). Deterministic,
    idempotent, never raises.

    Returns {workflows_scanned, values_healed, unresolved}."""
    wf_dir = Path(output_dir) / "workflows"
    report = {"workflows_scanned": 0, "values_healed": 0, "unresolved": 0}
    if not wf_dir.is_dir():
        return report
    for f in sorted(wf_dir.glob("*.json")):
        report["workflows_scanned"] += 1
        try:
            original = f.read_text()
            wf = json.loads(original)
        except Exception:  # noqa: BLE001 — a malformed file is another guard's job
            continue
        try:
            healed, unresolved = heal_workflow_dict(wf)
        except Exception as exc:  # noqa: BLE001 — never let one workflow abort the pass
            logger.warning("[workflow_mutation_guard] heal failed for %s: %s", f.name, exc)
            continue
        report["values_healed"] += healed
        report["unresolved"] += len(unresolved)
        if healed:
            new_text = json.dumps(wf, indent=2)
            if new_text != original:
                try:
                    f.write_text(new_text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[workflow_mutation_guard] write failed for %s: %s", f.name, exc)
    return report
