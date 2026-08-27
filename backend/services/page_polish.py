"""Page-polish helpers used by the deterministic page builders.

The deterministic ``build_crud_page`` dispatch (``build_kanban_page``,
``build_list_page``, …) currently pulls a very small subset of the
planner's per-page dict — route, archetype/type, entity, fields — and
throws the rest away. That's why an emitted Kanban ends up with
``cardTitle: "email"`` and no row actions, even when the planner
authored a rich page with description prose, action list, and features
like ``["status-pipeline", "approval"]``.

This module is where the four polish levers live. Nothing here calls an
LLM; each helper is a pure function over registry+planner data. Callers
(the builders) opt in by threading a ``page_hint`` dict through.

Levers
------
1. **Smart column picking** (:func:`pick_card_props`) — chooses
   ``cardTitle``, ``cardSubtitle``, ``cardImage``, ``cardBadges`` using
   a semantic priority list on the entity's columns. Handles composite
   name columns (``firstName`` + ``lastName``) and honors any hints the
   description parser surfaces.
2. **Honor planner actions** (:func:`compose_card_actions`) — turns
   the planner's ``page.actions[]`` into Kanban ``cardActions`` or
   List row-action buttons. Preserves workflow bindings + input_map.
3. **Feature composers** (:func:`compose_features`) — dispatches on
   the planner's ``page.features[]`` list. First five features
   handled: ``approval`` (approve/reject actions), ``filterable``
   (header filter chips from enum + FK columns), ``metrics`` (stat
   row above the primary widget), ``timeline`` (append a Timeline
   section), ``search`` (header search input).
4. **Prose parser** (:func:`parse_description_hints`) — extracts
   column-name mentions from the planner's ``page.description`` so
   phrases like "cards show name, drive, nationality" wire into
   ``cardTitle/cardSubtitle/cardBadges``.

Contract
--------
Each helper returns primitive dicts / lists — never a full page schema
— so builders can mix them in freely. All helpers degrade to safe
defaults on missing/invalid input; nothing here raises.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional


# =========================================================================
# Lever 1 — smart column picking
# =========================================================================

# Priority orders. Case-insensitive; normalized column names (letters +
# digits only) are compared to each entry.

_CARD_TITLE_PRIORITY = (
    "fullname", "displayname", "name", "title", "label",
    "username", "firstname", "email", "code", "reference", "sku",
)

_CARD_SUBTITLE_PRIORITY = (
    "role", "jobtitle", "position", "company", "department",
    "team", "location", "nationality", "specialty", "category",
    "type", "kind",
)

_CARD_IMAGE_PRIORITY = (
    "avatarurl", "avatar", "photourl", "photo", "imageurl", "image",
    "profileimage", "picture", "thumbnail",
)

_CARD_BADGE_PRIORITY = (
    "status", "state", "stage", "priority", "level", "tier",
    "severity", "risk", "role", "kind", "category",
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _col_names(columns: dict) -> list[str]:
    """The list of column names in the entity, filtered to user-facing
    columns (drops id + timestamps + soft-delete)."""
    system = {"id", "createdat", "updatedat", "deletedat"}
    out = []
    for c in columns or {}:
        if _norm(c) in system:
            continue
        out.append(c)
    return out


def _pick_by_priority(columns: dict, priority: Iterable[str]) -> Optional[str]:
    """Return the column whose normalized name matches the earliest entry
    in ``priority``, or None if no column matches any entry."""
    names = _col_names(columns)
    norms = {_norm(n): n for n in names}
    for target in priority:
        if target in norms:
            return norms[target]
    return None


def _pick_first_enum_column(columns: dict, preferred: Iterable[str] = ()) -> Optional[str]:
    """Pick the first column that carries an ``enum`` metadata list. When
    ``preferred`` is supplied, prefer a name in that priority order
    among enum columns."""
    names = _col_names(columns)
    # First pass: any preferred name that has an enum
    prefer_norm = {p for p in preferred}
    enum_cols = []
    for n in names:
        meta = columns.get(n) or {}
        vals = meta.get("enum") or meta.get("enumValues") or meta.get("enum_values")
        if isinstance(vals, list) and vals:
            enum_cols.append(n)
    if not enum_cols:
        return None
    for want in prefer_norm:
        for c in enum_cols:
            if _norm(c) == want:
                return c
    return enum_cols[0]


def _detect_composite_name(columns: dict) -> Optional[str]:
    """``firstName`` + ``lastName`` present → return the concat binding
    ``{{firstName}} {{lastName}}`` for use as a cardTitle. Handles a few
    common shape variants (``first_name`` / ``firstname`` etc.). Returns
    None when a composite isn't detectable."""
    norms = {_norm(n): n for n in _col_names(columns)}
    first = norms.get("firstname") or norms.get("givenname")
    last = norms.get("lastname") or norms.get("surname") or norms.get("familyname")
    if first and last:
        return "{{" + first + "}} {{" + last + "}}"
    return None


def pick_card_props(
    columns: dict,
    *,
    hints: Optional[dict] = None,
) -> dict:
    """Return ``{cardTitle?, cardSubtitle?, cardImage?, cardBadges?}``
    picked from the entity's columns.

    ``hints`` may carry column-name suggestions extracted by the
    description parser — they take priority over the semantic
    fallbacks below. Values in ``hints`` that don't match a real column
    are ignored (the parser can be noisy on prose)."""
    hints = hints or {}
    real = {_norm(n) for n in _col_names(columns)}
    out: dict = {}

    # cardTitle: hint > composite name > priority > first user-facing string col
    hint_title = hints.get("title")
    if hint_title and _norm(hint_title) in real:
        out["cardTitle"] = _resolve_col(columns, hint_title)
    else:
        composite = _detect_composite_name(columns)
        if composite:
            out["cardTitle"] = composite
        else:
            title = _pick_by_priority(columns, _CARD_TITLE_PRIORITY)
            if title:
                out["cardTitle"] = title

    # cardSubtitle: hint > priority
    hint_sub = hints.get("subtitle")
    if hint_sub and _norm(hint_sub) in real:
        out["cardSubtitle"] = _resolve_col(columns, hint_sub)
    else:
        sub = _pick_by_priority(columns, _CARD_SUBTITLE_PRIORITY)
        if sub and sub != out.get("cardTitle"):
            out["cardSubtitle"] = sub

    # cardImage: hint > priority (only when an image-ish column exists)
    hint_img = hints.get("image")
    if hint_img and _norm(hint_img) in real:
        out["cardImage"] = _resolve_col(columns, hint_img)
    else:
        img = _pick_by_priority(columns, _CARD_IMAGE_PRIORITY)
        if img:
            out["cardImage"] = img

    # cardBadges: hint list (dedup + only real cols) > best-effort enum picks
    hint_badges = hints.get("badges")
    if isinstance(hint_badges, list) and hint_badges:
        picked = []
        seen = set()
        for h in hint_badges:
            resolved = _resolve_col(columns, h)
            if resolved and resolved not in seen:
                picked.append(resolved)
                seen.add(resolved)
        if picked:
            out["cardBadges"] = picked
    else:
        badge = _pick_by_priority(columns, _CARD_BADGE_PRIORITY)
        if badge:
            out["cardBadges"] = [badge]

    return out


def _resolve_col(columns: dict, want: str) -> Optional[str]:
    if not isinstance(want, str):
        return None
    target = _norm(want)
    for c in _col_names(columns):
        if _norm(c) == target:
            return c
    return None


# =========================================================================
# Lever 2 — honor planner actions
# =========================================================================

# Planner action shape (from itdvhi75 dossier):
#   { "kind": "row_action" | "collection_action" | ...,
#     "label": "Shortlist",
#     "workflow": "CandidatePipelineWorkflow",
#     "input_map": { "status": "status" | "'Shortlisted'" },
#     "requires_record": true }

_ROW_ACTION_KINDS = {"row_action", "record_action", "item_action", "card_action"}
_COLLECTION_ACTION_KINDS = {"collection_action", "header_action", "toolbar_action"}


def compose_card_actions(actions: list) -> list[dict]:
    """Turn the planner's ``page.actions`` into a list of Kanban
    ``cardActions`` / List row-action entries. Only ``row_action`` (and
    aliases) come through; collection-level actions are handled
    separately by :func:`compose_header_actions`. Malformed entries are
    dropped silently."""
    out: list[dict] = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or "").lower()
        if kind and kind not in _ROW_ACTION_KINDS:
            continue
        label = a.get("label")
        workflow = a.get("workflow") or a.get("workflowId")
        if not isinstance(label, str) or not label:
            continue
        entry: dict = {"label": label}
        if isinstance(workflow, str) and workflow:
            entry["workflow"] = workflow
        input_map = a.get("input_map") or a.get("inputMap")
        if isinstance(input_map, dict) and input_map:
            entry["input_map"] = dict(input_map)
        if a.get("variant"):
            entry["variant"] = str(a["variant"])
        out.append(entry)
    return out


def compose_header_actions(actions: list) -> list[dict]:
    """Turn the planner's ``collection_action`` entries into header
    button specs the builders can render above the primary widget."""
    out: list[dict] = []
    for a in actions or []:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or "").lower()
        if kind not in _COLLECTION_ACTION_KINDS:
            continue
        label = a.get("label")
        if not isinstance(label, str) or not label:
            continue
        entry: dict = {"label": label}
        workflow = a.get("workflow") or a.get("workflowId")
        if isinstance(workflow, str) and workflow:
            entry["workflow"] = workflow
        navigate = a.get("navigate") or a.get("to")
        if isinstance(navigate, str) and navigate:
            entry["navigate"] = navigate
        out.append(entry)
    return out


# =========================================================================
# Lever 3 — feature composers
# =========================================================================

def compose_features(
    features: list,
    *,
    columns: dict,
    entity: str,
    data_source: str,
) -> dict:
    """Dispatch the planner's ``features`` list to targeted composers.

    Returns ``{header_nodes, footer_nodes, extra_card_props, extra_ds}``:

    * ``header_nodes`` — nodes to insert BEFORE the primary widget (e.g.
      Stat row for ``metrics``, filter chip Row for ``filterable``,
      search Input for ``search``).
    * ``footer_nodes`` — nodes AFTER the primary widget (e.g. Timeline
      for ``timeline``).
    * ``extra_card_props`` — properties to merge into the primary
      widget's props (e.g. ``cardActions`` for ``approval`` when the
      planner didn't already supply them).
    * ``extra_ds`` — additional entries for the page's ``dataSources``
      (e.g. a stat count dataSource for ``metrics``).
    """
    feats = _normalize_features(features)
    header_nodes: list = []
    footer_nodes: list = []
    extra_card_props: dict = {}
    extra_ds: list = []

    if "approval" in feats:
        approval_actions = _compose_approval_actions(columns)
        if approval_actions:
            extra_card_props.setdefault("cardActions", []).extend(approval_actions)

    if "filterable" in feats:
        chip_row = _compose_filter_chips(columns)
        if chip_row is not None:
            header_nodes.append(chip_row)

    if "metrics" in feats:
        stat_row, stat_ds = _compose_metrics_row(entity, data_source, columns)
        if stat_row is not None:
            header_nodes.append(stat_row)
        if stat_ds:
            extra_ds.extend(stat_ds)

    if "timeline" in feats:
        timeline_node, timeline_ds = _compose_timeline(entity, data_source, columns)
        if timeline_node is not None:
            footer_nodes.append(timeline_node)
        if timeline_ds:
            extra_ds.extend(timeline_ds)

    if "search" in feats:
        search = _compose_search(columns)
        if search is not None:
            header_nodes.insert(0, search)

    return {
        "header_nodes": header_nodes,
        "footer_nodes": footer_nodes,
        "extra_card_props": extra_card_props,
        "extra_ds": extra_ds,
    }


def _normalize_features(features: Any) -> set[str]:
    if not isinstance(features, list):
        return set()
    out: set[str] = set()
    for f in features:
        if isinstance(f, str) and f.strip():
            out.add(f.strip().lower().replace("_", "-"))
    return out


def _compose_approval_actions(columns: dict) -> list[dict]:
    """When the entity has a status column with an enum that includes
    approval-shaped states, emit Approve/Reject actions bound to
    those states. When no enum is available, emit generic
    Approve/Reject actions with no input_map (the workflow decides)."""
    status_col = _pick_by_priority(columns, ("status", "state", "approval"))
    if not status_col:
        return [
            {"label": "Approve", "variant": "primary"},
            {"label": "Reject",  "variant": "danger"},
        ]
    return [
        {"label": "Approve",
         "input_map": {status_col: "'Approved'"},
         "variant": "primary"},
        {"label": "Reject",
         "input_map": {status_col: "'Rejected'"},
         "variant": "danger"},
    ]


def _compose_filter_chips(columns: dict) -> Optional[dict]:
    """Return a Row of chip filters for enum + FK columns. When there
    are no filter-worthy columns, returns None."""
    chips: list[dict] = []
    for name in _col_names(columns):
        meta = columns.get(name) or {}
        enum = meta.get("enum") or meta.get("enumValues") or meta.get("enum_values")
        is_fk = bool(meta.get("fk") or meta.get("foreignKey") or _looks_like_fk(name))
        if isinstance(enum, list) and enum:
            chips.append({
                "type": "FilterChip",
                "props": {"field": name, "label": _humanize(name), "options": list(enum)},
            })
        elif is_fk:
            chips.append({
                "type": "FilterChip",
                "props": {"field": name, "label": _humanize(name), "kind": "fk"},
            })
        if len(chips) >= 4:  # cap so the header stays scannable
            break
    if not chips:
        return None
    return {
        "type": "Row",
        "props": {"gap": "tokens.spacing.2", "align": "center"},
        "children": chips,
    }


def _compose_metrics_row(entity: str, data_source: str, columns: dict) -> tuple[Optional[dict], list[dict]]:
    """Emit a Row of Stat tiles above the primary widget. Total count
    is always shown; when a status column exists, add per-status counts
    for the top ~3 enum values (or 'Active' / 'Pending' if we can't
    infer)."""
    stats: list[dict] = []
    extra_ds: list[dict] = []

    total_ds = f"{data_source}Count"
    stats.append({
        "type": "Stat",
        "props": {"label": f"Total {_humanize_entity_plural(entity)}",
                  "value": f"{{{{{total_ds}}}}}"},
    })
    extra_ds.append({"name": total_ds, "entity": entity, "op": "count"})

    status_col = _pick_by_priority(columns, ("status", "state"))
    if status_col:
        enum = (columns.get(status_col) or {}).get("enum") or \
               (columns.get(status_col) or {}).get("enumValues") or \
               (columns.get(status_col) or {}).get("enum_values") or []
        for val in list(enum)[:3]:
            ds_name = f"{data_source}Count{_slug(val)}"
            stats.append({
                "type": "Stat",
                "props": {"label": _humanize(str(val)),
                          "value": f"{{{{{ds_name}}}}}"},
            })
            extra_ds.append({"name": ds_name, "entity": entity, "op": "count",
                             "where": {status_col: val}})

    row = {
        "type": "Row",
        "props": {"gap": "tokens.spacing.3", "wrap": True},
        "children": stats,
    }
    return row, extra_ds


def _compose_timeline(entity: str, data_source: str, columns: dict) -> tuple[Optional[dict], list[dict]]:
    """Append a Timeline section after the primary widget. The timeline
    binds to a *derived* recent-events dataSource of the same entity,
    ordered by createdAt DESC. When the entity has no timestamp
    column, degrade to using the primary list."""
    # Direct scan against ALL columns (timestamps are filtered by
    # _col_names as "system"; here they're exactly the columns we want).
    ts_priority = ("createdat", "updatedat", "occurredat", "eventat")
    norms = {_norm(n): n for n in (columns or {})}
    ts_col = next((norms[p] for p in ts_priority if p in norms), None)
    if not ts_col:
        return None, []
    events_ds = f"{data_source}Recent"
    title_col = _pick_by_priority(columns, _CARD_TITLE_PRIORITY) or "id"
    node = {
        "type": "Card",
        "props": {"title": "Recent activity"},
        "children": [{
            "type": "Timeline",
            "props": {
                "events":    f"{{{{{events_ds}}}}}",
                "dateField": ts_col,
                "titleField": title_col,
                "emptyText": "No recent activity",
            },
        }],
    }
    ds = [{"name": events_ds, "entity": entity, "op": "list",
           "orderBy": ts_col, "orderDir": "desc", "limit": 10}]
    return node, ds


def _compose_search(columns: dict) -> Optional[dict]:
    """Emit a header search Input over the entity's primary searchable
    column (label field)."""
    label_col = _pick_by_priority(columns, _CARD_TITLE_PRIORITY)
    if not label_col:
        return None
    return {
        "type": "Input",
        "props": {
            "type": "search",
            "name": "q",
            "placeholder": f"Search by {_humanize(label_col).lower()}…",
            "aria-label": f"Search by {_humanize(label_col).lower()}",
        },
    }


# =========================================================================
# Lever 4 — description prose parser
# =========================================================================

# Regexes are intentionally simple. False positives on prose are OK
# because pick_card_props filters extracted names against real columns.

_CARDS_SHOW_RE = re.compile(
    r"cards?\s+(?:show|display|include|feature)\s+([^.]+)",
    re.IGNORECASE,
)
_GROUPED_BY_RE = re.compile(
    r"grouped\s+by\s+([a-z][a-z_ ]*(?:\s+status|\s+stage)?)",
    re.IGNORECASE,
)
_FILTER_BY_RE = re.compile(
    r"filter(?:ed)?\s+by\s+([^.]+)",
    re.IGNORECASE,
)
_BADGE_RE = re.compile(r"([a-z][a-z_ ]*)\s+badge", re.IGNORECASE)


def parse_description_hints(description: str, columns: dict) -> dict:
    """Return a hints dict for :func:`pick_card_props` and other polish
    helpers.

    Shape::

        {
          "title":    "fullName"   | None,
          "subtitle": "nationality" | None,
          "badges":   ["experienceLevel"] | None,
          "groupBy":  "status" | None,
          "filters":  ["drive", "status"] | None
        }

    Values are drawn from mentions in the description that match real
    columns (case-insensitive, ignoring separators). Any mention that
    doesn't map to a real column is quietly dropped so noisy prose
    doesn't corrupt the schema.
    """
    if not isinstance(description, str) or not description.strip():
        return {}

    real_by_norm = {_norm(c): c for c in _col_names(columns)}
    hints: dict = {}

    # "cards show name, drive, nationality, aviation experience badge"
    m = _CARDS_SHOW_RE.search(description)
    if m:
        # Split on commas/and, extract each phrase as a candidate column
        tail = m.group(1)
        parts = re.split(r"[,;]|\band\b", tail, flags=re.IGNORECASE)
        candidates: list[str] = []
        badges: list[str] = []
        for p in parts:
            phrase = p.strip().rstrip(".")
            if not phrase:
                continue
            # "aviation experience badge" → badges list; drop the " badge" suffix.
            badge_m = _BADGE_RE.search(phrase)
            if badge_m:
                stripped = re.sub(r"\s+badge$", "", badge_m.group(1)).strip()
                candidates.append(stripped)
                badges.append(stripped)
                continue
            candidates.append(phrase)

        # Map each candidate phrase to a real column via progressive
        # normalization (spaces, hyphens, underscores collapse; try
        # exact hit first, then trailing-word slice for compound
        # phrases like "aviation experience").
        picked: list[str] = []
        picked_badges: list[str] = []
        badge_set = {b.lower() for b in badges}
        for phrase in candidates:
            resolved = _resolve_col_phrase(phrase, real_by_norm)
            if resolved:
                if phrase.lower() in badge_set:
                    picked_badges.append(resolved)
                else:
                    picked.append(resolved)

        if picked:
            # First non-badge → title; second → subtitle; rest folded to badges.
            hints["title"] = picked[0]
            if len(picked) > 1:
                hints["subtitle"] = picked[1]
            if len(picked) > 2:
                picked_badges.extend(picked[2:])

        if picked_badges:
            hints["badges"] = picked_badges

    # "grouped by pipeline status" → status
    m = _GROUPED_BY_RE.search(description)
    if m:
        target = m.group(1).strip()
        resolved = _resolve_col_phrase(target, real_by_norm)
        if resolved:
            hints["groupBy"] = resolved

    # "filter by drive and status"
    m = _FILTER_BY_RE.search(description)
    if m:
        parts = re.split(r"[,;]|\band\b", m.group(1), flags=re.IGNORECASE)
        picked: list[str] = []
        for p in parts:
            phrase = p.strip().rstrip(".")
            if not phrase:
                continue
            resolved = _resolve_col_phrase(phrase, real_by_norm)
            if resolved and resolved not in picked:
                picked.append(resolved)
        if picked:
            hints["filters"] = picked

    return hints


def _resolve_col_phrase(phrase: str, real_by_norm: dict[str, str]) -> Optional[str]:
    """Resolve a possibly-compound prose phrase ('aviation experience',
    'pipeline status') to a real column. Progresses through exact hit,
    substring hit (either direction — 'name' → fullName, 'pipeline
    status' → status), then trailing-word chunks for cases where the
    substring pass didn't find a home. Returns None on total miss."""
    if not isinstance(phrase, str) or not phrase.strip():
        return None
    key = _norm(phrase)
    if not key:
        return None
    if key in real_by_norm:
        return real_by_norm[key]
    # Substring resolution — the phrase norm contains, or is contained by,
    # a real column norm. Iterate insertion order so results are stable.
    for rn, rc in real_by_norm.items():
        if key in rn or rn in key:
            return rc
    # Trailing-chunk fallback: "aviation experience" → "experience"; try
    # substring at each shrink.
    words = re.split(r"\s+", phrase.strip())
    while len(words) > 1:
        words = words[1:]
        candidate = _norm("".join(words))
        if not candidate:
            continue
        if candidate in real_by_norm:
            return real_by_norm[candidate]
        for rn, rc in real_by_norm.items():
            if candidate in rn or rn in candidate:
                return rc
    return None


# =========================================================================
# Small utilities
# =========================================================================

def _looks_like_fk(name: str) -> bool:
    """FK columns commonly end in Id / _id."""
    n = name or ""
    return n.endswith("Id") or n.endswith("_id") or n.lower() == "userid"


def _humanize(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "")
    s = s.replace("_", " ").replace("-", " ").strip()
    return " ".join(w.capitalize() for w in s.split()) or (name or "")


def _humanize_entity_plural(entity: str) -> str:
    h = _humanize(entity)
    if h.endswith("s"):
        return h
    if h.endswith("y"):
        return h[:-1] + "ies"
    return h + "s"


def _slug(s: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(s or ""))
