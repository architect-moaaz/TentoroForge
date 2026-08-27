"""Map an entity's status-transition action buttons to the REAL domain workflow.

The page agent invents row/page action refs like `confirmAppointment` /
`cancelAppointment` — but the business-logic agent produced ONE consolidated
`AppointmentStatusWorkflow` that performs a `db_update` on `appointments.status`
(triggered with `{appointmentId, targetStatus}`). Nothing in the pipeline bridged
the two, so those buttons dispatched a dead workflow.

This module builds, from the generated `workflows/*.json`, an index of "which
workflow transitions each entity's status, and how to call it", so the binding
pass can rewrite a status action (`Confirm`/`Cancel`/...) to the real workflow
with the right `{idVar: {{item.id}}, statusVar: <value>}` args instead of
stripping it. Deterministic + best-effort: unknown → return None (caller strips).
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from typing import Any

from services.entity_names import EntityNameError, entity_key

logger = logging.getLogger(__name__)

# Action-label verb → the status value it drives a record TO. Only used as a
# fallback when the workflow's own known status set has no matching value.
_STATUS_VERBS: dict[str, str] = {
    "confirm": "confirmed",
    "cancel": "cancelled",
    "approve": "approved",
    "reject": "rejected",
    "decline": "declined",
    "complete": "completed",
    "finish": "completed",
    "resolve": "resolved",
    "close": "closed",
    "activate": "active",
    "deactivate": "inactive",
    "publish": "published",
    "archive": "archived",
    "submit": "submitted",
    "pay": "paid",
    "ship": "shipped",
    "deliver": "delivered",
    "start": "in_progress",
}

# Verbs longest-first, so a verb that CONTAINS another wins over it.
# "deactivate" must be tested before "activate", or `"activate" in "deactivate"`
# drives the record to the opposite state (register STATUS-2).
_VERBS_BY_SPECIFICITY: tuple[str, ...] = tuple(
    sorted(_STATUS_VERBS, key=len, reverse=True)
)

# Prefixes that INVERT a verb. "unpublish" is not "publish"; "disapprove" is
# not "approve". Only consulted when the negated form is not itself a declared
# verb — "deactivate" IS declared, so it resolves directly and never gets here.
_NEGATING_PREFIXES: tuple[str, ...] = ("un", "de", "dis", "non")


def _is_negated(key: str, verb: str) -> bool:
    """Is `verb` immediately preceded by a negating prefix inside `key`?"""
    at = key.find(verb)
    while at != -1:
        head = key[:at]
        if any(head.endswith(p) for p in _NEGATING_PREFIXES):
            return True
        at = key.find(verb, at + 1)
    return False


def _ent_key(s: Any) -> str:
    """Normalize an entity name / table name to a singular comparison key so
    `Appointment`, `appointments`, and `appointment` all collapse to the same
    thing.

    Delegates to :func:`services.entity_names.entity_key` — the single
    naming authority. The local version dropped one trailing `s`, which
    is wrong for every irregular plural: `categories` → `categorie` never
    matched `Category` → `category`, so the entity↔table join failed and
    the status workflow for that entity became unreachable (register
    findings STATUS-3 and BA-5). It also silently returned `''` for
    unusable input, and an empty key matches the wrong bucket rather
    than none — that path now raises."""
    return entity_key(s)


def _iter_strings(obj: Any):
    """Yield every string leaf in a nested dict/list (so condition expressions can
    be regex-scanned with their real, unescaped quotes)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def index_status_workflows(output_dir: str | os.PathLike) -> dict[str, dict]:
    """Scan `workflows/*.json` for every workflow that updates a table's `status`
    column, returning `{entity_key: {name, table, id_var, status_var, statuses}}`.

    A status workflow is identified by an action node with
    `config.actionType == "db_update"` whose `config.values` sets `status`. The
    node reveals how to invoke it: `where.id` names the entity-id variable and
    `values.status` names the target-status variable. Allowed status values are
    harvested from any `<status_var> == "X"` comparisons in the definition.
    """
    out: dict[str, dict] = {}
    wdir = os.path.join(str(output_dir), "workflows")
    if not os.path.isdir(wdir):
        return out

    for fp in sorted(glob.glob(os.path.join(wdir, "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001 — skip unreadable/invalid files
            continue
        defn = d.get("definition") or {}
        nodes = defn.get("nodes") or []
        name = d.get("name") or d.get("id")
        if not name:
            continue
        # Names of the workflow's declared inputs — used to tell a parameterized
        # status update (values.status references a var like `targetStatus`) apart
        # from a fixed one (values.status is a literal like "issued"). Only the
        # parameterized kind is a general status-transition workflow we can drive.
        pvars = {
            str(v.get("name"))
            for v in (d.get("processVariables") or [])
            if isinstance(v, dict) and v.get("name")
        }
        for n in nodes:
            if not isinstance(n, dict):
                continue
            cfg = ((n.get("data") or {}).get("config")) or n.get("config") or {}
            if not isinstance(cfg, dict) or cfg.get("actionType") != "db_update":
                continue
            values = cfg.get("values") or {}
            if not isinstance(values, dict) or "status" not in values:
                continue
            table = cfg.get("table")
            if not table:
                continue
            status_var = str(values.get("status") or "status")
            # Skip fixed-literal status setters (single-purpose CRUD-ish updates):
            # they don't take a target-status arg, so there's nothing to map a
            # multi-way Confirm/Cancel action onto.
            if status_var not in pvars:
                continue
            where = cfg.get("where") if isinstance(cfg.get("where"), dict) else {}
            # The REAL key column, not an assumed "id".
            #
            # This read only `where["id"]` and fell back to "id" for anything
            # else, so a table keyed on `candidate_id` / `uuid` / `code` got an
            # argument name the workflow does not accept and the update matched
            # no row. Batch 3 (CRUD-4) made non-`id` keys ordinary output, so
            # this is now reachable in normal generation.
            id_var = _where_key(where, str(name))

            # Harvest the statuses this workflow is known to deal in.
            #
            # Previously ONLY `<status_var> == "X"` condition expressions were
            # scanned. A normal status workflow contains no such condition — it
            # just does `db_update values.status = {{targetStatus}}` — so the
            # set came back EMPTY on the ordinary path, `derive_target_status`
            # had no constraint to honour, and it fell through to the verb
            # table. That is the "never invent an invalid status" guard being
            # inert exactly when it is needed (register STATUS-1).
            #
            # Any status LITERAL the workflow itself writes is evidence too, so
            # both sources are harvested.
            blob = "\n".join(_iter_strings(defn))
            statuses = set(re.findall(_status_literal_re(status_var), blob))
            statuses |= _literal_status_values(nodes, table)
            statuses.discard(status_var)

            entry = {
                "name": name,
                "table": table,
                "id_var": id_var,
                "status_var": status_var,
                "statuses": sorted(statuses),
            }
            key = _ent_key(table)
            existing = out.get(key)
            if existing is None:
                entry["alternates"] = []
                out[key] = entry
            else:
                # Keep EVERY status workflow for a table reachable.
                #
                # `setdefault` + `break` kept only the first, so a second flow
                # for the same table (an approval alongside a fulfilment, say)
                # could never be dispatched whatever label the button carried.
                # The primary entry keeps its exact shape — every existing
                # consumer reads `status_idx[key]` as a dict — and the rest
                # hang off it for `map_status_action` to choose between.
                existing.setdefault("alternates", []).append(entry)
            break  # first status-updating node per workflow is enough
    return out


def _where_key(where: dict, workflow_name: str) -> str:
    """The PROCESS VARIABLE a status workflow filters by.

    `where` is `{column: variable}` — e.g. `{"id": "appointmentId"}` means
    "match the `id` column against the `appointmentId` input". The argument the
    caller must supply is therefore the VALUE, not the key.

    This used to read `where["id"]` specifically and fall back to the literal
    `"id"` for anything else. A table keyed on `candidate_id` / `uuid` / `code`
    therefore got the argument name `"id"`, which the workflow does not declare
    — so the value never bound, the WHERE matched no row, and the button did
    nothing (register STATUS-5). Batch 3 (CRUD-4) made non-`id` key columns
    ordinary output, which made this reachable in normal generation.
    """
    entries = [(k, v) for k, v in (where or {}).items() if k and v]
    if not entries:
        return "id"
    if len(entries) > 1:
        # Prefer the id-ish column, but say which one was chosen.
        preferred = next(
            (v for k, v in entries if str(k).lower() in ("id", "uuid")),
            entries[0][1],
        )
        logger.warning(
            "workflow_action_mapper: %s filters on %d columns %s; using the "
            "variable %r as the id argument.",
            workflow_name, len(entries), sorted(str(k) for k, _ in entries), preferred,
        )
        return str(preferred)
    return str(entries[0][1])


def _status_literal_re(status_var: str) -> str:
    """``<status_var> == "X"``, anchored so a SIBLING variable is not harvested.

    Unanchored, a ``status_var`` of ``status`` also matched
    ``old_status == "Bogus"`` and adopted another variable's values as this
    one's legal set — silently constraining or widening what the buttons could
    drive the record to."""
    return r'(?<![A-Za-z0-9_])' + re.escape(status_var) + r'\s*==\s*"([^"]+)"'


def _literal_status_values(nodes: list, table: Any) -> set[str]:
    """Every literal written to a ``status`` column by this workflow's own
    db_update/db_insert nodes on the same table."""
    out: set[str] = set()
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        cfg = ((n.get("data") or {}).get("config")) or n.get("config") or {}
        if not isinstance(cfg, dict):
            continue
        if cfg.get("actionType") not in ("db_update", "db_insert"):
            continue
        if cfg.get("table") and _ent_key(cfg.get("table")) != _ent_key(table):
            continue
        values = cfg.get("values")
        if not isinstance(values, dict):
            continue
        v = values.get("status")
        if not isinstance(v, str):
            continue
        v = v.strip()
        # A template or bare variable reference is not a literal value.
        if not v or "{{" in v or not re.search(r"[A-Za-z]", v):
            continue
        out.add(v)
    return out


def derive_target_status(label: str, statuses: list[str] | set[str]) -> str | None:
    """From an action label ("Confirm", "Cancel"), pick the status value it drives
    to. Prefers a value in the workflow's own known `statuses` set (so we never
    invent a value the DB/enum would reject); falls back to a canonical verb map
    only when the workflow declared no status literals. Returns None if unmappable."""
    key = re.sub(r"[^a-z]", "", (label or "").lower())
    if not key:
        return None
    known = list(statuses or [])

    def _match_verb(stem: str) -> str | None:
        # Prefer a known status starting with the verb stem: confirm → confirmed.
        for s in known:
            if re.sub(r"[^a-z]", "", s.lower()).startswith(stem):
                return s
        return None

    # 1) The label itself equals a known status (e.g. label "Completed").
    for s in known:
        if re.sub(r"[^a-z]", "", s.lower()) == key:
            return s

    # 2) A verb in the label maps to a status.
    #
    # Verbs are tried LONGEST FIRST, not in declaration order.
    #
    # The scan was `if verb in key` over the dict in insertion order, and
    # `"activate"` is both declared before `"deactivate"` AND a substring of it.
    # So the label "Deactivate" matched the verb "activate" and drove the record
    # to `active` — the exact opposite of what the button says. Any verb that
    # is a substring of another had the same hazard ("pay"/"repay",
    # "close"/"disclose", "submit"/"resubmit"); ordering by length makes the
    # most specific verb win, which is the only reading that can be right.
    for verb in _VERBS_BY_SPECIFICITY:
        if verb not in key:
            continue
        # A NEGATING PREFIX inverts the verb, so a match is not evidence.
        #
        # Longest-first ordering fixes verb-vs-verb collisions ("deactivate"
        # beats "activate") because both are declared. It cannot help when the
        # negated form is NOT declared: "Unpublish" still contains "publish"
        # and drove the record to `published` — the opposite of the button.
        # We cannot know the intended target (is it "draft"? "unpublished"?
        # "archived"?), and guessing the inverse is how a status write becomes
        # destructive. Refuse, and let the caller fall back to a real binding.
        if _is_negated(key, verb):
            logger.warning(
                "workflow_action_mapper: label %r negates the verb %r and no "
                "%r status is declared — refusing to infer a target status "
                "rather than driving the record to its opposite.",
                label, verb, f"un/de/dis-{verb}",
            )
            return None
        val = _STATUS_VERBS[verb]
        m = _match_verb(verb)
        if m:
            return m
        if not known:
            # No known status set to honour. See index_status_workflows: the
            # set is now harvested from the workflow's own status literals as
            # well as its conditions, so an empty set here really does mean
            # "this workflow declares nothing" rather than "we did not look".
            return val
        # Known set exists but nothing matched the verb → also try the
        # canonical value directly against the known set.
        for s in known:
            if re.sub(r"[^a-z]", "", s.lower()) == re.sub(r"[^a-z]", "", val):
                return s
        return None
    return None


def map_status_action(
    label: str,
    entity: Any,
    index: dict[str, dict],
    id_expr: str = "{{item.id}}",
) -> dict | None:
    """Resolve a status-transition action to a real workflow call.

    Returns ``{"workflow": name, "args": {id_var: id_expr, status_var: value}}``
    or None when there's no status workflow for the entity or the label isn't a
    recognisable transition.

    ``id_expr`` is how the caller addresses the record. It defaults to
    ``{{item.id}}`` (a per-row container) so existing call sites are unchanged;
    a detail page should pass ``{{record.id}}``."""
    if not index:
        return None
    try:
        info = index.get(entity_key(entity))
    except EntityNameError:
        return None
    if not info:
        return None

    # Consider EVERY status workflow registered for this table, not just the
    # first one indexed (register STATUS-4). A candidate that DECLARES the
    # target status is preferred over one that merely tolerates it, so an
    # "Approve" button picks the approval flow rather than whichever workflow
    # happened to be read off disk first.
    candidates = [info, *(info.get("alternates") or [])]
    best: tuple[dict, str] | None = None
    for cand in candidates:
        target = derive_target_status(label, cand.get("statuses") or [])
        if not target:
            continue
        declared = target in (cand.get("statuses") or [])
        if declared:
            best = (cand, target)
            break
        if best is None:
            best = (cand, target)
    if best is None:
        return None
    chosen, target = best

    return {
        "workflow": chosen["name"],
        "args": {
            # The id EXPRESSION is the caller's to supply (register STATUS-7).
            #
            # Every call site got `{{item.id}}`, which only resolves inside a
            # per-row container. On a detail page the record is bound as
            # `record` / `data`, so the argument resolved to nothing, the WHERE
            # matched no row, and the button silently did nothing. The default
            # keeps the row-context behaviour for existing callers.
            chosen["id_var"]: id_expr,
            chosen["status_var"]: target,
        },
    }
