"""Post-generate guard: every link on a page must reach a page that exists.

Symptom (UAT F&B). A list row linked to ``/admin/categories/<id>`` but the
build made only ``/admin/categories`` and ``/admin/categories/new`` — menu
items DID get their ``[id]`` page. The link rendered HTTP 200 showing the 404
page, and nothing looked at it: ``nav_guard`` only reads ``navigate`` props,
``table_row_nav_guard`` only top-level pages, and neither saw a nested
``/admin/...`` list or a ``href``/``rowHref``/row action.

This reads the link targets of every component on every page schema —
``navigate``, ``href``, ``to``, ``rowHref`` (and card/item hrefs) on a node's
own props, its row actions and its empty action; never a data row — and asks
whether a page file answers it, ``[id]`` routes included (``{{item.id}}`` /
``{id}`` / ``:id`` are wildcards, but a wildcard never answers ``new`` /
``edit`` / ``create``). Files (``/logo.png``) and uploads are not pages and
are skipped. A target nothing answers is repaired, in this order:

  1. ``<list>/<id>`` where ``<list>`` is a real page over a known record type:
     the missing record page is BUILT (``build_detail_page``), its Back/Edit
     buttons pointed at real routes;
  2. otherwise a repoint, but ONLY to a concrete page of the SAME kind and
     depth (list -> list, form -> form, record -> record) — never to a
     route with a ``[param]`` or a ``(group)`` in it, never to a different
     kind of page: a link that lands somewhere else is worse than none;
  3. otherwise the link is removed and that is a WARNING naming page, link
     and target; a control left with nothing to do is named too.

Idempotent and never raises; a file it cannot read is warned about by name.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.component_nodes import components, link_items
from services.guard_io import dump_like, read_raw, write_like
from services.binding_validator import _BUTTON_TYPES, _canon

logger = logging.getLogger(__name__)

_LINK_KEYS = ("navigate", "href", "to", "rowHref", "itemHref", "cardHref")
_SINGLE_BRACE = re.compile(r"(?<!\{)\{([\w.]+)\}(?!\})")
_SKIP_FILES = {"shell.json", "nav-flow.json"}
_DYN = "<dyn>"
_CONTROLS = _BUTTON_TYPES | {"link", "navlink", "confirmdialog"}
_ACTION_WORDS = {"new", "edit", "create"}
_ASSET = re.compile(r"\.[A-Za-z0-9]{2,5}$")
_NOT_PAGES = ("/uploads/", "/static/", "/_next/", "/assets/", "/images/", "/files/", "/public/", "/api/")
#: What makes a control do something once its link is gone.
_DOES = ("navigate", "href", "to", "workflow", "clientAction", "onClick", "action", "submit", "opensDialog")


def _wild(target: str) -> str:
    """`/a/{id}` -> `/a/{{id}}` so a segment reads as dynamic."""
    return _SINGLE_BRACE.sub(r"{{\1}}", target)


def _internal(v: Any) -> bool:
    if not (isinstance(v, str) and v.startswith("/") and not v.startswith("//")):
        return False
    path = v.split("?")[0].split("#")[0]
    if path.strip("/") == "" or _ASSET.search(path.rstrip("/").rsplit("/", 1)[-1]):
        return False
    return not any(path.startswith(p) or path + "/" == p for p in _NOT_PAGES)


def _segments(route: str) -> list[str]:
    path = (route or "").split("?")[0].split("#")[0].strip().strip("/")
    out = []
    for s in path.split("/"):
        if not s or (s.startswith("(") and s.endswith(")")):
            continue                              # a route group is not in the URL
        out.append(_DYN if (s.startswith("[") or s.startswith(":") or "{{" in s) else s)
    return out


def _route_of(rel: str) -> str:
    return "/" + "/".join(s for s in rel.rsplit(".", 1)[0].split("/") if not (s.startswith("(") and s.endswith(")")))


def _matches(known: list[str], target: list[str]) -> bool:
    return len(known) == len(target) and all(
        k == t or (k == _DYN and t not in _ACTION_WORDS) for k, t in zip(known, target))


def _kind(parts: list[str]) -> str:
    if parts and parts[-1] in ("new", "create"):
        return "form"
    if parts and parts[-1] == "edit":
        return "edit"
    return "record" if parts and parts[-1] == _DYN else "list"


def _dicts(node: Any):
    """Every COMPONENT node: a dict whose `type` is a known component name,
    never entering data (a record with a `type` column is not a component)."""
    return components(node)


def _holders(node: dict):
    """(holder dict, is_row_action) whose link keys are inspected for a node."""
    yield node, False
    props = node.get("props")
    if isinstance(props, dict):
        yield props, False
        for a in props.get("rowActions") or []:
            if isinstance(a, dict):
                yield a, True
        # Link lists of known components (Breadcrumb items, nav links, tabs)
        # have no `type` of their own; they are read by the component's prop.
        for item in link_items(node):
            yield item, False
        if isinstance(props.get("emptyAction"), dict):
            yield props["emptyAction"], True


def _entity_columns(root: Path, entity: str) -> dict[str, str]:
    from services.apply_record_maquette import _load_registry, _column_type_map
    ents = _load_registry(root).get("entities")
    if not isinstance(ents, dict):
        return {}
    want = re.sub(r"[^a-z0-9]", "", entity.lower())
    for name, meta in ents.items():
        n = re.sub(r"[^a-z0-9]", "", str(name).lower())
        if isinstance(meta, dict) and (n == want or n == want + "s" or n + "s" == want):
            return _column_type_map(meta)
    return {}


def _list_entity(schema: dict) -> str | None:
    for s in schema.get("dataSources") or []:
        if isinstance(s, dict) and s.get("op") in (None, "list") and isinstance(s.get("entity"), str):
            return s["entity"]
    return None


def _build_detail(root: Path, parent: str, schema: dict, has_edit: bool) -> str | None:
    """Write `<parent>/[id]`'s page; return its route, or None if it cannot
    be built from what the app declares."""
    entity = _list_entity(schema)
    columns = _entity_columns(root, entity) if entity else {}
    if not columns:
        return None
    from services.deterministic_pages import build_detail_page
    route = parent.rstrip("/") + "/[id]"
    page = build_detail_page(entity, columns, route, design_spec=None)
    var = (page.get("dataSources") or [{}])[0].get("name") or "item"
    for d in list(_dicts(page)) + [page]:
        kids = d.get("children")
        if isinstance(kids, list):
            kept = []
            for k in kids:
                p = k.get("props") if isinstance(k, dict) else None
                if isinstance(p, dict) and p.get("label") == "Back":
                    p["navigate"] = parent
                elif isinstance(p, dict) and p.get("label") == "Edit":
                    if not has_edit:
                        continue
                    p["navigate"] = f"{parent.rstrip('/')}/{{{{{var}.id}}}}/edit"
                kept.append(k)
            d["children"] = kept
    path = root / "src" / "schemas" / (route.strip("/") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_like(str(path), None, page)
    return route


def _label(holder: dict) -> str:
    p = holder.get("props") if isinstance(holder.get("props"), dict) else {}
    return str(holder.get("label") or p.get("label") or p.get("title") or holder.get("type") or "a control")


def ensure_links_resolve(output_dir: str) -> dict:
    """Make every internal link on every page resolve to a real route.

    Returns ``{"created": [routes], "repointed": [...], "removed": [...],
    "findings": [...]}``. ``removed`` entries are ``{page, link, target}``;
    ``findings`` are what needs a person: a composer-authored link that
    reaches no page, and a control left with nothing to do
    (``{page, link, target, control}``). All are also logged as warnings.
    """
    report: dict = {"created": [], "repointed": [], "removed": [], "findings": []}
    try:
        root = Path(output_dir)
        sdir = root / "src" / "schemas"
        if not sdir.is_dir():
            return report
        from services.artifact_authority import should_assert_only_any

        pages: dict[Path, tuple[dict, str]] = {}                   # path -> (doc, raw text)
        for fp in sorted(sdir.rglob("*.json")):
            if fp.name in _SKIP_FILES:
                continue
            try:
                raw = read_raw(str(fp))
                doc = json.loads(raw)
            except (OSError, ValueError) as exc:
                logger.warning("link_target_guard: cannot read %s: %s", fp.relative_to(sdir).as_posix(), exc)
                continue
            if isinstance(doc, dict):
                pages[fp] = (doc, raw)

        # Computed once; extended only when a page is built.
        known_routes: dict[str, dict] = {}
        known_parts: list[list[str]] = []
        for fp, (doc, _) in pages.items():
            r = _route_of(fp.relative_to(sdir).as_posix())
            known_routes[r] = doc
            known_parts.append(_segments(r))
        concrete = [(r, _segments(r)) for r in known_routes if "[" not in r and "(" not in r]

        def resolves(parts: list[str]) -> bool:
            return not parts or any(_matches(k, parts) for k in known_parts)

        def same_kind_page(parts: list[str], raw_target: str) -> str | None:
            """A concrete page of the same kind and depth that the target is
            a naming drift of; None when there is no honest one."""
            sig = lambda p: {w for s in p if s != _DYN for w in (x[:-1] if len(x) > 3 and x.endswith("s") else x for x in re.split(r"[-_]", s.lower())) if w and w not in _ACTION_WORDS}
            want, best, score = sig(parts), None, 0.0
            if not want:
                return None
            for r, rp in concrete:
                if len(rp) != len(parts) or _kind(rp) != _kind(parts):
                    continue
                s = len(want & sig(rp)) / len(want | sig(rp))
                if s > score:
                    best, score = r, s
            return best if score >= 0.5 else None

        for fp in list(pages):
            doc, raw = pages[fp]
            rel = fp.relative_to(sdir).as_posix()
            dirty = False
            for node in _dicts(doc):
                for holder, is_row in _holders(node):
                    for key in _LINK_KEYS:
                        val = holder.get(key)
                        if not _internal(val):
                            continue
                        target = _wild(val)
                        parts = _segments(target)
                        if resolves(parts):
                            continue
                        parent = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
                        parent_real = next((r for r in known_routes if _segments(r) == parts[:-1]
                                            and "[" not in r and "(" not in r), None)
                        if parts[-1:] == [_DYN] and parent_real:
                            made = None
                            has_edit = resolves(parts + ["edit"])
                            try:
                                made = _build_detail(root, parent_real, known_routes[parent_real], has_edit)
                            except Exception:  # noqa: BLE001
                                logger.exception("link_target_guard: could not build %s/[id]", parent_real)
                            if made:
                                new_fp = sdir / (made.strip("/") + ".json")
                                text = read_raw(str(new_fp))
                                pages[new_fp] = (json.loads(text), text)
                                known_routes[made] = pages[new_fp][0]
                                known_parts.append(_segments(made))
                                report["created"].append(made)
                                logger.info("link_target_guard: built %s — %s links to %r "
                                            "and no page answered it", made, rel, val)
                                continue
                        if should_assert_only_any(doc):
                            report["findings"].append({"page": rel, "link": key, "target": val})
                            logger.warning("link_target_guard: %s: %s %r reaches no page (composer-"
                                           "authored, left as is)", rel, key, val)
                            continue
                        new = same_kind_page(parts, target)
                        if new:
                            holder[key] = new
                            dirty = True
                            report["repointed"].append({"page": rel, "link": key, "target": val, "to": new})
                            logger.info("link_target_guard: %s: %s %r repointed to %r", rel, key, val, new)
                            continue
                        holder.pop(key, None)
                        dirty = True
                        report["removed"].append({"page": rel, "link": key, "target": val})
                        logger.warning("link_target_guard: %s: %s %r reaches no page and none "
                                       "could be built — the link was removed; add the page or "
                                       "drop the control", rel, key, val)
                        props = node.get("props") if isinstance(node.get("props"), dict) else {}
                        control = is_row or _canon(node.get("type")) in _CONTROLS
                        still_acts = any(holder.get(k) or (not is_row and (node.get(k) or props.get(k)))
                                         for k in _DOES)
                        if control and not still_acts:
                            ctl = _label(holder if is_row else node)
                            report["findings"].append({"page": rel, "link": key, "target": val, "control": ctl})
                            logger.warning("link_target_guard: %s: %r is left with nothing to do after "
                                           "its link %r was removed — give it a page or take it off",
                                           rel, ctl, val)
            if dirty:
                new_raw = dump_like(raw, doc)
                if new_raw != raw:
                    write_like(str(fp), raw, doc)
                    pages[fp] = (doc, new_raw)
    except Exception:  # noqa: BLE001 — the guard must never crash the pipeline
        logger.exception("link_target_guard: internal error after created=%s repointed=%s removed=%s "
                         "(what was written stays written)", report["created"], len(report["repointed"]),
                         len(report["removed"]))
    return report
