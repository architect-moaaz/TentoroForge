"""Structured deliverable-progress events for the generation UI.

The pipeline already streams coarse `status`/`log` events. These helpers add a
`resource` event carrying a compact, structured summary of each concrete
deliverable (a data model, a workflow, a page, a binding) so the frontend can
render a live "deliverables tracker" + Claude-Code-style preview cards without
fetching or parsing whole files.

Event shape (fed to sse_helpers.sse_event("resource", ...)):
    {
      "kind":  "data_model" | "workflow" | "page" | "binding",
      "name":  "Appointment",
      "state": "planning" | "in_progress" | "done",
      "index": 3, "total": 5,          # optional — drives "3/5"
      "summary": "9 fields · FK: patient, dentist",   # one-line preview
      "detail": {...},                  # optional small structured extra
    }

All readers are best-effort and I/O-safe: a missing dir / unparseable file
yields nothing rather than raising, so progress reporting never breaks a build.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Iterator


def resource_event(
    kind: str,
    name: str,
    state: str = "done",
    *,
    index: int | None = None,
    total: int | None = None,
    summary: str = "",
    detail: dict | None = None,
) -> dict:
    """Build a `resource` event payload for sse_event("resource", <payload>)."""
    evt: dict[str, Any] = {"kind": kind, "name": name, "state": state}
    if index is not None:
        evt["index"] = index
    if total is not None:
        evt["total"] = total
    if summary:
        evt["summary"] = summary
    if detail:
        evt["detail"] = detail
    return evt


# ---------------------------------------------------------------------------
# Summarizers — turn a raw artifact into a one-line preview string
# ---------------------------------------------------------------------------

def _fk_fields(fields: list[dict]) -> list[str]:
    out = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        n = str(f.get("name") or "")
        if f.get("references") or f.get("foreignKey") or re.search(r"[_A-Za-z]Id$", n):
            base = re.sub(r"Id$", "", n)
            if base:
                out.append(base)
    return out


def summarize_entity(entity: dict) -> str:
    """`9 fields · FK: patient, dentist` from a registry/schema entity def."""
    fields = entity.get("fields") or entity.get("columns") or []
    if isinstance(fields, dict):
        fields = [{"name": k, **(v if isinstance(v, dict) else {})} for k, v in fields.items()]
    n = len(fields)
    fks = _fk_fields(fields)
    parts = [f"{n} field{'s' if n != 1 else ''}"]
    if fks:
        parts.append("FK: " + ", ".join(fks[:3]))
    return " · ".join(parts)


def summarize_workflow(wf: dict) -> str:
    """`trigger: status change · 11 steps` from a workflow definition."""
    defn = wf.get("definition") or {}
    nodes = defn.get("nodes") or []
    steps = sum(1 for n in nodes if isinstance(n, dict) and n.get("type") not in ("trigger", "end"))
    trig = (defn.get("trigger") or {})
    tname = trig.get("event") or trig.get("type") or "manual"
    tname = str(tname).replace("_", " ")
    return f"trigger: {tname} · {steps} step{'s' if steps != 1 else ''}"


def _count_nodes(schema: dict) -> int:
    n = 0
    stack = [schema.get("root") or schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("type"):
                n += 1
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    return n


def summarize_page(schema: dict) -> str:
    """`Table · Form · 24 nodes` — the notable component types + node count."""
    types: list[str] = []
    seen: set[str] = set()
    NOTABLE = {"Table", "DataGrid", "Form", "Calendar", "Kanban", "Chart",
               "Timeline", "ResourceTimeline", "InspectorPanel", "MetricTile",
               "ApprovalStepper", "DescriptionList"}
    stack = [schema.get("root") or schema]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            t = cur.get("type")
            if t in NOTABLE and t not in seen:
                seen.add(t)
                types.append(t)
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
        elif isinstance(cur, list):
            stack.extend(cur)
    n = _count_nodes(schema)
    head = " · ".join(types[:3]) if types else "content"
    return f"{head} · {n} nodes"


# ---------------------------------------------------------------------------
# Readers — enumerate deliverables of a kind from the output dir
# ---------------------------------------------------------------------------

def iter_entities(output_dir: str) -> Iterator[dict]:
    """Yield resource events for each data-model entity in registry.json."""
    reg_path = os.path.join(output_dir, "registry.json")
    try:
        with open(reg_path, encoding="utf-8") as fh:
            reg = json.load(fh)
    except Exception:
        return
    ents = reg.get("entities") or {}
    items = list(ents.items())
    total = len(items)
    for i, (name, ent) in enumerate(items):
        ent = ent if isinstance(ent, dict) else {}
        yield resource_event("data_model", name, "done", index=i + 1, total=total,
                             summary=summarize_entity(ent))


def iter_workflows(output_dir: str) -> Iterator[dict]:
    """Yield resource events for domain workflows first, then a rollup for CRUD."""
    wdir = os.path.join(output_dir, "workflows")
    if not os.path.isdir(wdir):
        return
    domain: list[tuple[str, dict]] = []
    crud = 0
    for fp in sorted(glob.glob(os.path.join(wdir, "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                wf = json.load(fh)
        except Exception:
            continue
        name = wf.get("name") or wf.get("id")
        if not name:
            continue
        if re.match(r"^(Create|Update|Delete)[A-Z]", str(name)):
            crud += 1
        else:
            domain.append((str(name), wf))
    total = len(domain) + (1 if crud else 0)
    idx = 0
    for name, wf in domain:
        idx += 1
        yield resource_event("workflow", name, "done", index=idx, total=total,
                             summary=summarize_workflow(wf))
    if crud:
        idx += 1
        yield resource_event("workflow", f"{crud} CRUD workflows", "done",
                             index=idx, total=total,
                             summary="Create / Update / Delete per entity")


def iter_pages(output_dir: str) -> Iterator[dict]:
    """Yield resource events for each generated page schema."""
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return
    files = [f for f in sorted(glob.glob(os.path.join(sdir, "*.json")))
             if os.path.basename(f) not in ("shell.json", "nav-flow.json")]
    total = len(files)
    for i, fp in enumerate(files):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:
            continue
        route = schema.get("route") or ("/" + os.path.basename(fp)[:-5])
        yield resource_event("page", route, "done", index=i + 1, total=total,
                             summary=summarize_page(schema))
