"""Per-app BLUEPRINT.md builder.

Every generated app has a `BLUEPRINT.md` sitting at its root — a
human-readable Markdown snapshot of everything about the app: what it
is, its data model (with a Mermaid ER diagram), pages, navigation
(with a Mermaid flowchart), workflows (with per-workflow diagrams),
forms, design spec, actors/roles, and architecture.

The blueprint is generated deterministically from whatever contracts +
schemas are on disk. This module is a PURE function: it reads files
and returns a Markdown string — never writes. See
``services.blueprint_writer`` for the write side (atomic writes, log
appending, idempotency).

Design principles
-----------------

* **Best-effort.** Every referenced file is optional. A missing
  contract does not crash — the corresponding section is either
  skipped or degraded to a short "not present" line.
* **Deterministic.** Given the same input tree, always produces the
  same Markdown byte-for-byte (except for the ``Last built`` header,
  which the writer strips before its idempotency check).
* **Multiple layouts.** Different generation phases land contract
  files at either ``contracts/`` (root) OR ``src/contracts/``; both
  are probed. Same for ``registry.json`` at root vs
  ``contracts/resource-registry.json``.
* **Mermaid-safe.** IDs are sanitized to Mermaid identifier syntax;
  labels are wrapped in quotes; circular refs degrade to a bullet
  list with an inline note so the block still renders.

Public surface: :func:`build_blueprint` and :data:`BLUEPRINT_VERSION`.
Everything else is internal (single-leading-underscore).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


BLUEPRINT_VERSION = 1


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def build_blueprint(
    output_dir: str | Path,
    *,
    mutation_source: str | None = None,
) -> str:
    """Read whatever contracts + schemas live under ``output_dir`` and
    return the complete BLUEPRINT.md text.

    Missing files degrade cleanly. The function never raises on
    malformed input — bad JSON logs a warning and the section is
    skipped or emitted with a "(not readable)" placeholder.

    ``mutation_source`` names the seam that triggered this build
    (``"generation" | "editor" | "smith" | "manual" | …``). When
    provided, it is annotated into the header line so a reader can
    see which pipeline actually wrote the blueprint currently on
    disk — makes out-of-band edits visible.
    """
    root = Path(output_dir)
    sources = _load_sources(root)

    parts: list[str] = []
    parts.append(_render_header(sources, mutation_source=mutation_source))
    parts.append(_render_description(sources))
    parts.append(_render_architecture(sources))
    parts.append(_render_data_model(sources))
    parts.append(_render_actors(sources))
    parts.append(_render_pages(sources))
    parts.append(_render_navigation(sources))
    parts.append(_render_workflows(sources))
    parts.append(_render_forms(sources))
    parts.append(_render_design(sources))
    parts.append(_render_content_bank(sources))
    # Uncovered check runs against the OTHER sections we're about to
    # ship — not the on-disk file — so first-build and second-build
    # produce the same result (no drift flip-flop).
    body_so_far = "\n\n".join(p for p in parts if p and p.strip())
    parts.append(_render_uncovered(sources, root, body_so_far=body_so_far))
    parts.append(_render_generation_log(sources))

    # Drop empty sections cleanly and separate with blank lines.
    body = "\n\n".join(p.rstrip() for p in parts if p and p.strip())
    if not body.endswith("\n"):
        body += "\n"
    return body


# --------------------------------------------------------------------------- #
# Source loading — silently tolerant of missing / malformed files
# --------------------------------------------------------------------------- #

class _Sources:
    """Cached read-once view of every source file the builder consumes."""

    def __init__(self, root: Path):
        self.root = root
        self.plan: dict = _read_json_first(root, [
            "contracts/plan.json",
            "src/contracts/plan.json",
            "plan.json",
        ]) or {}
        self.brief: dict = _read_json_first(root, [
            "contracts/brief.json",
            "src/contracts/brief.json",
        ]) or {}
        self.design_spec: dict = _read_json_first(root, [
            "contracts/design-spec.json",
            "src/contracts/design-spec.json",
        ]) or {}
        self.nav_flow: dict = _read_json_first(root, [
            "contracts/nav-flow.json",
            "src/contracts/nav-flow.json",
        ]) or {}
        # Two registries: canonical resource-registry (rich, entity-centric)
        # and the emitter's flatter registry.json at root. Prefer the former.
        self.resource_registry: dict = _read_json_first(root, [
            "contracts/resource-registry.json",
            "src/contracts/resource-registry.json",
        ]) or {}
        self.flat_registry: dict = _read_json_first(root, [
            "registry.json",
        ]) or {}
        # Root-level navigation.json (editor screen graph) — falls back
        # when nav-flow.json is missing.
        self.navigation: dict = _read_json_first(root, [
            "navigation.json",
        ]) or {}
        self.package: dict = _read_json_first(root, ["package.json"]) or {}
        self.dossier: dict = _read_json_first(root, [
            "contracts/generation-dossier.json",
            "src/contracts/generation-dossier.json",
        ]) or {}
        self.discovery: dict = _read_json_first(root, [
            "contracts/discovery.json",
            "src/contracts/discovery.json",
        ]) or {}

        self.schemas: dict[str, dict] = _load_schemas(root)
        self.workflows: dict[str, dict] = _load_workflows(root)
        self.change_log: list[dict] = _load_change_log(root)


def _load_sources(root: Path) -> _Sources:
    return _Sources(root)


def _read_json_first(root: Path, rel_paths: list[str]) -> dict | None:
    for rel in rel_paths:
        p = root / rel
        if p.is_file():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                logger.warning(
                    "blueprint_builder: %s unreadable (%r); skipping",
                    p, exc,
                )
                return None
    return None


def _load_schemas(root: Path) -> dict[str, dict]:
    """Walk ``src/schemas/`` recursively, return {relpath: parsed}."""
    out: dict[str, dict] = {}
    base = root / "src" / "schemas"
    if not base.is_dir():
        return out
    for p in sorted(base.rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        rel = str(p.relative_to(base))
        out[rel] = data
    return out


def _load_workflows(root: Path) -> dict[str, dict]:
    """Load every workflow JSON — from ``workflows/`` at root OR
    ``contracts/workflows/``. Keyed by workflow name."""
    out: dict[str, dict] = {}
    for base_rel in ("workflows", "contracts/workflows"):
        base = root / base_rel
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            name = str(data.get("name") or p.stem)
            if name not in out:
                out[name] = data
    return out


def _load_change_log(root: Path) -> list[dict]:
    """Read the hidden ``.blueprint-log.jsonl`` (JSONL, newest last).
    Missing file returns []."""
    p = root / ".blueprint-log.jsonl"
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict):
                    out.append(entry)
            except ValueError:
                continue
    except OSError:
        return []
    return out


# --------------------------------------------------------------------------- #
# Rendering — header + top-level
# --------------------------------------------------------------------------- #

def _app_name(s: _Sources) -> str:
    """Pick the best available human-readable app name."""
    for cand in (
        (s.plan or {}).get("name"),
        (s.plan or {}).get("app_name"),
        (s.dossier or {}).get("plan", {}).get("name") if isinstance(s.dossier.get("plan"), dict) else None,
        (s.brief or {}).get("identity", {}).get("domain") if isinstance(s.brief.get("identity"), dict) else None,
        (s.discovery or {}).get("domain"),
        (s.package or {}).get("name"),
    ):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return "Untitled App"


def _description(s: _Sources) -> str:
    """Best available prose description."""
    for cand in (
        (s.plan or {}).get("description"),
        (s.plan or {}).get("brief"),
        (s.dossier or {}).get("prompt"),
        (s.discovery or {}).get("description"),
    ):
        if isinstance(cand, str) and cand.strip():
            return cand.strip()
    return ""


def _render_header(s: _Sources, *, mutation_source: str | None = None) -> str:
    name = _app_name(s)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Prefer the caller-supplied source; when omitted, fall back to the
    # newest log entry's source (the writer appends to the log BEFORE
    # calling the builder, so this row is the current mutation).
    src = (mutation_source or "").strip()
    if not src:
        log = s.change_log or []
        if log:
            src = str((log[-1] or {}).get("source") or "").strip()
    src = src or "unknown"
    log_n = len(s.change_log or [])
    return (
        f"# {name}\n\n"
        f"_Last built: {ts} · Blueprint version {BLUEPRINT_VERSION} · "
        f"Written by: {src} · Log: {log_n} entr"
        f"{'y' if log_n == 1 else 'ies'}_"
    )


def _render_description(s: _Sources) -> str:
    d = _description(s)
    if not d:
        return ""
    return f"> {d}"


def _render_architecture(s: _Sources) -> str:
    # The generated app's architecture is fixed by the pipeline; we still
    # emit it because it's the second thing anyone reading the doc asks.
    pkg = s.package or {}
    deps = (pkg.get("dependencies") or {}) if isinstance(pkg.get("dependencies"), dict) else {}
    next_v = deps.get("next") or "^15"
    react_v = deps.get("react") or "^19"

    lines = ["## Architecture"]
    lines.append(f"- Frontend: Next.js {next_v} (App Router) + React {react_v}")
    lines.append("- Backend: Next.js API routes + Drizzle ORM + PostgreSQL")
    lines.append("- Auth: NextAuth")
    lines.append("- Runtime: @tentoroforge/renderer")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

def _extract_entities(s: _Sources) -> list[dict]:
    """Canonical entity list unified across the three shapes the pipeline
    produces:

    * resource-registry.json: {"entities": {Name: {columns: [...], ...}}}
    * flat registry.json:     {"entities": {Name: {fields: {name: {...}}}}}
    * plan.json:              {"entities": {Name: {...}}} OR "data_models": [...]
    """
    out: list[dict] = []
    seen: set[str] = set()

    def _push(name: str, columns: list[dict], purpose: str = "") -> None:
        if not name or name in seen:
            return
        seen.add(name)
        out.append({"name": name, "columns": columns, "purpose": purpose})

    def _cols_from_registry(rec: dict) -> list[dict]:
        cols = rec.get("columns")
        if isinstance(cols, list):
            return [
                {
                    "name": c.get("name") or "",
                    "type": c.get("type") or "",
                    "fk": c.get("fk") or "",
                    "notNull": bool(c.get("notNull")),
                    "primaryKey": bool(c.get("primaryKey")),
                    "enum": c.get("enum") or c.get("enum_values") or None,
                }
                for c in cols if isinstance(c, dict) and c.get("name")
            ]
        fields = rec.get("fields")
        if isinstance(fields, dict):
            return [
                {
                    "name": fname,
                    "type": (fdef or {}).get("type") or "",
                    "fk": (fdef or {}).get("fk") or "",
                    "notNull": (fdef or {}).get("nullable") is False,
                    "primaryKey": bool((fdef or {}).get("primaryKey")),
                    "enum": (fdef or {}).get("enum_values") or None,
                }
                for fname, fdef in fields.items()
            ]
        return []

    # 1) resource-registry — richest source.
    rr = (s.resource_registry or {}).get("entities")
    if isinstance(rr, dict):
        for name, rec in rr.items():
            if isinstance(rec, dict):
                _push(str(name), _cols_from_registry(rec),
                      str(rec.get("purpose") or ""))

    # 2) flat registry.json — legacy fallback.
    fr = (s.flat_registry or {}).get("entities")
    if isinstance(fr, dict):
        for name, rec in fr.items():
            if isinstance(rec, dict):
                _push(str(name), _cols_from_registry(rec), "")

    # 3) plan.json — final fallback.
    pe = (s.plan or {}).get("entities")
    if isinstance(pe, dict):
        for name, rec in pe.items():
            if isinstance(rec, dict):
                fields = rec.get("fields") or []
                cols = [
                    {
                        "name": f.get("name") or "",
                        "type": f.get("type") or "",
                        "fk": f.get("fk") or "",
                        "notNull": bool(f.get("required") or f.get("notNull")),
                        "primaryKey": False,
                        "enum": None,
                    }
                    for f in fields if isinstance(f, dict) and f.get("name")
                ]
                _push(str(name), cols, str(rec.get("purpose") or ""))
    elif isinstance(pe, list):
        for rec in pe:
            if isinstance(rec, dict) and rec.get("name"):
                _push(str(rec["name"]), [], str(rec.get("purpose") or ""))

    dm = (s.plan or {}).get("data_models")
    if isinstance(dm, list):
        for rec in dm:
            if isinstance(rec, dict) and rec.get("name"):
                _push(str(rec["name"]), [], str(rec.get("purpose") or ""))

    return out


def _render_data_model(s: _Sources) -> str:
    entities = _extract_entities(s)
    if not entities:
        return "## Data Model\n\n_No entities on record yet._"

    lines = ["## Data Model", ""]

    # Mermaid ER diagram.
    mermaid = _render_er_diagram(entities)
    if mermaid:
        lines.append(mermaid)
        lines.append("")

    lines.append("### Entities")
    lines.append("")
    lines.append("| Entity | Columns | FKs | Purpose |")
    lines.append("|---|---|---|---|")
    for e in entities:
        cols = e["columns"] or []
        col_names = ", ".join(c["name"] for c in cols[:8] if c.get("name"))
        if len(cols) > 8:
            col_names += f" (+{len(cols) - 8} more)"
        fks = [f"{c['name']}→{c['fk']}" for c in cols if c.get("fk")]
        fk_str = ", ".join(fks) if fks else "—"
        purpose = _md_cell(e.get("purpose") or "—")
        lines.append(
            f"| **{e['name']}** | {_md_cell(col_names or '—')} | {_md_cell(fk_str)} | {purpose} |"
        )
    return "\n".join(lines)


def _render_er_diagram(entities: list[dict]) -> str:
    """Emit a Mermaid erDiagram of entities + FK relationships.

    Truncates to ~40 entities to keep the render manageable; anything
    beyond is degraded to a note beneath.
    """
    if not entities:
        return ""
    HARD_CAP = 40
    shown = entities[:HARD_CAP]
    truncated = len(entities) - len(shown)

    name_ids: dict[str, str] = {e["name"]: _mermaid_id(e["name"]) for e in shown}

    lines = ["```mermaid", "erDiagram"]
    for e in shown:
        eid = name_ids[e["name"]]
        cols = [c for c in (e["columns"] or []) if c.get("name")][:12]
        lines.append(f"    {eid} {{")
        for c in cols:
            ctype = _mermaid_type(c.get("type") or "string")
            marker = ""
            if c.get("primaryKey"):
                marker = " PK"
            elif c.get("fk"):
                marker = " FK"
            lines.append(f"        {ctype} {_mermaid_ident(c['name'])}{marker}")
        lines.append("    }")

    # Relationships from FK links, skipping targets we didn't emit.
    seen_rel: set[tuple[str, str]] = set()
    for e in shown:
        src_id = name_ids[e["name"]]
        for c in e["columns"] or []:
            fk = c.get("fk")
            if not fk:
                continue
            # FK may be a slug ("recruitment-drive"); match case-insensitive
            # against known entity names.
            target = _resolve_fk_target(fk, name_ids)
            if not target:
                continue
            key = (src_id, target)
            if key in seen_rel:
                continue
            seen_rel.add(key)
            label = _mermaid_ident(c["name"])
            lines.append(f"    {src_id} }}o--|| {target} : \"{label}\"")

    lines.append("```")
    if truncated > 0:
        lines.append("")
        lines.append(f"_+{truncated} more entities omitted for readability._")
    return "\n".join(lines)


def _resolve_fk_target(fk: str, name_ids: dict[str, str]) -> str | None:
    """FK values are inconsistent: sometimes a slug (kebab), sometimes a
    class name, sometimes plural. Try each in order."""
    if not fk:
        return None
    key = str(fk).strip()
    # Direct name match.
    if key in name_ids:
        return name_ids[key]
    # Case-insensitive.
    for name, mid in name_ids.items():
        if name.lower() == key.lower():
            return mid
    # slug → CamelCase heuristic.
    camel = "".join(part.capitalize() for part in re.split(r"[-_ ]+", key))
    for name, mid in name_ids.items():
        if name == camel or name.lower() == camel.lower():
            return mid
    return None


# --------------------------------------------------------------------------- #
# Actors & roles
# --------------------------------------------------------------------------- #

def _render_actors(s: _Sources) -> str:
    actors_raw: Any = None
    for src in (s.plan, s.discovery):
        cand = (src or {}).get("actors")
        if cand:
            actors_raw = cand
            break

    # Try resource-registry.accessModel.roles as a fallback.
    if not actors_raw:
        rr = s.resource_registry or {}
        am = rr.get("accessModel") if isinstance(rr, dict) else None
        if isinstance(am, dict):
            roles = am.get("roles") or []
            if roles:
                actors_raw = roles

    if not actors_raw:
        return ""

    lines = ["## Actors & Roles", ""]
    if isinstance(actors_raw, list):
        for a in actors_raw:
            if isinstance(a, str):
                lines.append(f"- **{a}**")
            elif isinstance(a, dict):
                name = a.get("name") or a.get("role") or a.get("id") or "?"
                perms = a.get("permissions") or a.get("capabilities") or []
                bit = f"- **{name}**"
                if isinstance(perms, list) and perms:
                    bit += " — permissions: " + ", ".join(str(p) for p in perms[:6])
                desc = a.get("description") or a.get("purpose") or ""
                if desc:
                    bit += f"  · {desc}"
                lines.append(bit)
    elif isinstance(actors_raw, dict):
        for name, rec in actors_raw.items():
            bit = f"- **{name}**"
            if isinstance(rec, dict):
                desc = rec.get("description") or rec.get("purpose")
                if desc:
                    bit += f"  · {desc}"
            lines.append(bit)

    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def _extract_pages(s: _Sources) -> list[dict]:
    """Return a stable page list from nav-flow OR navigation OR plan OR
    the schemas dir — whichever we can piece together."""
    out: list[dict] = []
    seen_routes: set[str] = set()

    def _push(route: str, title: str = "", schema_file: str = "",
              page_type: str = "", entity: str = "") -> None:
        route = str(route or "").strip()
        if not route or route in seen_routes:
            return
        seen_routes.add(route)
        out.append({
            "route": route, "title": title, "schema_file": schema_file,
            "type": page_type, "entity": entity,
        })

    # 1) nav-flow.json — richest.
    for p in (s.nav_flow or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        _push(
            route=p.get("route") or "",
            title=p.get("title") or p.get("id") or "",
            schema_file=p.get("schemaFile") or p.get("schema_path") or "",
        )

    # 2) navigation.json (editor screen graph).
    for scr in (s.navigation or {}).get("screens") or []:
        if not isinstance(scr, dict):
            continue
        data = scr.get("data") if isinstance(scr.get("data"), dict) else {}
        _push(
            route=data.get("route") or "",
            title=data.get("label") or "",
        )

    # 3) plan pages.
    for p in (s.plan or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        _push(
            route=p.get("route") or "",
            title=p.get("name") or p.get("title") or "",
            page_type=p.get("type") or "",
            entity=p.get("entity") or "",
        )

    # 4) fall back to the src/schemas/ dir contents.
    for rel, sch in (s.schemas or {}).items():
        route = sch.get("route") or f"/{rel[:-5]}" if rel.endswith(".json") else ""
        _push(
            route=route,
            title=sch.get("title") or "",
            schema_file=f"src/schemas/{rel}",
        )

    return out


def _render_pages(s: _Sources) -> str:
    pages = _extract_pages(s)
    if not pages:
        return ""

    lines = ["## Pages", ""]
    lines.append("| Route | Type | Entity | Purpose / Title |")
    lines.append("|---|---|---|---|")
    for p in pages:
        entity = p.get("entity") or _guess_entity_for_route(p, s) or "—"
        ptype = p.get("type") or _guess_type_for_route(p, s) or "—"
        title = p.get("title") or "—"
        lines.append(
            f"| `{_md_cell(p['route'])}` | {_md_cell(ptype)} "
            f"| {_md_cell(entity)} | {_md_cell(title)} |"
        )

    # Per-page detail — one subsection per schema with an outline.
    detail = _render_page_details(s)
    if detail:
        lines.append("")
        lines.append("### Page Details")
        lines.append("")
        lines.append(detail)
    return "\n".join(lines)


def _guess_entity_for_route(page: dict, s: _Sources) -> str:
    sf = page.get("schema_file") or ""
    if not sf:
        return ""
    # Look up in loaded schemas.
    rel = sf
    if rel.startswith("src/schemas/"):
        rel = rel[len("src/schemas/"):]
    sch = (s.schemas or {}).get(rel)
    if not isinstance(sch, dict):
        return ""
    for src in (sch.get("dataSources") or []):
        if isinstance(src, dict) and src.get("entity"):
            return str(src["entity"])
    return ""


def _guess_type_for_route(page: dict, s: _Sources) -> str:
    sf = page.get("schema_file") or ""
    if not sf:
        return ""
    rel = sf[len("src/schemas/"):] if sf.startswith("src/schemas/") else sf
    sch = (s.schemas or {}).get(rel)
    if not isinstance(sch, dict):
        return ""
    for k in ("kind", "pageType", "type"):
        v = sch.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _render_page_details(s: _Sources) -> str:
    """One subsection per schema — component summary, workflows fired,
    data sources. Capped to avoid rendering hundreds of pages."""
    schemas = s.schemas or {}
    if not schemas:
        return ""

    CAP = 30
    keys = list(schemas.keys())[:CAP]

    blocks: list[str] = []
    for rel in keys:
        sch = schemas[rel]
        if not isinstance(sch, dict):
            continue
        route = sch.get("route") or f"/{rel[:-5]}"
        title = sch.get("title") or sch.get("id") or rel

        # Component summary — count top-level names.
        comp_summary = _outline_components(sch)
        # Workflows dispatched (workflowId props on buttons).
        wf_dispatched = _outline_workflow_refs(sch)
        # Data sources.
        ds = sch.get("dataSources") or []
        ds_lines: list[str] = []
        if isinstance(ds, list):
            for d in ds[:6]:
                if isinstance(d, dict):
                    nm = d.get("name") or "?"
                    ent = d.get("entity") or "—"
                    op = d.get("op") or "list"
                    ds_lines.append(f"  - `{nm}` — {op} {ent}")

        block = [f"#### `{route}` — {title}"]
        if comp_summary:
            block.append("- Components: " + comp_summary)
        if ds_lines:
            block.append("- Data sources:")
            block.extend(ds_lines)
        if wf_dispatched:
            block.append("- Workflows dispatched: " + ", ".join(wf_dispatched[:8]))
        blocks.append("\n".join(block))

    if len(schemas) > CAP:
        blocks.append(f"_+{len(schemas) - CAP} more page schemas omitted._")

    return "\n\n".join(blocks)


def _outline_components(node: Any, counts: dict[str, int] | None = None) -> str:
    """Return a comma-separated top-N component counts."""
    counts = counts or {}
    _walk_count(node, counts)
    if not counts:
        return ""
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
    return ", ".join(f"{name}×{n}" if n > 1 else name for name, n in top)


def _walk_count(node: Any, counts: dict[str, int]) -> None:
    if isinstance(node, dict):
        comp = node.get("component") or node.get("kind")
        if isinstance(comp, str) and comp:
            counts[comp] = counts.get(comp, 0) + 1
        for v in node.values():
            _walk_count(v, counts)
    elif isinstance(node, list):
        for it in node:
            _walk_count(it, counts)


def _outline_workflow_refs(node: Any, refs: list[str] | None = None) -> list[str]:
    refs = refs if refs is not None else []
    if isinstance(node, dict):
        for k in ("workflowId", "workflow", "dispatchWorkflow"):
            v = node.get(k)
            if isinstance(v, str) and v and v not in refs:
                refs.append(v)
        for v in node.values():
            _outline_workflow_refs(v, refs)
    elif isinstance(node, list):
        for it in node:
            _outline_workflow_refs(it, refs)
    return refs


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #

def _render_navigation(s: _Sources) -> str:
    """Mermaid flowchart from nav-flow OR navigation edges."""
    transitions = (s.nav_flow or {}).get("transitions") or []
    pages_by_id: dict[str, dict] = {}
    for p in (s.nav_flow or {}).get("pages") or []:
        if isinstance(p, dict) and p.get("id"):
            pages_by_id[str(p["id"])] = p

    if transitions and pages_by_id:
        return _render_navflow_diagram(transitions, pages_by_id)

    # Fallback: root navigation.json edges.
    screens_by_id: dict[str, dict] = {}
    for scr in (s.navigation or {}).get("screens") or []:
        if isinstance(scr, dict) and scr.get("id"):
            screens_by_id[str(scr["id"])] = scr
    edges = (s.navigation or {}).get("edges") or []
    if screens_by_id and edges:
        return _render_screen_graph(edges, screens_by_id)

    return ""


def _render_navflow_diagram(
    transitions: list[dict], pages_by_id: dict[str, dict],
) -> str:
    """Emit a mermaid flowchart of nav-flow transitions."""
    HARD_CAP = 80
    if len(transitions) > HARD_CAP:
        note = f"\n_+{len(transitions) - HARD_CAP} more transitions omitted._"
        transitions = transitions[:HARD_CAP]
    else:
        note = ""

    lines = ["## Navigation", "", "```mermaid", "flowchart LR"]
    # Emit page nodes actually referenced.
    used_ids: set[str] = set()
    for t in transitions:
        if not isinstance(t, dict):
            continue
        used_ids.add(str(t.get("from") or ""))
        used_ids.add(str(t.get("to") or ""))
    for pid in sorted(x for x in used_ids if x):
        page = pages_by_id.get(pid) or {}
        label = page.get("title") or page.get("route") or pid
        route = page.get("route") or ""
        node_label = f"{label}<br/><small>{route}</small>" if route else label
        lines.append(f"    {_mermaid_id(pid)}[\"{_mermaid_label(node_label)}\"]")

    for t in transitions:
        if not isinstance(t, dict):
            continue
        src = str(t.get("from") or "")
        dst = str(t.get("to") or "")
        if not src or not dst:
            continue
        trig = str(t.get("trigger") or "")
        arrow = f"-->|{_mermaid_label(trig)[:40]}|" if trig else "-->"
        lines.append(f"    {_mermaid_id(src)} {arrow} {_mermaid_id(dst)}")

    lines.append("```")
    if note:
        lines.append(note)
    return "\n".join(lines)


def _render_screen_graph(edges: list[dict], screens_by_id: dict[str, dict]) -> str:
    HARD_CAP = 80
    if len(edges) > HARD_CAP:
        note = f"\n_+{len(edges) - HARD_CAP} more edges omitted._"
        edges = edges[:HARD_CAP]
    else:
        note = ""

    lines = ["## Navigation", "", "```mermaid", "flowchart LR"]
    used: set[str] = set()
    for e in edges:
        if isinstance(e, dict):
            used.add(str(e.get("source") or ""))
            used.add(str(e.get("target") or ""))
    for sid in sorted(x for x in used if x):
        scr = screens_by_id.get(sid) or {}
        data = scr.get("data") if isinstance(scr.get("data"), dict) else {}
        label = data.get("label") or sid
        route = data.get("route") or ""
        node_label = f"{label}<br/><small>{route}</small>" if route else label
        lines.append(f"    {_mermaid_id(sid)}[\"{_mermaid_label(node_label)}\"]")
    for e in edges:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source") or "")
        dst = str(e.get("target") or "")
        if not src or not dst:
            continue
        lbl = str(e.get("label") or "")
        arrow = f"-->|{_mermaid_label(lbl)[:40]}|" if lbl else "-->"
        lines.append(f"    {_mermaid_id(src)} {arrow} {_mermaid_id(dst)}")
    lines.append("```")
    if note:
        lines.append(note)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #

def _render_workflows(s: _Sources) -> str:
    workflows = s.workflows or {}
    if not workflows:
        return ""

    CAP = 20  # per-workflow diagrams; extras get a summary row only.
    ordered = sorted(workflows.items(), key=lambda kv: kv[0].lower())

    lines = ["## Workflows", ""]
    # Summary table first.
    lines.append("| Workflow | Trigger | Inputs | Steps |")
    lines.append("|---|---|---|---|")
    for name, wf in ordered:
        trig = _wf_trigger(wf)
        inputs = _wf_inputs(wf)
        steps = _wf_node_count(wf)
        lines.append(
            f"| **{_md_cell(name)}** | {_md_cell(trig)} "
            f"| {_md_cell(inputs)} | {steps} |"
        )
    lines.append("")

    # Per-workflow subsections.
    shown = ordered[:CAP]
    for name, wf in shown:
        lines.append(f"### {name}")
        desc = wf.get("description") or ""
        if desc:
            lines.append("")
            lines.append(str(desc))
        diagram = _render_workflow_diagram(wf)
        if diagram:
            lines.append("")
            lines.append(diagram)
        lines.append("")

    if len(ordered) > CAP:
        lines.append(
            f"_+{len(ordered) - CAP} more workflow diagrams omitted for brevity._"
        )
    return "\n".join(lines)


def _wf_trigger(wf: dict) -> str:
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    trig = defn.get("trigger") if isinstance(defn.get("trigger"), dict) else {}
    if isinstance(trig, dict) and trig.get("type"):
        return str(trig["type"])
    top = wf.get("trigger")
    if isinstance(top, str):
        return top
    if isinstance(top, dict) and top.get("type"):
        return str(top["type"])
    return "manual"


def _wf_inputs(wf: dict) -> str:
    pv = wf.get("processVariables")
    if isinstance(pv, list) and pv:
        names = [str(v.get("name")) for v in pv if isinstance(v, dict) and v.get("name")]
        return ", ".join(names[:8]) or "—"
    inputs = wf.get("inputs")
    if isinstance(inputs, list) and inputs:
        return ", ".join(str(i) for i in inputs[:8])
    return "—"


def _wf_node_count(wf: dict) -> int:
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    nodes = defn.get("nodes")
    if isinstance(nodes, list):
        return len(nodes)
    return 0


def _render_workflow_diagram(wf: dict) -> str:
    """One mermaid flowchart per workflow. Nodes are workflow steps,
    edges are the ``edges`` list from the definition."""
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else {}
    nodes = defn.get("nodes") if isinstance(defn.get("nodes"), list) else []
    edges = defn.get("edges") if isinstance(defn.get("edges"), list) else []
    if not nodes:
        return ""

    HARD_CAP = 40
    if len(nodes) > HARD_CAP:
        return (
            f"_Workflow has {len(nodes)} nodes — too large to diagram inline. "
            f"See its JSON file for the full graph._"
        )

    lines = ["```mermaid", "flowchart TD"]
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        if not nid:
            continue
        data = n.get("data") if isinstance(n.get("data"), dict) else {}
        label = str(data.get("label") or n.get("type") or nid)
        ntype = str(n.get("type") or "action")
        shape_open, shape_close = _mermaid_shape_for(ntype)
        lines.append(
            f"    {_mermaid_id(nid)}{shape_open}"
            f"\"{_mermaid_label(label)}\"{shape_close}"
        )

    if isinstance(edges, list) and edges:
        for e in edges:
            if not isinstance(e, dict):
                continue
            src = str(e.get("source") or e.get("from") or "")
            dst = str(e.get("target") or e.get("to") or "")
            if not src or not dst:
                continue
            lbl = str(e.get("label") or e.get("condition") or "")
            arrow = f"-->|{_mermaid_label(lbl)[:30]}|" if lbl else "-->"
            lines.append(f"    {_mermaid_id(src)} {arrow} {_mermaid_id(dst)}")
    else:
        # Straight-line fallback: connect nodes in declaration order.
        prev: str | None = None
        for n in nodes:
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or "")
            if not nid:
                continue
            if prev is not None:
                lines.append(f"    {_mermaid_id(prev)} --> {_mermaid_id(nid)}")
            prev = nid

    lines.append("```")
    return "\n".join(lines)


def _mermaid_shape_for(ntype: str) -> tuple[str, str]:
    t = ntype.lower()
    if t == "trigger":
        return ("([", "])")  # stadium
    if t == "end":
        return ("(((", ")))")  # circle-ish
    if t in ("condition", "branch", "decision"):
        return ("{", "}")  # diamond
    return ("[", "]")


# --------------------------------------------------------------------------- #
# Forms
# --------------------------------------------------------------------------- #

def _render_forms(s: _Sources) -> str:
    """Walk all page schemas, find every Form component + its fields."""
    rows: list[tuple[str, str, str, str]] = []  # (page, target, fields, kind)
    for rel, sch in (s.schemas or {}).items():
        page_route = sch.get("route") or f"/{rel[:-5]}"
        for form in _walk_forms(sch):
            props = form.get("props") or {}
            target = (
                props.get("resource")
                or props.get("entity")
                or props.get("submit", {}).get("target")
                if isinstance(props.get("submit"), dict) else props.get("resource")
                or "—"
            )
            fields = props.get("fields") or form.get("fields") or []
            field_names = []
            if isinstance(fields, list):
                for f in fields:
                    if isinstance(f, dict) and f.get("name"):
                        field_names.append(str(f["name"]))
                    elif isinstance(f, str):
                        field_names.append(f)
            kind = ""
            if isinstance(props.get("submit"), dict):
                kind = str(props["submit"].get("kind") or props["submit"].get("verb") or "")
            if not kind:
                kind = str(props.get("submitKind") or props.get("kind") or "submit")

            rows.append((
                page_route,
                str(target) if target else "—",
                ", ".join(field_names[:8]) + ("…" if len(field_names) > 8 else ""),
                kind,
            ))

    if not rows:
        return ""

    lines = ["## Forms", ""]
    lines.append("| Page | Form Target | Fields | Submit Kind |")
    lines.append("|---|---|---|---|")
    for page, target, fields, kind in rows:
        lines.append(
            f"| `{_md_cell(page)}` | {_md_cell(target)} "
            f"| {_md_cell(fields or '—')} | {_md_cell(kind or '—')} |"
        )
    return "\n".join(lines)


def _walk_forms(node: Any, out: list[dict] | None = None) -> list[dict]:
    out = out if out is not None else []
    if isinstance(node, dict):
        comp = node.get("component") or node.get("kind")
        if isinstance(comp, str) and comp.lower() == "form":
            out.append(node)
        for v in node.values():
            _walk_forms(v, out)
    elif isinstance(node, list):
        for it in node:
            _walk_forms(it, out)
    return out


# --------------------------------------------------------------------------- #
# Design
# --------------------------------------------------------------------------- #

def _render_design(s: _Sources) -> str:
    brief = s.brief or {}
    spec = s.design_spec or {}
    if not brief and not spec:
        return ""

    palette = brief.get("palette") if isinstance(brief.get("palette"), dict) else {}
    if not palette:
        palette = spec.get("colorPalette") if isinstance(spec.get("colorPalette"), dict) else {}
    typography = brief.get("typography") if isinstance(brief.get("typography"), dict) else {}
    if not typography:
        typography = spec.get("typography") if isinstance(spec.get("typography"), dict) else {}
    layout = brief.get("layout") if isinstance(brief.get("layout"), dict) else {}
    if not layout:
        layout = spec.get("layout") if isinstance(spec.get("layout"), dict) else {}
    stance = (brief.get("identity") or {}).get("visual_stance") if isinstance(brief.get("identity"), dict) else None
    if not stance:
        stance = brief.get("visual_stance") if isinstance(brief.get("visual_stance"), dict) else {}

    lines = ["## Design", ""]

    # Palette with color swatches. We can't use CSS in Markdown, but
    # GitHub renders 12x12 SVG data-URI images inline in tables.
    if palette:
        lines.append("### Palette")
        lines.append("")
        lines.append("| Role | Color |")
        lines.append("|---|---|")
        for role in ("brand", "accent", "primary", "secondary",
                     "surface_bg", "surface_elevated",
                     "foreground_primary", "foreground_muted",
                     "neutrals_base", "background", "surface",
                     "error", "warning", "success"):
            val = palette.get(role)
            if isinstance(val, str) and val.strip():
                lines.append(f"| {role} | `{val}` {_swatch(val)} |")
        lines.append("")

    if typography:
        lines.append("### Typography")
        for k in ("display_family", "body_family", "utility_family",
                  "fontFamily", "headingWeight", "bodySize", "scale"):
            v = typography.get(k)
            if v is not None and str(v):
                lines.append(f"- {k}: `{v}`")
        lines.append("")

    if layout:
        lines.append("### Layout")
        for k in ("navigation", "density", "borderRadius", "spacing",
                  "radius", "gutter"):
            v = layout.get(k)
            if v is not None and str(v):
                lines.append(f"- {k}: `{v}`")
        lines.append("")

    if isinstance(stance, dict) and stance:
        lines.append("### Visual stance")
        for k in ("hue_range", "temperature", "shape_vocab",
                  "principles", "personality"):
            v = stance.get(k)
            if v is None or v == "":
                continue
            if isinstance(v, list):
                lines.append(f"- {k}: {', '.join(str(x) for x in v)}")
            else:
                lines.append(f"- {k}: `{v}`")

    return "\n".join(lines).rstrip()


def _swatch(hex_color: str) -> str:
    """Return a tiny inline SVG data-URI swatch for the color; renders
    as a color chip alongside the hex value in GitHub-flavored Markdown."""
    h = hex_color.strip()
    if not re.match(r"^#[0-9A-Fa-f]{3,8}$", h):
        return ""
    # 14x14 square. Keep it tiny — one image per palette row.
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14'>"
        f"<rect width='14' height='14' fill='{h}' "
        f"stroke='%23888' stroke-width='0.5'/></svg>"
    )
    # base64-avoid: URL-encode a few common chars only, keep it inline-safe.
    import urllib.parse as _up
    return f"![]({'data:image/svg+xml,' + _up.quote(svg, safe='<>=/')})"


# --------------------------------------------------------------------------- #
# Content bank
# --------------------------------------------------------------------------- #

def _render_content_bank(s: _Sources) -> str:
    brief = s.brief or {}
    bank = brief.get("content_bank") if isinstance(brief.get("content_bank"), dict) else None
    if not bank:
        return ""
    lines = ["## Content Bank", ""]
    for key, label in (
        ("taglines", "Taglines"),
        ("cta_verbs", "CTA verbs"),
        ("empty_state_patterns", "Empty-state copy"),
        ("microcopy", "Microcopy"),
    ):
        vals = bank.get(key)
        if not vals:
            continue
        if isinstance(vals, list):
            lines.append(f"### {label}")
            for v in vals[:10]:
                lines.append(f"- {v}")
            lines.append("")

    if len(lines) <= 2:
        return ""
    return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------- #
# Uncovered artifacts — coverage-gate integration
# --------------------------------------------------------------------------- #

def _render_uncovered(
    s: _Sources, root: Path, *, body_so_far: str = "",
) -> str:
    """Append an ``## Uncovered Artifacts`` section when disk holds
    pages/tables/workflows/entities/routes that no other blueprint
    section references. Empty when everything is covered — an empty
    section is a positive health signal.

    ``body_so_far`` is the concatenation of the sections rendered
    before this one, used as the haystack. This makes coverage a pure
    function of the source data (no dependency on the on-disk file),
    so successive builds produce identical output and drift is stable.
    """
    try:
        from services.blueprint_coverage import (  # noqa: PLC0415
            check_coverage_from_sources,
        )
        report = check_coverage_from_sources(
            root, s, blueprint_text=body_so_far,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "blueprint_builder: coverage check failed: %r; skipping section",
            exc,
        )
        return ""
    uncov = report.get("uncovered") or {}
    total = sum(len(v) for v in uncov.values() if isinstance(v, list))
    if total <= 0:
        return ""

    lines = ["## Uncovered Artifacts", ""]
    lines.append(
        "_These artifacts exist on disk but no other blueprint section "
        "references them. A non-empty list here means the app is out of "
        "sync with its authoring surface — either the blueprint needs a "
        "rebuild or the orphan needs to be deleted / wired in._"
    )
    lines.append("")
    for key, label in (
        ("pages", "Pages"),
        ("tables", "Tables"),
        ("workflows", "Workflows"),
        ("entities", "Entities"),
        ("routes", "Routes"),
    ):
        items = uncov.get(key) or []
        if not items:
            continue
        lines.append(f"### {label} ({len(items)})")
        for it in items:
            lines.append(f"- `{_md_cell(it)}`")
        lines.append("")
    return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------- #
# Generation log
# --------------------------------------------------------------------------- #

def _render_generation_log(s: _Sources) -> str:
    log = s.change_log or []
    if not log:
        return ""
    tail = log[-5:][::-1]  # newest first
    lines = ["## Generation Log", ""]
    lines.append("| When | Source | Summary |")
    lines.append("|---|---|---|")
    for entry in tail:
        ts = _md_cell(str(entry.get("ts") or ""))
        src = _md_cell(str(entry.get("source") or ""))
        summary = _md_cell(str(entry.get("summary") or ""))
        lines.append(f"| {ts} | {src} | {summary} |")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Mermaid helpers
# --------------------------------------------------------------------------- #

_MERMAID_ID_RE = re.compile(r"[^A-Za-z0-9_]")
# Mermaid reserved words that would be parsed as syntax if used bare as
# a node id. `end` closes a subgraph in flowcharts and breaks the diagram
# outright — workflows commonly name a node `end` so this bites hard.
_MERMAID_RESERVED = frozenset({
    "end", "subgraph", "graph", "flowchart", "classDef", "class",
    "click", "style", "linkStyle", "direction", "default",
})


def _mermaid_id(raw: str) -> str:
    """Make ``raw`` a valid Mermaid identifier — alphanumeric + underscore.
    Prefixes with ``n_`` when the result would start with a digit or match
    a Mermaid reserved keyword (which would otherwise close a subgraph or
    otherwise corrupt the diagram)."""
    if not raw:
        return "n_"
    s = _MERMAID_ID_RE.sub("_", raw)
    if s and s[0].isdigit():
        s = "n_" + s
    if s in _MERMAID_RESERVED:
        s = "n_" + s
    return s or "n_"


def _mermaid_ident(raw: str) -> str:
    """Column-name-safe identifier for erDiagram bodies (no quotes)."""
    s = _MERMAID_ID_RE.sub("_", raw or "")
    return s or "field"


def _mermaid_type(raw: str) -> str:
    """Coerce a SQL type into a Mermaid ER column type (single token)."""
    if not raw:
        return "string"
    s = str(raw).strip().split("(")[0]
    s = _MERMAID_ID_RE.sub("_", s)
    return s or "string"


def _mermaid_label(raw: str) -> str:
    """Escape a label so it's safe inside "double-quoted" Mermaid text."""
    if raw is None:
        return ""
    # Mermaid doesn't handle raw quotes / backticks well; strip them.
    return str(raw).replace('"', "'").replace("`", "'").replace("\n", " ")


# --------------------------------------------------------------------------- #
# Markdown helpers
# --------------------------------------------------------------------------- #

def _md_cell(raw: Any) -> str:
    """Escape ``|`` and newlines so a value renders in a single table cell."""
    if raw is None:
        return "—"
    s = str(raw)
    return s.replace("|", "\\|").replace("\n", " ")
