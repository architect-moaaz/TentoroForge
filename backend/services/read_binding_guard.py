"""Read-binding reconciler (Slice R1 of the read-binding contract).

Every read-bound node — a Table's `rows`, a List's `items`, a Chart's `data`, a
map's `resources`/`events`/`entries`, a Stat's `value` — carries a `{{name}}`
binding that MUST name a page dataSource the renderer can resolve. When it does
not, the renderer returns the literal ``"{{name}}"`` string and the node renders
empty with no error (interpolate.ts). This guard is the read-side twin of the
button/action contract: it walks every page schema and, for each read binding,

  1. **resolves** it (the name is already a declared dataSource) — no-op;
  2. **remaps** a naming-drift orphan (``{{drives}}`` ↔ ``recruitmentDrives``) to
     the real dataSource of a compatible op; or
  3. **materializes** the missing derived dataSource — decoding a semantic prefix
     (``active``/``recent``/``upcoming``/…) or a ``By<Col>`` grouping into a real
     ``filter``/``sort``/``limit`` over the entity's ACTUAL columns — rather than
     renaming onto the base list (which caused name collisions).

Anything whose stripped base does not map to a real registered entity is left
**unresolved** (never guessed) so the validator can error on it.

Deterministic and idempotent: a derived binding is always classified
``materialized`` (whether or not the dataSource already exists), a dataSource is
never appended twice by name, and an already-resolvable binding is never
rewritten — so a second run produces byte-identical schema files AND
``contracts/data-contract.json``. Own try/except at the module boundary; never
raises.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re

from services.binding_validator import _SlugResolver, _read_schema_tables
from services.list_data_source_guard import _canon
from services.read_binding_semantics import decode_view, strip_prefix

logger = logging.getLogger(__name__)

# A pure single-token binding: "{{ recruitmentDrives }}" -> "recruitmentDrives".
_SINGLE_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][\w]*)\s*\}\}$")
# A (possibly dotted) stat binding: "{{open.count}}" -> ("open", "count").
_DOTTED_RE = re.compile(r"^\{\{\s*([A-Za-z_][\w]*)\s*(?:\.([A-Za-z_][\w.]*))?\s*\}\}$")
# A camelCase "…By<Col>" grouping suffix: "recruitmentDrivesByStatus".
_BY_RE = re.compile(r"^(.*?)By([A-Z][\w]*)$")
# Leading camelCase word split: "shortlistedApplicants" -> ("shortlisted", "Applicants").
_LEADING_CAMEL_RE = re.compile(r"^([a-z][a-z0-9]*)([A-Z][\w]*)$")

# ── node → binding-prop map ──────────────────────────────────────────────────
_LIST_PROPS = ("items", "data", "records")
_STAT_PROPS = ("value", "current", "count", "score")
_STAT_TYPES = {
    "stat", "statcard", "metric", "metrictile", "metriccard", "kpi", "kpicard",
    "gauge", "progress", "counter", "scorecard",
}
_READ_BINDINGS: dict[str, tuple[str, ...]] = {
    "table": ("rows",), "datatable": ("rows",), "datagrid": ("rows",),
    "list": _LIST_PROPS, "datalist": _LIST_PROPS, "cardlist": _LIST_PROPS,
    "recordlist": _LIST_PROPS, "listview": _LIST_PROPS, "itemlist": _LIST_PROPS,
    "chart": ("data",),
    "resourcetimeline": ("resources", "items"),
    "calendar": ("events",),
    "timeline": ("entries",),
    "kanban": ("data",),
    **{t: _STAT_PROPS for t in _STAT_TYPES},
}

# ops considered compatible for a remap of each want-op.
_COMPAT: dict[str, set[str]] = {
    "list": {"list", "table", "grid", "index"},
    "series": {"series"},
    "aggregate": {"aggregate"},
}

# Status-like column names (lowercased) that carry a lifecycle value.
_STATUS_NAMES = {"status", "state", "stage"}
# Lifecycle prefixes whose materialized filter value MUST be verified against the
# app's real status vocabulary (captured enum + workflow-harvested literals). When
# no real value matches, the filter is OMITTED rather than guessed — a guessed
# value (e.g. capitalized "Active") that the app never uses matches zero rows and
# renders the widget empty, the exact failure this contract exists to prevent.
_STATUS_PREFIXES = {"active", "open", "pending", "closed", "completed"}
# Common category columns for a series groupBy fallback.
_CATEGORY_HINTS = (
    "status", "priority", "type", "category", "source", "stage", "state",
    "kind", "tier", "level", "role", "channel", "department", "region",
)


def _node_type(node: dict) -> str:
    return str(node.get("type") or node.get("component") or "").lower()


def _want_op(ntype: str) -> str:
    if ntype in _STAT_TYPES:
        return "aggregate"
    if ntype == "chart":
        return "series"
    return "list"


def _entity_name(slug: str) -> str:
    """PascalCase singular of a registered slug: recruitmentDrives→RecruitmentDrive."""
    s = slug
    if len(s) > 3 and s.endswith("ies"):
        s = s[:-3] + "y"
    elif len(s) > 2 and s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s[:1].upper() + s[1:]


def _derive_entity(resolver: _SlugResolver, token: str,
                   vocab: _Vocab | None = None) -> tuple[str | None, str, str | None]:
    """Decode a binding token → (entity_slug, prefix, groupBy_hint).

    Strips a semantic prefix, then resolves the remainder to a registered entity
    slug; failing that, splits a ``…By<Col>`` grouping suffix and resolves the
    left part (the grouping column becomes the hint). As a last resort, treats a
    leading camelCase word as a status-value prefix when it matches the resolved
    entity's REAL status vocabulary (``{{shortlistedApplicants}}`` where the app's
    status literals include "shortlisted"). ``(None, prefix, None)`` if no real
    entity backs the token — never guessed.
    """
    prefix, base = strip_prefix(token)
    slug = resolver.resolve(base)
    if slug:
        return slug, prefix, None
    m = _BY_RE.match(base)
    if m:
        left, right = m.group(1), m.group(2)
        slug = resolver.resolve(left)
        if slug:
            return slug, prefix, (right[:1].lower() + right[1:])
    if vocab is not None:
        word, rest = _split_leading_camel(token)
        if word and rest:
            slug = resolver.resolve(rest)
            if slug:
                status_col = _status_col(resolver.columns_for(slug))
                if status_col:
                    known = {v.lower() for v in vocab.values_for(slug, status_col)}
                    if word.lower() in known:
                        return slug, word.lower(), None
    return None, prefix, None


def _status_col(raw_cols: dict) -> str | None:
    for name in raw_cols:
        if str(name).lower() in _STATUS_NAMES:
            return name
    return None


def _is_status_ish(col) -> bool:
    c = str(col or "").strip().lower()
    return c in _STATUS_NAMES or c.endswith(("status", "state", "stage"))


def _split_leading_camel(token: str) -> tuple[str, str]:
    """"shortlistedApplicants" -> ("shortlisted", "applicants"); no split -> ("", token)."""
    m = _LEADING_CAMEL_RE.match(token or "")
    if not m:
        return "", token
    return m.group(1), m.group(2)[:1].lower() + m.group(2)[1:]


def _wf_status_by_slug(output_dir: str, resolver: _SlugResolver) -> dict[str, list[str]]:
    """{entity_slug -> [real status literals]} harvested from workflow db_insert/
    db_update `values.<statusish>` + `statusValue`, scoped to the written table.

    Only LITERAL strings are collected (skips `{{template}}` refs and passthrough
    variable bindings whose value equals the column name). This is the same class
    of harvesting `semantic_field_types.harvest_workflow_statuses` does, but keyed
    by the target ENTITY (via its table) rather than globally by column — so one
    entity's vocabulary can't leak into another's filter.
    """
    out: dict[str, list[str]] = {}

    def add(slug: str | None, col, val) -> None:
        if not slug or not isinstance(val, str):
            return
        v = val.strip()
        if not v or v.startswith("{{"):
            return
        if v.lower() == str(col or "").strip().lower():
            return  # passthrough variable binding, not a literal
        lst = out.setdefault(slug, [])
        if v not in lst:
            lst.append(v)

    def walk(obj) -> None:
        if isinstance(obj, dict):
            cfg = obj.get("config") if isinstance(obj.get("config"), dict) else None
            data = obj.get("data") if isinstance(obj.get("data"), dict) else None
            if data and isinstance(data.get("config"), dict):
                cfg = data["config"]
            if isinstance(cfg, dict):
                atype = str(cfg.get("actionType", "")).strip().lower()
                slug = resolver.resolve(cfg.get("table")) if isinstance(cfg.get("table"), str) else None
                if atype in ("db_insert", "db_update"):
                    vals = cfg.get("values")
                    if isinstance(vals, dict):
                        for col, val in vals.items():
                            if _is_status_ish(col):
                                add(slug, col, val)
                sv = cfg.get("statusValue")
                if isinstance(sv, str):
                    add(slug, cfg.get("column") or cfg.get("field") or "status", sv)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    for fp in sorted(glob.glob(os.path.join(output_dir, "workflows", "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                wf = json.load(fh)
        except (OSError, ValueError):
            continue
        walk(wf)
    return out


class _Vocab:
    """Real status vocabulary per entity, so a materialized filter only ever uses a
    VERIFIED value. Precision-first: workflow literals + registry enums scoped to
    the entity; a global by-column workflow harvest is a last-resort fallback only
    when the entity itself contributed nothing.
    """

    def __init__(self, output_dir: str, resolver: _SlugResolver):
        self.by_slug: dict[str, list[str]] = {}
        self.by_col: dict[str, list[str]] = {}
        try:
            self.by_slug = _wf_status_by_slug(output_dir, resolver)
        except Exception:  # noqa: BLE001
            self.by_slug = {}
        # Registry-declared enums (schema `.$type<>()`/pgEnum) — source (1), exact.
        try:
            from services.semantic_field_types import _registry_enum_values
            for ent, colmap in (_registry_enum_values(output_dir) or {}).items():
                slug = resolver.resolve(ent)
                if not slug or not isinstance(colmap, dict):
                    continue
                for col, vals in colmap.items():
                    if _is_status_ish(col) and isinstance(vals, list):
                        lst = self.by_slug.setdefault(slug, [])
                        for v in vals:
                            if isinstance(v, str) and v not in lst:
                                lst.append(v)
        except Exception:  # noqa: BLE001
            pass
        # Global by-column workflow harvest — reused as a last-resort fallback.
        try:
            from services.semantic_field_types import harvest_workflow_statuses
            for col, vals in (harvest_workflow_statuses(output_dir) or {}).items():
                if _is_status_ish(col) and isinstance(vals, list):
                    lst = self.by_col.setdefault(str(col).lower(), [])
                    for v in vals:
                        if isinstance(v, str) and v not in lst:
                            lst.append(v)
        except Exception:  # noqa: BLE001
            pass

    def values_for(self, slug: str | None, status_col) -> list[str]:
        vals = list(self.by_slug.get(slug, [])) if slug else []
        if not vals and status_col:
            vals = list(self.by_col.get(str(status_col).lower(), []))
        return vals


def _group_col(hint: str | None, raw_cols: dict) -> str:
    """Pick a real grouping column for a series: hint → status-like → category → any."""
    if hint:
        for name in raw_cols:
            if str(name).lower() == hint.lower():
                return name
    col = _status_col(raw_cols)
    if col:
        return col
    for h in _CATEGORY_HINTS:
        for name in raw_cols:
            if str(name).lower() == h:
                return name
    for name in raw_cols:
        if str(name).lower() not in ("id", "createdat", "created_at", "updatedat", "updated_at"):
            return name
    return next(iter(raw_cols), "id")


def _build_view(prefix: str, raw_cols: dict, status_values: list[str] | None = None) -> dict:
    """Decode prefix → {filter?, sort?, limit?} over the entity's real columns.

    A status filter is only ever emitted with a VERIFIED value. The entity's real
    status vocabulary (``status_values``) is injected as the status column's enum
    so ``decode_view`` matches a lifecycle prefix's intended token(s) against real
    values (using their exact casing); an arbitrary status-value prefix (e.g.
    ``shortlisted``) that ``decode_view``'s fixed lifecycle set doesn't know is
    matched here directly. If NO real value matches, the filter is OMITTED — never
    guessed — so the materialized dataSource is an unfiltered (non-empty) list.
    """
    status_col = _status_col(raw_cols)
    status_values = status_values or []
    cols: dict = {}
    for n, t in raw_cols.items():
        meta: dict = {"type": t}
        if n == status_col and status_values:
            meta["enum"] = status_values
        cols[n] = meta

    view = dict(decode_view(prefix, cols))

    # Verbatim status-value prefix (e.g. "shortlisted") — decode_view only knows the
    # fixed lifecycle prefixes, so match the raw prefix against the real vocabulary
    # and use its exact casing. Guarded to status prefixes: only fill when the
    # lifecycle set didn't (never overrides a decode_view enum match).
    if "filter" not in view and status_col and prefix:
        for real in status_values:
            if isinstance(real, str) and real.lower() == prefix.lower():
                view["filter"] = {status_col: real}
                break
    return view


class _Ctx:
    """Per-file mutable walk state."""

    def __init__(self, resolver: _SlugResolver, data_sources: list, rel: str,
                 vocab: _Vocab):
        self.resolver = resolver
        self.data_sources = data_sources
        self.rel = rel
        self.vocab = vocab
        self.ds_names: set[str] = {
            ds["name"] for ds in data_sources
            if isinstance(ds, dict) and isinstance(ds.get("name"), str)
        }
        self.ds_by_name: dict[str, dict] = {
            ds["name"]: ds for ds in data_sources
            if isinstance(ds, dict) and isinstance(ds.get("name"), str)
        }
        self.mutated = False
        self.records: list[dict] = []

    def set_prop(self, container: dict, key: str, value) -> None:
        if container.get(key) != value:
            container[key] = value
            self.mutated = True

    def add_source(self, ds: dict) -> None:
        name = ds["name"]
        if name in self.ds_names:
            return  # dedup — idempotent
        self.data_sources.append(ds)
        self.ds_names.add(name)
        self.ds_by_name[name] = ds
        self.mutated = True


def _remap_target(token: str, want_op: str, ctx: _Ctx) -> str | None:
    """A unique canonical match (else the sole) dataSource of a compatible op."""
    compat = _COMPAT.get(want_op, set())
    names = [
        ds["name"] for ds in ctx.data_sources
        if isinstance(ds, dict) and isinstance(ds.get("name"), str)
        and str(ds.get("op", "")).lower() in compat
    ]
    canon_idx: dict[str, list[str]] = {}
    for n in names:
        canon_idx.setdefault(_canon(n), []).append(n)
    hits = canon_idx.get(_canon(token), [])
    if len(hits) == 1:
        return hits[0]
    if len(names) == 1:
        return names[0]
    return None


def _materialize(node: dict, container: dict, prop: str, token: str, slug: str,
                 entity: str, want_op: str, metric: str | None, prefix: str,
                 gb_hint: str | None, ctx: _Ctx) -> None:
    """Append the derived dataSource (dedup) + normalize a chart's render config."""
    raw_cols = ctx.resolver.columns_for(slug)
    status_values = ctx.vocab.values_for(slug, _status_col(raw_cols))
    if want_op == "series":
        ds = {"name": token, "entity": entity, "op": "series",
              "groupBy": _group_col(gb_hint, raw_cols), "agg": {"fn": "count"}}
        ctx.add_source(ds)
        ctx.set_prop(container, "data", "{{%s}}" % token)
        ctx.set_prop(container, "xKey", "label")
        ctx.set_prop(container, "series", [{"name": entity, "dataKey": "value"}])
    elif want_op == "aggregate":
        view = _build_view(prefix, raw_cols, status_values)
        metric_cfg = {"fn": "count"}
        metric_cfg.update(view.get("filter", {}))
        ds = {"name": token, "entity": entity, "op": "aggregate",
              "metrics": {metric or "value": metric_cfg}}
        ctx.add_source(ds)
    else:  # list
        ds = {"name": token, "entity": entity, "op": "list"}
        ds.update(_build_view(prefix, raw_cols, status_values))
        ctx.add_source(ds)


def _handle_binding(node: dict, container: dict, prop: str, token: str,
                    metric: str | None, want_op: str, ntype: str, ctx: _Ctx) -> None:
    slug, prefix, gb_hint = _derive_entity(ctx.resolver, token, ctx.vocab)
    derived = bool(slug and (prefix or gb_hint))
    entity = op = None
    resolved = False

    if derived:
        entity = _entity_name(slug)
        op = want_op
        resolved = True
        action = "materialized"
        _materialize(node, container, prop, token, slug, entity, want_op,
                     metric, prefix, gb_hint, ctx)
    elif token in ctx.ds_names:
        action = "resolved"
        resolved = True
        ds = ctx.ds_by_name.get(token)
        if ds:
            entity, op = ds.get("entity"), ds.get("op")
    else:
        target = _remap_target(token, want_op, ctx)
        if target:
            new = "{{%s}}" % target if metric is None else "{{%s.%s}}" % (target, metric)
            ctx.set_prop(container, prop, new)
            action = "remapped"
            resolved = True
            ds = ctx.ds_by_name.get(target)
            if ds:
                entity, op = ds.get("entity"), ds.get("op")
        else:
            action = "unresolved"

    ctx.records.append({
        "file": ctx.rel,
        "node_type": node.get("type") or node.get("component"),
        "binding_prop": prop,
        "binding_name": token,
        "entity": entity,
        "op": op,
        "resolved": resolved,
        "action": action,
    })


def _process_node(node: dict, ctx: _Ctx) -> None:
    ntype = _node_type(node)
    props_tuple = _READ_BINDINGS.get(ntype)
    if not props_tuple:
        return
    is_stat = ntype in _STAT_TYPES
    want_op = _want_op(ntype)
    props = node.get("props") if isinstance(node.get("props"), dict) else None
    for prop in props_tuple:
        for container in ([node] if node is not None else []) + ([props] if props else []):
            val = container.get(prop)
            if not isinstance(val, str):
                continue
            if is_stat:
                m = _DOTTED_RE.match(val)
                if not m:
                    continue
                token, metric = m.group(1), (m.group(2) or "value")
            else:
                m = _SINGLE_TOKEN_RE.match(val)
                if not m:
                    continue
                token, metric = m.group(1), None
            _handle_binding(node, container, prop, token, metric, want_op, ntype, ctx)
            break  # one occurrence per prop


def _walk(node, ctx: _Ctx) -> None:
    if isinstance(node, dict):
        _process_node(node, ctx)
        for v in node.values():
            _walk(v, ctx)
    elif isinstance(node, list):
        for v in node:
            _walk(v, ctx)


def _write_contract(output_dir: str, records: list[dict]) -> None:
    cdir = os.path.join(output_dir, "contracts")
    os.makedirs(cdir, exist_ok=True)
    nodes = sorted(
        records,
        key=lambda n: (str(n["file"]), str(n["binding_prop"]), str(n["binding_name"])),
    )
    payload = {"version": 1, "nodes": nodes}
    with open(os.path.join(cdir, "data-contract.json"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, indent=2, sort_keys=True))


def reconcile_read_bindings(output_dir: str) -> dict:
    """Reconcile every read binding on every page against the real registries.

    Returns ``{files_scanned, files_changed, actions_by_kind:{resolved, remapped,
    materialized, unresolved}, nodes:[...]}``. Writes changed schema files and
    ``contracts/data-contract.json``. Idempotent; never raises.
    """
    result = {
        "files_scanned": 0,
        "files_changed": 0,
        "actions_by_kind": {"resolved": 0, "remapped": 0, "materialized": 0, "unresolved": 0},
        "nodes": [],
    }
    try:
        tables = _read_schema_tables(output_dir)
        resolver = _SlugResolver(tables)
        vocab = _Vocab(output_dir, resolver)
        all_records: list[dict] = []

        sdir = os.path.join(output_dir, "src", "schemas")
        if os.path.isdir(sdir):
            for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"), recursive=True)):
                rel = os.path.relpath(fp, sdir)
                if os.path.basename(fp) in ("nav-flow.json",):
                    continue
                result["files_scanned"] += 1
                try:
                    with open(fp, encoding="utf-8") as fh:
                        page = json.load(fh)
                except (OSError, ValueError) as e:
                    logger.warning("read_binding_guard: could not parse %s: %s", rel, e)
                    continue
                if not isinstance(page, dict):
                    continue

                data_sources = page.get("dataSources")
                if not isinstance(data_sources, list):
                    data_sources = []
                ctx = _Ctx(resolver, data_sources, rel, vocab)
                root = page.get("root") if isinstance(page.get("root"), dict) else page
                _walk(root, ctx)

                for rec in ctx.records:
                    result["actions_by_kind"][rec["action"]] += 1
                    all_records.append(rec)

                if ctx.mutated:
                    page["dataSources"] = data_sources
                    result["files_changed"] += 1
                    try:
                        with open(fp, "w", encoding="utf-8") as fh:
                            json.dump(page, fh, indent=2)
                    except OSError as e:
                        logger.warning("read_binding_guard: could not write %s: %s", rel, e)

        result["nodes"] = all_records
        _write_contract(output_dir, all_records)
    except Exception:  # noqa: BLE001 — an additive guard must never break the pipeline
        logger.exception("read_binding_guard: internal error (degrading to no-op)")

    return result
