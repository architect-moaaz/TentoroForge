"""Charts and number tiles are widgets — Blueprint artifacts the editor can make.

A chart on a page is a `widgets` row: a query over an entity (measures by at
most two dimensions) and how it is drawn (`chart.mark`). The page reads it in
`load.ts` with `runWidget(widgets.key)` and draws it in `view.tsx` with
`<WidgetView>`; the typed handle in `src/sdk/widgets.ts` is generated from
the row. So adding a chart from the palette is: write the row through the
Blueprint (checked by the same rules the analytics agent obeys — a sum over
text, a bucket on a non-date, a pie with two dimensions are refused before
they exist), regenerate the SDK, then extend the page's two files. Editing a
chart edits the row; the page's code does not change unless the handle's
name does, in which case its references are renamed with it.
"""
from __future__ import annotations

import copy
import logging
import re
import uuid
from typing import Any

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, apply_agent_result
from services.blueprint.app_sdk import project_app_sdk, widget_keys, widget_query
from services.react_editor import adapter, service
from services.react_editor.service import EditorError, Project, _live, load_blueprint

logger = logging.getLogger(__name__)

MARKS = ("bar", "line", "area", "pie", "donut", "funnel", "radar", "scatter", "heatmap", "treemap", "sunburst", "graph", "map")
AGGREGATIONS = ("count", "count_distinct", "sum", "avg", "min", "max")
BUCKETS = ("day", "week", "month", "quarter", "year")
UNITS = ("number", "currency", "percent", "duration", "date", "text")
SIZES = ("sm", "md", "lg", "full")


def _entity(doc: dict, ref: str) -> dict | None:
    for e in _live((doc.get("data") or {}).get("entities")):
        if str(e.get("id")) == ref or str(e.get("name")) == ref:
            return e
    return None


def _plain(findings: list[str]) -> str:
    """The verifier's words, for a person."""
    out = []
    for f in findings:
        f = re.sub(r"measure '[^']*': ", "", f)
        f = f.replace("needs a field", "needs a field to add up")
        f = re.sub(r"'(\w+)', which is not a column on (\w+)", r"“\1”, which is not a field of \2", f)
        f = re.sub(r"'(\w+)' is not a column on (\w+)", r"“\1” is not a field of \2", f)
        f = re.sub(r"(sum|avg) over '(\w+)', which is not a number on (\w+)", r"“\2” is not a number, so it cannot be added up", f)
        f = re.sub(r"dimension '(\w+)' is bucketed by (\w+) but is not a date", r"“\1” is not a date, so it cannot be grouped by \2", f)
        f = re.sub(r"a (\w+) draws (\S+) dimension\(s\); this query has (\d+)", r"a \1 chart needs \2 thing(s) to group by; this has \3", f)
        f = re.sub(r"a (\w+) draws (\S+) measure\(s\); this query has (\d+)", r"a \1 chart shows \2 number(s); this has \3", f)
        out.append(f[0].upper() + f[1:])
    return " ".join(out)


def _validate(doc: dict, widget: dict) -> None:
    from services.blueprint.verification import _query_findings
    entity = _entity(doc, str(widget["dataSource"].get("entity")))
    if entity is None:
        raise EditorError(422, "no-entity", "Choose which kind of record the chart is about.")
    src = widget_query(doc, widget)
    findings = _query_findings(widget, src or {}, entity) if src else ["the chart's query could not be read"]
    fields = {f.get("name") for f in entity.get("fields") or []}
    for k in (widget["dataSource"].get("filter") or {}):
        if fields and k not in fields:
            findings.append(f"filters on '{k}', which is not a column on {entity.get('name')}")
    if findings:
        raise EditorError(422, "bad-widget", _plain(findings), findings=findings)


def _ref(doc: dict, w: dict, keys: dict[str, str]) -> dict:
    ents = {str(e.get("id")): e.get("name") for e in _live((doc.get("data") or {}).get("entities"))}
    src = dict(w.get("dataSource") or {})
    return {"id": str(w.get("id")), "key": keys.get(str(w.get("id"))), "page": str(w.get("page") or ""),
            "label": w.get("label") or "", "description": w.get("description") or "", "kind": w.get("kind") or "metric",
            "unit": w.get("unit") or "number", "size": w.get("size"), "chart": w.get("chart"), "order": w.get("order"),
            "source": {**src, "entity": ents.get(str(src.get("entity")), src.get("entity"))}}


def refs(doc: dict) -> list[dict]:
    keys = widget_keys(doc)
    return [_ref(doc, w, keys) for w in _live(doc.get("widgets"))]


def _from_spec(doc: dict, page_id: str, spec: dict[str, Any], base: dict | None = None) -> dict:
    """A widget row from what the person chose; ``base`` is the row being changed."""
    w: dict[str, Any] = copy.deepcopy(base) if base else {"page": page_id, "kind": "chart", "unit": "number", "size": "md"}
    if "label" in spec:
        label = str(spec.get("label") or "").strip()
        if not label:
            raise EditorError(422, "no-label", "Give the chart a title.")
        w["label"] = label
    if "description" in spec:
        w["description"] = str(spec.get("description") or "")
    if "kind" in spec:
        if spec["kind"] not in ("chart", "metric", "gauge"):
            raise EditorError(422, "bad-kind", "A widget is a chart, a number tile or a gauge.")
        w["kind"] = spec["kind"]
    if "unit" in spec and spec["unit"] in UNITS:
        w["unit"] = spec["unit"]
    if "size" in spec and spec["size"] in SIZES:
        w["size"] = spec["size"]
    src = dict(w.get("dataSource") or {"op": "query", "filter": {}})
    src["op"] = "query"
    if "entity" in spec:
        ent = _entity(doc, str(spec.get("entity") or ""))
        if ent is None:
            raise EditorError(422, "no-entity", "Choose which kind of record the chart is about.")
        src["entity"] = str(ent.get("id"))
    if "measures" in spec:
        measures = []
        for i, m in enumerate(spec.get("measures") or []):
            agg = str(m.get("aggregation") or "count")
            if agg not in AGGREGATIONS:
                raise EditorError(422, "bad-measure", f"“{agg}” is not a way of adding things up.")
            key = str(m.get("key") or ("count" if agg == "count" else f"{agg}_{m.get('field') or i}"))
            key = re.sub(r"\W+", "_", key) or f"m{i}"
            row = {"key": key, "aggregation": agg}
            if m.get("field") and agg != "count":
                row["field"] = str(m["field"])
            if m.get("label"):
                row["label"] = str(m["label"])
            measures.append(row)
        if not measures:
            raise EditorError(422, "no-measure", "Choose what the chart should count or add up.")
        src["measures"] = measures
    if "dimensions" in spec:
        dims = []
        for d in spec.get("dimensions") or []:
            if not d.get("field"):
                continue
            row = {"field": str(d["field"])}
            if d.get("bucket") in BUCKETS:
                row["bucket"] = d["bucket"]
            if d.get("ranges"):
                row["ranges"] = [{k: r[k] for k in ("label", "from", "to") if r.get(k) not in (None, "")}
                                 for r in d["ranges"] if isinstance(r, dict)]
            dims.append(row)
        if len(dims) > 2:
            raise EditorError(422, "too-many-dimensions", "A chart can group by at most two things.")
        src["dimensions"] = dims
    if "filter" in spec:
        filt: dict[str, Any] = {}
        for k, v in (spec.get("filter") or {}).items():
            if v in (None, "", []):
                continue
            filt[str(k)] = [str(x) for x in v] if isinstance(v, list) else v
        src["filter"] = filt
    for k in ("timeField", "sort", "limit"):
        if k in spec:
            if spec[k] in (None, "", {}):
                src.pop(k, None)
            else:
                src[k] = spec[k]
    if "limit" in src:
        try:
            src["limit"] = max(1, min(1000, int(src["limit"])))
        except (TypeError, ValueError):
            src.pop("limit")
    w["dataSource"] = src
    if w.get("kind") == "chart":
        chart = dict(w.get("chart") or {})
        if "mark" in spec:
            if spec["mark"] not in MARKS:
                raise EditorError(422, "bad-mark", "Choose a kind of chart: bar, line, area, pie…")
            chart["mark"] = spec["mark"]
        for k in ("stacked", "horizontal"):
            if k in spec:
                if spec[k]:
                    chart[k] = True
                else:
                    chart.pop(k, None)
        chart.setdefault("mark", "bar")
        w["chart"] = chart
    else:
        w.pop("chart", None)
    return w


def _write_new(svc: Any, widget: dict, label: str) -> dict:
    result = AgentResult(task_id=f"TASK-editor-widget-{uuid.uuid4().hex[:8]}", agent="analytics", confidence=1.0,
                         proposals=[ArtifactProposal(section="widgets", natural_key=f"editor:{uuid.uuid4().hex}", body=widget)])
    applied = apply_agent_result(svc, result, commit=True, user_request=label)
    if not applied.applied or not applied.artifacts:
        raise EditorError(422, "refused", applied.reason or "The chart could not be added to the application.")
    wid = applied.artifacts[0]
    return next(w for w in svc.doc.get("widgets") or [] if str(w.get("id")) == str(wid))


def create(project: Project, page_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """A new widget on the page, its SDK handle regenerated: ``{widget}``."""
    svc = load_blueprint(project)
    doc = svc.doc
    service._page(doc, page_id)
    widget = _from_spec(doc, page_id, spec)
    orders = [int(w.get("order") or 0) for w in _live(doc.get("widgets")) if str(w.get("page")) == page_id]
    widget["order"] = (max(orders) + 1) if orders else 1
    _validate(doc, widget)
    with svc.lock:
        row = _write_new(svc, widget, f"Add {widget.get('kind')} “{widget.get('label')}”")
        project_app_sdk(svc.doc, project.app_root)
    return {"widget": _ref(svc.doc, row, widget_keys(svc.doc))}


def update(project: Project, widget_id: str, spec: dict[str, Any], *, page_revision: str | None = None) -> dict[str, Any]:
    """Change a widget; when its handle's name changes, the page's references follow."""
    svc = load_blueprint(project)
    doc = svc.doc
    row = next((w for w in _live(doc.get("widgets")) if str(w.get("id")) == widget_id), None)
    if row is None:
        raise EditorError(404, "no-widget", "That chart is not part of this application any more.")
    old_key = widget_keys(doc).get(widget_id)
    changed = _from_spec(doc, str(row.get("page")), spec, base=row)
    for k in ("id", "status", "requirements", "decisions", "confidence", "syncNote", "order"):
        if k in row:
            changed[k] = row[k]
    _validate(doc, changed)
    with svc.lock:
        before = svc.snapshot()
        row.clear()
        row.update(changed)
        svc.commit(user_request=f"Change “{changed.get('label')}”", before=before, affected=[widget_id])
        project_app_sdk(svc.doc, project.app_root)
        new_key = widget_keys(svc.doc).get(widget_id)
        renamed = None
        if old_key and new_key and old_key != new_key:
            renamed = _rename_references(project, svc, str(row.get("page")), old_key, new_key, page_revision)
    return {"widget": _ref(svc.doc, row, widget_keys(svc.doc)), "renamed": renamed}


def _rename_references(project: Project, svc: Any, page_id: str, old: str, new: str, expected: str | None) -> dict | None:
    """`widgets.old` → `widgets.new` in the page's two files, as one checked revision."""
    prow = service._row(svc.doc, page_id)
    if prow is None:
        return None
    pat = re.compile(r"\bwidgets\." + re.escape(old) + r"\b")
    view, load = str(prow.get("view") or ""), str(prow.get("load") or "")
    if not pat.search(view) and not pat.search(load):
        return None
    current = adapter.revision_of(view, load)
    if expected and expected != current:
        raise EditorError(409, "stale", "The page changed since you loaded it — reload before renaming this chart.", current=current)
    out = service.apply(project, page_id, base_revision=current, ops=[],
                        source={"view": pat.sub(f"widgets.{new}", view), "load": pat.sub(f"widgets.{new}", load)},
                        label=f"Rename chart handle to {new}", kind="edit")
    return {"from": old, "to": new, "revision": out["revision"]}


def remove(project: Project, widget_id: str) -> dict[str, Any]:
    """Retire the widget (DEPRECATED, never deleted — §22) and drop its handle."""
    svc = load_blueprint(project)
    row = next((w for w in _live(svc.doc.get("widgets")) if str(w.get("id")) == widget_id), None)
    if row is None:
        return {"removed": False}
    with svc.lock:
        before = svc.snapshot()
        svc.set_status(widget_id, "DEPRECATED", note="Removed in the editor")
        svc.commit(user_request=f"Remove “{row.get('label')}”", before=before, affected=[widget_id])
        project_app_sdk(svc.doc, project.app_root)
    return {"removed": True}
