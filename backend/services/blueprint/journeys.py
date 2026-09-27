"""The critical journeys of an application, read from what it declares.

"Verify only the critical journeys" was a scope with nothing behind it: the
review had no notion of a journey and read the whole application — 25 of 27
pages re-composed on a Kids Vaccination app for an ask that meant the few
paths people actually walk (aszjcc2k, 2026-09-26).

A journey here is what the Blueprint already says people come to do:

- where each role lands (`entry` pages);
- where each piece of work starts (every live workflow's `launchedFrom`);
- where that work's result is then read (the list or detail page whose
  `data.primaryEntity` is a record the workflow writes).

The third is the one that matters most. Adding a child that succeeds and a
"My Children" page that stays empty is a broken journey even when both pages
look right on their own.
"""
from __future__ import annotations

#: Page patterns on which a written record is read back.
READ_BACK_PATTERNS = frozenset({"entity_list", "master_detail", "entity_detail",
                                "approval_inbox"})

#: Workflow actions that leave a record behind.
_WRITES = frozenset({"db_insert", "db_update", "db_upsert"})


def _live(items) -> list[dict]:
    return [i for i in items or [] if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def _written_entities(workflow: dict) -> set[str]:
    out: set[str] = set()
    for step in workflow.get("steps") or []:
        config = step.get("config") or {}
        if step.get("entity") and config.get("actionType") in _WRITES:
            out.add(str(step["entity"]))
    return out


def critical_journey_pages(doc: dict) -> list[str]:
    """The page ids on the application's critical journeys, in page order."""
    pages = _live(doc.get("pages"))
    users = {str(p.get("id")): {str(u) for u in p.get("users") or []} for p in pages}
    wanted: set[str] = {str(p["id"]) for p in pages if p.get("entry") and p.get("id")}
    # (entity written, roles who wrote it) — a journey is one person's path, so
    # the admin's list of every appointment is not on the parent's booking one.
    written: list[tuple[str, set[str]]] = []
    for workflow in _live(doc.get("workflows")):
        launched = [str(pid) for pid in workflow.get("launchedFrom") or []]
        wanted.update(launched)
        by = set().union(*(users.get(pid, set()) for pid in launched)) if launched else set()
        written += [(entity, by) for entity in _written_entities(workflow)]
    for p in pages:
        primary = (p.get("data") or {}).get("primaryEntity")
        if not primary or p.get("pattern") not in READ_BACK_PATTERNS:
            continue
        readers = users.get(str(p.get("id")), set())
        if any(entity == str(primary) and (not by or not readers or by & readers)
               for entity, by in written):
            wanted.add(str(p["id"]))
    return [str(p["id"]) for p in pages if str(p.get("id")) in wanted]


def critical_journey_routes(doc: dict) -> list[str]:
    """The same pages, by route — what the review is scoped with."""
    by_id = {str(p.get("id")): p.get("route") for p in _live(doc.get("pages"))}
    return [str(by_id[pid]) for pid in critical_journey_pages(doc) if by_id.get(pid)]
