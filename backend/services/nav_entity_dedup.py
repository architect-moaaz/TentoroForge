"""One destination per entity, named the way a person would name it.

The app-completeness rule says every entity must be reachable. On opmk18qr it
was satisfied literally: three pages were appended whose titles were the raw
table identifiers — ``employees`` at /employees, ``managers`` at /managers,
``hr_admins`` at /hr-admins — even though ``/admin/employees`` already reached
Employees under a proper label. The sidebar then showed the plumbing next to
the product: *employees* above *Employees*.

Two separate mistakes are folded into that, and this module unpicks both:

* **Coverage was measured as route equality.** The shell merge deduped by
  route, so /employees and /admin/employees read as different destinations.
  What the completeness rule actually means is "some page lists this entity",
  which is a question about the entity, not the URL.
* **A label was never written.** A page invented to satisfy a gate still gets
  read by a person, so an identifier that leaks into the menu is a defect even
  when it is the only route to the entity.

What it deliberately will NOT do is drop a page that is the only way in. A
stranded entity is the failure the completeness rule exists to prevent, and
trading it for a tidier menu would be a worse app. Those pages get a written
label instead.
"""

from __future__ import annotations

import re
from typing import Any

# Initialisms that look wrong in Title Case. Small and explicit: a general
# "short words are acronyms" rule turns `hr` into HR but also `id` into ID
# inside labels where it reads worse than the alternative.
_INITIALISMS = {"hr", "id", "url", "api", "sku", "pto", "kpi", "faq"}

_TITLED_WORD = re.compile(r"^[A-Z][a-z]")


def is_raw_entity_label(label: str) -> bool:
    """True when this reads as a table identifier rather than a written name."""
    s = (label or "").strip()
    if not s:
        return False
    if "_" in s:
        return True            # snake_case is never a written label
    if " " in s:
        return False           # a phrase was authored by someone
    return not _TITLED_WORD.match(s)   # bare lowercase token


def humanize_entity_label(label: str) -> str:
    words = re.split(r"[_\s]+", (label or "").strip())
    out = []
    for w in words:
        if not w:
            continue
        out.append(w.upper() if w.lower() in _INITIALISMS else w[:1].upper() + w[1:])
    return " ".join(out)


def _entity_of(route: str) -> str | None:
    """The entity a LIST route serves. Detail/create routes serve a record,
    not the collection, so they never count as covering the entity."""
    segs = [s for s in (route or "").split("/") if s]
    if not segs:
        return None
    last = segs[-1]
    if last.startswith("[") or last in {"new", "edit"}:
        return None
    return last.replace("_", "-").lower()


def reconcile_entity_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Drop table-speak pages an authored page already covers; name the rest.

    Mutates `pages` in place. Idempotent — after one run nothing is table-speak
    and nothing is a duplicate, so a second run reports zero.
    """
    notes: list[str] = []
    dropped = renamed = 0

    def label_of(p: dict) -> str:
        return str(p.get("name") or p.get("title") or "")

    # Entities already covered by a page somebody actually authored.
    authored: dict[str, str] = {}
    for p in pages:
        if is_raw_entity_label(label_of(p)):
            continue
        ent = _entity_of(str(p.get("route") or ""))
        if ent:
            authored.setdefault(ent, str(p.get("route")))

    survivors: list[dict] = []
    for p in pages:
        label = label_of(p)
        if not is_raw_entity_label(label):
            survivors.append(p)
            continue
        ent = _entity_of(str(p.get("route") or ""))
        covered_by = authored.get(ent) if ent else None
        if covered_by:
            dropped += 1
            notes.append(f"dropped {p.get('route')!r} ({label!r}) — "
                         f"{covered_by!r} already covers {ent}")
            continue
        # Only way in: keep it, but give it a name a person would use.
        better = humanize_entity_label(label)
        if better != label:
            if "name" in p:
                p["name"] = better
            if "title" in p:
                p["title"] = better
            if "name" not in p and "title" not in p:
                p["name"] = better
            renamed += 1
            notes.append(f"renamed {p.get('route')!r}: {label!r} -> {better!r}")
        survivors.append(p)

    pages[:] = survivors
    return {"dropped": dropped, "renamed": renamed, "notes": notes}


def reconcile_nav_flow(nav_flow_path: str) -> dict[str, Any]:
    """Apply the same rule to a generated app's nav-flow.json.

    One difference from the plan-level pass: a duplicate is demoted out of the
    menu (``shell: false``) rather than deleted. The route and its schema
    already exist on disk and may be linked from elsewhere; the defect is that
    it appears in the sidebar next to the page it duplicates, so that — and
    only that — is what gets removed.
    """
    import json
    from pathlib import Path

    p = Path(nav_flow_path)
    if not p.exists():
        return {"dropped": 0, "renamed": 0, "notes": []}
    try:
        nf = json.loads(p.read_text())
    except Exception:  # noqa: BLE001 — a malformed contract is not our business
        return {"dropped": 0, "renamed": 0, "notes": []}

    pages = nf.get("pages")
    if not isinstance(pages, list):
        return {"dropped": 0, "renamed": 0, "notes": []}

    shelved = [p_ for p_ in pages if p_.get("shell")]
    before = {id(p_): p_.get("title") for p_ in shelved}
    kept = list(shelved)
    report = reconcile_entity_pages(kept)

    survivors = {id(p_) for p_ in kept}
    for p_ in shelved:
        if id(p_) not in survivors:
            p_["shell"] = False          # out of the menu, still routable

    if report["dropped"] or report["renamed"]:
        p.write_text(json.dumps(nf, indent=2))
    # `renamed` counts titles rewritten in place; before/after kept for clarity
    _ = before
    return report
