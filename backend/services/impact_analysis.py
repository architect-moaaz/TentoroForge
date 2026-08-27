"""Impact / blast-radius analysis over a generated app.

Answers "if I change X, what else needs to change?" for three target
kinds:

* ``{"entity": "Candidate", "field": "latestCvAttachmentId"}`` — every
  page that reads or writes this field, every workflow whose config
  refers to it, every api-route mapped to the entity, contracts, env
  requirements the target implies (FileUpload → ``FORGE_UPLOAD_DIR``).
* ``{"page": "candidates/new"}`` — every workflow the page's actions
  fire; every entity the page reads (via dataSources) or writes (via
  form field names).
* ``{"workflow": "process_cv"}`` — every page action that fires this
  workflow; every entity it reads or mutates via its steps.

The report is a pure function over registry.json + the on-disk file
tree — no I/O beyond reading. The orchestrator loop uses it *before*
delegating to any specialist so the change plan covers the whole
blast radius, not just the artifact the user named.

Design principle: never invent hits — every result is anchored to a
concrete file + node/step id. Empty lists mean "nothing found",
never "we didn't look".
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Iterator


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #

@dataclass
class ImpactReport:
    target: dict[str, Any]
    pages_reading:       list[dict[str, Any]] = field(default_factory=list)
    pages_writing:       list[dict[str, Any]] = field(default_factory=list)
    workflows_reading:   list[dict[str, Any]] = field(default_factory=list)
    workflows_writing:   list[dict[str, Any]] = field(default_factory=list)
    api_routes_touching: list[dict[str, Any]] = field(default_factory=list)
    contracts_impacted:  list[str]            = field(default_factory=list)
    env_requirements:    list[str]            = field(default_factory=list)
    notes:               list[str]            = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """Compact human-readable summary — Smith reads this before
        planning."""
        lines = [f"IMPACT of {self.target!r}:"]
        buckets = [
            ("pages read from",   self.pages_reading),
            ("pages write to",    self.pages_writing),
            ("workflows read",    self.workflows_reading),
            ("workflows write",   self.workflows_writing),
            ("api routes",        self.api_routes_touching),
            ("contracts",         self.contracts_impacted),
            ("env vars needed",   self.env_requirements),
        ]
        empty = True
        for label, items in buckets:
            if not items:
                continue
            empty = False
            lines.append(f"  {label} ({len(items)}):")
            for x in items[:8]:
                if isinstance(x, dict):
                    lines.append(f"    - {x.get('path') or x.get('id') or x!r}")
                else:
                    lines.append(f"    - {x}")
            if len(items) > 8:
                lines.append(f"    …and {len(items) - 8} more")
        if empty:
            lines.append("  (no dependents found — target may be unused)")
        if self.notes:
            lines.append("")
            lines.append("  notes:")
            for n in self.notes:
                lines.append(f"    - {n}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

_BINDING_RE = re.compile(r"\{\{\s*([A-Za-z_$][\w$\-\.\[\]]*)\s*\}\}")


def analyze_impact(output_dir: str, target: dict[str, Any]) -> ImpactReport:
    """Compute the blast radius of changing ``target``.

    ``target`` is one of::

        {"entity": "Candidate", "field": "latestCvAttachmentId"}   # or entity alone
        {"page":    "candidates/new"}
        {"workflow": "process_cv"}
    """
    if not isinstance(target, dict) or not target:
        return ImpactReport(target=target or {}, notes=["invalid target"])

    root = output_dir
    if not os.path.isdir(root):
        return ImpactReport(target=target, notes=[f"output_dir not found: {root}"])

    if target.get("entity"):
        return _impact_of_entity(root, target)
    if target.get("page"):
        return _impact_of_page(root, target)
    if target.get("workflow"):
        return _impact_of_workflow(root, target)
    return ImpactReport(
        target=target,
        notes=["target must contain 'entity', 'page', or 'workflow'"],
    )


# --------------------------------------------------------------------------- #
# Entity + field impact
# --------------------------------------------------------------------------- #

def _impact_of_entity(root: str, target: dict[str, Any]) -> ImpactReport:
    """Every page / workflow / api touching this entity — optionally
    narrowed to a single field."""
    entity = str(target["entity"])
    field_name = target.get("field")
    report = ImpactReport(target=target)

    # Registry-based hits.
    reg = _load_registry(root)
    entity_meta = (reg.get("entities") or {}).get(entity, {})
    if not entity_meta:
        report.notes.append(f"entity {entity!r} not in registry.json")

    # API routes for this entity.
    for key, meta in (reg.get("api_routes") or {}).items():
        if isinstance(meta, dict) and meta.get("entity") == entity:
            report.api_routes_touching.append({"route": key, "entity": entity})

    # Page schemas — the authoritative binding source.
    for path, schema in _iter_page_schemas(root):
        rel = os.path.relpath(path, root)
        page_hit_read = False
        page_hit_write = False
        # dataSources block naming this entity → page READS it.
        for ds in (schema.get("dataSources") or []):
            if isinstance(ds, dict) and ds.get("entity") == entity:
                ds_name = ds.get("name")
                if field_name is None:
                    page_hit_read = True
                    report.pages_reading.append(
                        {"path": rel, "dataSource": ds_name, "op": ds.get("op")}
                    )
        # Walk the tree — form fields naming the field → page WRITES it;
        # `{{binding.field}}` inside a display node → page READS it.
        for node_path, node in _iter_schema_nodes(schema):
            props = node.get("props") if isinstance(node, dict) else None
            if not isinstance(props, dict):
                continue
            # Form-side (writing): a Field/Input/Select/... whose `name` == field
            if field_name and props.get("name") == field_name:
                page_hit_write = True
                report.pages_writing.append({
                    "path": rel,
                    "node_type": node.get("type"),
                    "form_field": field_name,
                    "node_path": node_path,
                })
            # Display-side (reading): any `{{X.field}}` or `{{X}}` referencing
            # a dataSource whose entity == this entity.
            for _key, v in props.items():
                if not isinstance(v, str) or "{{" not in v:
                    continue
                for m in _BINDING_RE.finditer(v):
                    ref = m.group(1)
                    root_var = ref.split(".", 1)[0].split("[", 1)[0]
                    if _resolves_to_entity(root_var, schema, entity):
                        # If a field is specified, only count binding refs that
                        # mention it explicitly.
                        if field_name and field_name not in ref:
                            continue
                        page_hit_read = True
                        report.pages_reading.append({
                            "path": rel,
                            "binding": v,
                            "node_type": node.get("type"),
                        })
        # dedup by path
        # (pages_reading may have multiple entries per page — that's fine, keep granular)

    # Workflows — bindings + config.table.
    for wf_path, wf in _iter_workflows(root):
        wf_id = wf.get("id") or os.path.basename(wf_path).replace(".json", "")
        reads: list[dict[str, Any]] = []
        writes: list[dict[str, Any]] = []
        for step in _iter_workflow_steps(wf):
            step_id = step.get("id") or "?"
            cfg = (step.get("data") or {}).get("config") or step.get("config") or {}
            table = cfg.get("table") or cfg.get("entity")
            # Convert entity name → snake plural for table match.
            if table and _tables_match(table, entity, entity_meta):
                atype = (step.get("data") or {}).get("actionType") or step.get("type") or ""
                bucket = writes if "write" in atype or atype.startswith("db_") and atype != "db_query" else reads
                bucket.append({
                    "id": wf_id, "step_id": step_id, "action": atype, "table": table,
                })
            # Binding scan — any {{...field}} that names our field.
            if field_name:
                for txt in _iter_config_strings(cfg):
                    if field_name in txt and "{{" in txt:
                        reads.append({
                            "id": wf_id, "step_id": step_id,
                            "binding": txt.strip()[:160],
                        })
        report.workflows_reading.extend(reads)
        report.workflows_writing.extend(writes)

    # Contracts — action-contract.json may name the entity.
    ac_path = os.path.join(root, "contracts", "action-contract.json")
    if os.path.exists(ac_path):
        try:
            text = open(ac_path).read()
            if entity in text or (field_name and field_name in text):
                report.contracts_impacted.append("contracts/action-contract.json")
        except Exception:  # noqa: BLE001
            pass

    # Env requirements — a field named like *File* / *Cv* / *Upload* / *Attachment*
    # implies FileUpload → storage config.
    if field_name and _looks_like_file_field(field_name):
        report.env_requirements.append("FORGE_UPLOAD_DIR")
        report.notes.append(
            f"field {field_name!r} looks file-shaped — FileUpload requires "
            "FORGE_UPLOAD_DIR (or FORGE_S3_BUCKET) in .env.local"
        )

    return report


# --------------------------------------------------------------------------- #
# Page impact
# --------------------------------------------------------------------------- #

def _impact_of_page(root: str, target: dict[str, Any]) -> ImpactReport:
    page_key = str(target["page"])
    report = ImpactReport(target=target)

    schema_path = _resolve_page_path(root, page_key)
    if not schema_path or not os.path.exists(schema_path):
        report.notes.append(f"page not found: {page_key}")
        return report

    schema = _read_json(schema_path)
    if not isinstance(schema, dict):
        report.notes.append(f"page {page_key} has invalid schema")
        return report

    # Workflows this page fires (action.workflow refs).
    for _node_path, node in _iter_schema_nodes(schema):
        if not isinstance(node, dict):
            continue
        actions = (node.get("props") or {}).get("actions") or []
        if not isinstance(actions, list):
            continue
        for a in actions:
            if isinstance(a, dict) and a.get("workflow"):
                report.workflows_writing.append({
                    "id": a["workflow"],
                    "trigger": f"{page_key} · {node.get('type')}",
                })

    # Entities this page reads (via dataSources) and writes (via form fields).
    entities_read: set[str] = set()
    entities_written: set[str] = set()
    for ds in (schema.get("dataSources") or []):
        if isinstance(ds, dict) and ds.get("entity"):
            entities_read.add(ds["entity"])
    # Form field names → entity determined by dataSource name.
    for _node_path, node in _iter_schema_nodes(schema):
        if not isinstance(node, dict):
            continue
        if node.get("type") == "Form":
            # Best-effort: form's entity is inferred from dataSources.
            for ent in entities_read:
                entities_written.add(ent)

    for e in sorted(entities_read):
        report.pages_reading.append({"path": os.path.relpath(schema_path, root), "entity": e})
    for e in sorted(entities_written):
        report.pages_writing.append({"path": os.path.relpath(schema_path, root), "entity": e})

    return report


# --------------------------------------------------------------------------- #
# Workflow impact
# --------------------------------------------------------------------------- #

def _impact_of_workflow(root: str, target: dict[str, Any]) -> ImpactReport:
    wf_id = str(target["workflow"])
    report = ImpactReport(target=target)

    # Every page whose actions fire this workflow.
    for path, schema in _iter_page_schemas(root):
        rel = os.path.relpath(path, root)
        for _node_path, node in _iter_schema_nodes(schema):
            if not isinstance(node, dict):
                continue
            actions = (node.get("props") or {}).get("actions") or []
            if not isinstance(actions, list):
                continue
            for a in actions:
                if isinstance(a, dict) and a.get("workflow") == wf_id:
                    report.pages_writing.append({
                        "path": rel,
                        "trigger_node": node.get("type"),
                        "label": (a.get("label") or ""),
                    })

    # Entities the workflow reads/writes.
    wf = _find_workflow(root, wf_id)
    if wf is None:
        report.notes.append(f"workflow {wf_id!r} not found")
        return report

    for step in _iter_workflow_steps(wf):
        cfg = (step.get("data") or {}).get("config") or step.get("config") or {}
        table = cfg.get("table") or cfg.get("entity")
        if not table:
            continue
        atype = (step.get("data") or {}).get("actionType") or step.get("type") or ""
        entry = {"id": wf_id, "step_id": step.get("id"), "table": table, "action": atype}
        if "write" in atype or atype.startswith("db_") and atype != "db_query":
            report.workflows_writing.append(entry)
        else:
            report.workflows_reading.append(entry)

    return report


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _load_registry(root: str) -> dict[str, Any]:
    p = os.path.join(root, "registry.json")
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _read_json(path: str) -> Any:
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _iter_page_schemas(root: str) -> Iterator[tuple[str, dict[str, Any]]]:
    schema_root = os.path.join(root, "src", "schemas")
    if not os.path.isdir(schema_root):
        return
    for dirpath, _dirnames, filenames in os.walk(schema_root):
        for fn in filenames:
            if not fn.endswith(".json"):
                continue
            fp = os.path.join(dirpath, fn)
            data = _read_json(fp)
            if isinstance(data, dict):
                yield fp, data


def _iter_workflows(root: str) -> Iterator[tuple[str, dict[str, Any]]]:
    wf_dir = os.path.join(root, "workflows")
    if not os.path.isdir(wf_dir):
        return
    for fn in sorted(os.listdir(wf_dir)):
        if not fn.endswith(".json"):
            continue
        fp = os.path.join(wf_dir, fn)
        data = _read_json(fp)
        if isinstance(data, dict):
            yield fp, data


def _find_workflow(root: str, wf_id: str) -> dict[str, Any] | None:
    wanted = wf_id.lower().replace("_", "").replace("-", "")
    for path, data in _iter_workflows(root):
        stem = os.path.basename(path).replace(".json", "").lower().replace("_", "").replace("-", "")
        if stem == wanted or data.get("id") == wf_id:
            return data
    return None


def _iter_schema_nodes(schema: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Depth-first walk of the schema tree. Yields (path, node) for
    every node with a `type` field."""
    def walk(node: Any, path: str) -> Iterator[tuple[str, dict[str, Any]]]:
        if isinstance(node, dict):
            if "type" in node:
                yield path, node
            for k, v in node.items():
                yield from walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}[{i}]")
    root = schema.get("root")
    if isinstance(root, dict):
        yield from walk(root, "$.root")


def _iter_workflow_steps(wf: dict[str, Any]) -> Iterator[dict[str, Any]]:
    steps = wf.get("nodes") or wf.get("steps") or []
    if isinstance(steps, list):
        for s in steps:
            if isinstance(s, dict):
                yield s


def _iter_config_strings(cfg: dict[str, Any]) -> Iterator[str]:
    """Every string value anywhere inside a step's config."""
    if isinstance(cfg, dict):
        for v in cfg.values():
            yield from _iter_config_strings(v)
    elif isinstance(cfg, list):
        for v in cfg:
            yield from _iter_config_strings(v)
    elif isinstance(cfg, str):
        yield cfg


def _resolves_to_entity(root_var: str, schema: dict[str, Any], entity: str) -> bool:
    """True when a binding root token (e.g. `applicants` in
    `{{applicants[0].name}}`) resolves to a dataSource of the given
    entity in this schema."""
    for ds in (schema.get("dataSources") or []):
        if isinstance(ds, dict) and ds.get("name") == root_var and ds.get("entity") == entity:
            return True
    return False


def _tables_match(table_name: str, entity: str, entity_meta: dict[str, Any]) -> bool:
    """True when a workflow's `config.table` string names the given
    entity. Accepts snake, camel, kebab, and PascalCase forms."""
    tn = str(table_name).lower().replace("_", "").replace("-", "")
    if tn == entity.lower():
        return True
    names = entity_meta.get("names") if isinstance(entity_meta, dict) else None
    if isinstance(names, dict):
        for key in ("tableSnake", "sourceName", "routeSlug"):
            v = names.get(key)
            if isinstance(v, str) and tn == v.lower().replace("_", "").replace("-", ""):
                return True
    return False


_FILE_HINT_RE = re.compile(
    r"(cv|resume|attachment|upload|file|image|photo|avatar|logo|pdf|document)",
    re.IGNORECASE,
)


def _looks_like_file_field(field_name: str) -> bool:
    """Very light heuristic — Smith's job is to validate, not the
    analyzer's. False positives are cheap (an extra env var note);
    false negatives silently miss storage config."""
    return bool(_FILE_HINT_RE.search(field_name or ""))


def _resolve_page_path(root: str, page_key: str) -> str | None:
    """Given ``candidates/new`` or ``candidates/[id]``, resolve to the
    absolute schema path under src/schemas/."""
    stem = page_key.strip("/").rstrip(".json")
    candidate = os.path.join(root, "src", "schemas", f"{stem}.json")
    if os.path.exists(candidate):
        return candidate
    # Try common variants — some pages are indexed via a directory + .json.
    dir_json = os.path.join(root, "src", "schemas", stem + ".json")
    if os.path.exists(dir_json):
        return dir_json
    return None
