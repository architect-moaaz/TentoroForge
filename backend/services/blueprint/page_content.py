"""What a page says, and where each fact comes from — the content plan.

The page contract listed what a page is FOR (tasks, actions) and never what it
SAYS. Tool Share's tool page asked the UI engineer to "review a tool's photos
and description" over a Tool entity with two columns; the engineer did what it
could and printed "Tool #a1b2…". A reference design of the same product shows
a category, a name, what comes in the box, the owner with their verification
and history, how often the tool has been lent, and what happens at handover —
and every one of those is a field, a related record, a count over a
relationship, or something a rule or a workflow means for the reader.

So the page's author (`page_details`) writes `content`: fact by fact, the
reader's question it answers and its source. Here:

* `content_findings` — every source resolves against the data model, or the
  contract is refused with the fault named (like the controls check);
* `requested_fields` / `add_requested_fields` — a fact that needs a field the
  entity does not have proposes it (`newField`), and the `content_fields`
  service node adds it BEFORE workflows are written, so the form that creates
  the record asks for it. The data model grows to serve the screen instead of
  the screen shrinking to the data;
* `content_brief` — the plan as the UI engineer reads it: each fact with the
  SDK read that produces it.
"""
from __future__ import annotations

import re
from typing import Any

#: Types a proposed field may take — what the data model already uses.
FIELD_TYPES = frozenset({
    "string", "text", "integer", "number", "decimal", "float", "boolean", "date", "datetime",
    "timestamp", "enum", "email", "phone", "url", "image", "file", "json", "location",
})


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def _entities(doc: dict) -> dict[str, dict]:
    return {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}


def _field(entity: dict, name: str) -> dict | None:
    return next((f for f in entity.get("fields") or [] if isinstance(f, dict) and f.get("name") == name), None)


def _points_elsewhere(field: dict, target_id: str) -> bool:
    """A foreign key that says it references some OTHER entity."""
    ref = field.get("references")
    return bool(ref) and str(ref) != str(target_id)


def _type_ok(t: str) -> bool:
    t = str(t or "").strip().lower()
    return t in FIELD_TYPES or (t.endswith("[]") and t[:-2] in FIELD_TYPES)


def _new_field_findings(label: str, entity: dict, name: str, new: dict) -> list[str]:
    if not new:
        return [f"{label!r}: {entity.get('name')} has no field {name!r} — propose it in "
                f"`source.newField` ({{type, description}}) and it is added to the data model"]
    if not _type_ok(new.get("type")):
        return [f"{label!r}: newField type {new.get('type')!r} is not one of {', '.join(sorted(FIELD_TYPES))}"]
    if str(new.get("type")).lower() == "enum" and not new.get("enumValues"):
        return [f"{label!r}: an enum newField lists its `enumValues`"]
    return []


def _names(entity: dict) -> str:
    return ", ".join(str(f.get("name")) for f in entity.get("fields") or [])


def _where_findings(label: str, entity: dict, src: dict) -> list[str]:
    return [f"{label!r}: `where` names {key!r}, which {entity.get('name')} does not have"
            for key in (src.get("where") or {}) if _field(entity, str(key)) is None]


def item_findings(item: dict, page: dict, doc: dict) -> list[str]:
    """Why one content item's source does not resolve, if it does not."""
    ents = _entities(doc)
    primary_id = str(((page.get("data") or {}).get("primaryEntity")) or "")
    primary = ents.get(primary_id)
    src = item.get("source") or {}
    kind = str(src.get("kind") or "")
    label = item.get("label") or "a content item"
    ent_id = str(src.get("entity") or "")
    ent = ents.get(ent_id) if ent_id else None
    out: list[str] = []

    if ent_id and ent is None:
        return [f"{label!r}: entity {ent_id} is not in the data model"]

    if kind == "field":
        target = ent or primary
        if target is None:
            return [f"{label!r}: a `field` fact needs the page's primary entity or `entity`"]
        name = str(src.get("field") or "")
        if not name:
            return [f"{label!r}: name the `field`"]
        if _field(target, name) is None:
            out.extend(_new_field_findings(label, target, name, src.get("newField") or {}))
        return out

    if kind == "related":
        if primary is None:
            return [f"{label!r}: a `related` fact needs the page's primary entity"]
        via = str(src.get("via") or "")
        fk = _field(primary, via) if via else None
        if fk is None:
            return [f"{label!r}: `via` must be a foreign key of {primary.get('name')} "
                    f"(it has: {_names(primary)}) — if the link is stored on the other record, "
                    f"use `reverse` with that record's `via`"]
        if ent is None:
            return [f"{label!r}: name the related `entity` {via} points at"]
        if _points_elsewhere(fk, ent_id):
            out.append(f"{label!r}: {primary.get('name')}.{via} references {fk.get('references')}, not {ent_id}")
        name = str(src.get("field") or "")
        if name and _field(ent, name) is None:
            out.extend(_new_field_findings(label, ent, name, src.get("newField") or {}))
        return out

    if kind == "reverse":
        if primary is None:
            return [f"{label!r}: a `reverse` fact needs the page's primary entity"]
        if ent is None:
            return [f"{label!r}: name the `entity` whose row points at the page's record"]
        via = str(src.get("via") or "")
        fk = _field(ent, via) if via else None
        if fk is None:
            return [f"{label!r}: `via` must be the field of {ent.get('name')} that points at the "
                    f"{primary.get('name')} (it has: {_names(ent)})"]
        if _points_elsewhere(fk, primary_id):
            out.append(f"{label!r}: {ent.get('name')}.{via} references {fk.get('references')}, "
                       f"not {primary.get('name')}")
        out.extend(_where_findings(label, ent, src))
        sort = str(src.get("sort") or "")
        if sort and _field(ent, sort) is None:
            out.append(f"{label!r}: `sort` names {sort!r}, which {ent.get('name')} does not have")
        shown, name = ent, str(src.get("field") or "")
        then = src.get("then") or {}
        if then:
            hop = _field(ent, str(then.get("via") or ""))
            target = ents.get(str(then.get("entity") or ""))
            if hop is None:
                return out + [f"{label!r}: `then.via` must be a foreign key of {ent.get('name')} "
                              f"(it has: {_names(ent)})"]
            if target is None:
                return out + [f"{label!r}: `then.entity` {then.get('entity')!r} is not in the data model"]
            if _points_elsewhere(hop, str(then.get("entity"))):
                out.append(f"{label!r}: {ent.get('name')}.{then.get('via')} references "
                           f"{hop.get('references')}, not {then.get('entity')}")
            shown, name = target, str(then.get("field") or "")
        if name and _field(shown, name) is None:
            out.extend(_new_field_findings(label, shown, name, src.get("newField") or {}))
        return out

    if kind in ("count", "total"):
        if ent is None:
            return [f"{label!r}: name the `entity` whose rows are counted"]
        via = str(src.get("via") or "")
        fk = _field(ent, via) if via else None
        if via and fk is None:
            return [f"{label!r}: `via` must be the field of {ent.get('name')} that points at the record "
                    f"(it has: {_names(ent)}) — or leave `via` out to count every matching row"]
        of = str(src.get("of") or "")
        if of and not via:
            out.append(f"{label!r}: `of` counts against a record through `via` — name `via` too")
        elif of:
            if primary is None or _field(primary, of) is None:
                out.append(f"{label!r}: `of` must be a foreign key of the page's record")
        elif fk is not None and primary_id and _points_elsewhere(fk, primary_id):
            out.append(f"{label!r}: {ent.get('name')}.{via} references {fk.get('references')}, not the page's "
                       f"record — use `of` to count against the record it points at")
        out.extend(_where_findings(label, ent, src))
        if kind == "total":
            if src.get("fn") not in ("sum", "avg", "min", "max"):
                out.append(f"{label!r}: a total names `fn` (sum, avg, min, max)")
            if _field(ent, str(src.get("field") or "")) is None:
                out.append(f"{label!r}: a total names the numeric `field` of {ent.get('name')}")
        return out

    if kind == "distance":
        from services.blueprint.geo_types import is_location_field
        via = str(src.get("via") or "")
        if via:
            if primary is None or _field(primary, via) is None:
                return [f"{label!r}: `via` must be a foreign key of the page's record"]
            target = ent
            if target is None:
                return [f"{label!r}: name the `entity` {via} points at"]
        else:
            target = ent or primary
        if target is None:
            return [f"{label!r}: a `distance` fact needs the page's primary entity or `entity`"]
        name = str(src.get("field") or "")
        f = _field(target, name) if name else None
        if f is None:
            new = src.get("newField") or {}
            if not name or str(new.get("type") or "").lower() != "location":
                return [f"{label!r}: {target.get('name')} has no location field {name!r} — propose it in "
                        f"`source.newField` with type `location`"]
            return []
        if not is_location_field(f):
            return [f"{label!r}: {target.get('name')}.{name} is {f.get('type')!r}, not a `location`"]
        return []

    if kind == "process":
        if not str(src.get("about") or "").strip():
            out.append(f"{label!r}: a `process` fact says what it is `about` — the rule or the step")
        return out

    return [f"{label!r}: unknown source kind {kind!r}"]


def content_findings(page: dict, doc: dict) -> list[str]:
    return [f"{page.get('route') or page.get('name')}: {e}"
            for item in page.get("content") or [] if isinstance(item, dict)
            for e in item_findings(item, page, doc)]


def drop_unresolved_content(result: Any, doc: dict) -> list[str]:
    """On the author's last attempt: keep every fact that resolves and drop the
    rest, so one bad source never costs a feature its page contracts. Returns
    what was dropped, for the log."""
    dropped: list[str] = []
    for proposal in getattr(result, "proposals", None) or []:
        if proposal.section != "pages" or not isinstance(proposal.body, dict):
            continue
        body = proposal.body
        kept = []
        for item in body.get("content") or []:
            faults = item_findings(item, body, doc) if isinstance(item, dict) else ["not an object"]
            if faults:
                dropped.extend(f"{body.get('route')}: {f}" for f in faults)
            else:
                kept.append(item)
        if "content" in body:
            body["content"] = kept
    return dropped


# ---------------------------------------------------------------------------
# Fields a page asks for
# ---------------------------------------------------------------------------

def requested_fields(doc: dict) -> dict[str, list[dict]]:
    """`{entity id: [field]}` — every `newField` a page's content proposes that
    its entity does not have yet, first proposal of a name wins."""
    ents = _entities(doc)
    out: dict[str, list[dict]] = {}
    for page in _live(doc.get("pages")):
        primary_id = str(((page.get("data") or {}).get("primaryEntity")) or "")
        for item in page.get("content") or []:
            src = (item or {}).get("source") or {}
            new = src.get("newField")
            if src.get("kind") not in ("field", "related", "reverse", "distance") or not new:
                continue
            then = src.get("then") or {}
            if src.get("kind") == "reverse" and then:
                eid, field_name = str(then.get("entity") or ""), then.get("field")
            else:
                eid = str(src.get("entity") or (primary_id if src.get("kind") != "related" and not src.get("via") else ""))
                field_name = src.get("field")
            if not field_name:
                continue
            ent = ents.get(eid)
            name = str(field_name)
            if ent is None or _field(ent, name) is not None or not _type_ok(new.get("type")):
                continue
            if any(f["name"] == name for f in out.get(eid, [])):
                continue
            field = {"name": name, "type": str(new["type"]).lower(),
                     "required": bool(new.get("required")), "sensitive": False,
                     "description": str(new.get("description") or item.get("answers") or "")}
            if new.get("enumValues"):
                field["enumValues"] = [str(v) for v in new["enumValues"]]
            out.setdefault(eid, []).append(field)
    return out


def entity_bodies_with_requested_fields(doc: dict) -> list[dict]:
    """Each entity a page asked a field of, as its whole body with the fields added."""
    ents = _entities(doc)
    bodies = []
    for eid, fields in requested_fields(doc).items():
        body = {k: v for k, v in ents[eid].items() if k not in ("status",)}
        body["fields"] = list(body.get("fields") or []) + fields
        bodies.append(body)
    return bodies


# ---------------------------------------------------------------------------
# The plan as the UI engineer reads it
# ---------------------------------------------------------------------------

def _sdk_where(src: dict, record: str) -> str:
    """The `where` of an SDK read. No `via` is every row that matches — the
    staff overview's count, which belongs to no one record."""
    pairs = []
    if src.get("via"):
        pairs.append(f"{src.get('via')}: {record}.{src['of']}" if src.get("of") else f"{src.get('via')}: {record}.id")
    pairs += [f"{k}: {v!r}" if isinstance(v, str) else f"{k}: {str(v).lower()}"
              for k, v in (src.get("where") or {}).items()]
    return "{ " + ", ".join(pairs) + " }" if pairs else ""


def _reverse_read(src: dict, ent: dict, ents: dict, record: str) -> str:
    sort = src.get("sort") or ("createdAt" if _field(ent, "createdAt") else "")
    order = f", sort: \"{sort}\", order: \"desc\"" if sort else ""
    row = f"(await list(\"{ent.get('name')}\", {{ where: {_sdk_where(src, record)}{order}, limit: 1 }}))[0]"
    then = src.get("then") or {}
    if not then:
        return f"{row}?.{src.get('field') or ent.get('labelField') or 'name'}"
    target = ents.get(str(then.get("entity") or "")) or {}
    shown = then.get("field") or target.get("labelField") or "name"
    return f"(await record(\"{target.get('name')}\", {row}?.{then.get('via')}))?.{shown}"


def content_brief(doc: dict, page: dict) -> list[dict]:
    """Each fact with the SDK read that produces it — `record` stands for the
    page's record (or, on a list, each row)."""
    ents = _entities(doc)
    primary = ents.get(str(((page.get("data") or {}).get("primaryEntity")) or "")) or {}
    rec = re.sub(r"^[A-Z]", lambda m: m.group(0).lower(), str(primary.get("name") or "record"))
    one = "[" in str(page.get("route") or "")     # a record page, not a list
    out = []
    for item in page.get("content") or []:
        if not isinstance(item, dict):
            continue
        src = item.get("source") or {}
        kind = src.get("kind")
        ent = ents.get(str(src.get("entity") or "")) or {}
        name = ent.get("name")
        if kind == "field":
            read = f"{rec}.{src.get('field')}" if not name or ent is primary else f"{name}.{src.get('field')}"
        elif kind == "related":
            shown = src.get("field") or ent.get("labelField") or "name"
            read = (f"(await record(\"{name}\", {rec}.{src.get('via')}))?.{shown}" if one else
                    f"recordsById(\"{name}\", rows.map(r => r.{src.get('via')}))[row.{src.get('via')}]?.{shown}")
        elif kind == "reverse":
            read = _reverse_read(src, ent, ents, rec if one else "row")
            if not one:
                read += " — per row; read it for the rows on screen, not the whole table"
        elif kind == "count":
            where = _sdk_where(src, rec)
            read = f"count(\"{name}\"{', ' + where if where else ''})"
        elif kind == "total":
            where = _sdk_where(src, rec)
            read = f"total(\"{name}\", \"{src.get('fn')}\", \"{src.get('field')}\"{', ' + where if where else ''})"
        elif kind == "distance":
            where = (f"(await record(\"{name}\", {rec}.{src.get('via')}))?.{src.get('field')}" if src.get("via")
                     else f"{rec}.{src.get('field')}")
            read = (f"formatDistance(distanceKm(await whereAmI(ctx), {where}))"
                    + ("" if one else f" — or rank the rows with near(\"{primary.get('name')}\", \"{src.get('field')}\", "
                                      f"await whereAmI(ctx))" if not src.get("via") else ""))
        else:
            read = f"copy about: {src.get('about')} — from the rules and workflow steps below"
        out.append({"label": item.get("label"), "answers": item.get("answers") or "",
                    "prominence": item.get("prominence") or "key", "read": read})
    return out


def process_grounding(doc: dict, page: dict) -> list[str]:
    """The rules and workflow steps a `process` fact is written from: those on
    the page's entities."""
    if not any(((i or {}).get("source") or {}).get("kind") == "process" for i in page.get("content") or []):
        return []
    data = page.get("data") or {}
    mine = {str(data.get("primaryEntity") or "")} | {str(x) for x in data.get("supportingEntities") or []}
    names = {str(e.get("name")) for eid, e in _entities(doc).items() if eid in mine}
    abouts = " ".join(str(((i or {}).get("source") or {}).get("about") or "")
                      for i in page.get("content") or [])
    stems = {w[:5].lower() for w in re.findall(r"[A-Za-z]{5,}", abouts)}

    def about_it(text: str) -> bool:
        return bool(stems & {w[:5].lower() for w in re.findall(r"[A-Za-z]{5,}", text)})

    out = []
    for r in _live(doc.get("businessRules")):
        text = " ".join(str(r.get(k) or "") for k in ("name", "statement", "description"))
        if str(r.get("entity") or "") in mine or any(n and n in text for n in names) or about_it(text):
            line = f"rule — {r.get('name')}: {r.get('statement') or r.get('description') or ''}".strip()
            # What the facts are about first, so the cap never drops it.
            out.insert(0, line) if about_it(text) else out.append(line)
    for w in _live(doc.get("workflows")):
        if str(page.get("id")) in [str(x) for x in w.get("launchedFrom") or []] or \
                str(w.get("entity") or "") in mine or about_it(f"{w.get('name')} {w.get('purpose') or ''}"):
            steps = [s.get("name") or s.get("label") for s in w.get("steps") or [] if isinstance(s, dict)]
            out.append(f"workflow — {w.get('name')}: " + " → ".join(str(s) for s in steps if s))
    return out[:12]


__all__ = ["FIELD_TYPES", "content_brief", "content_findings", "drop_unresolved_content", "entity_bodies_with_requested_fields",
           "item_findings", "process_grounding", "requested_fields"]
