"""A person's own details can be changed: a page that shows their own record has a workflow that saves it.

Found building a ride-hailing app: the onboarding wizard and the profile page showed the driver's own record (phone,
licence, photos, bank details), and no workflow saved any of it. The forms rendered, the person filled them in, and
nothing could be written, because every change to data in a Forge app is a workflow and none was declared. It was
found by using the app, and fixed by writing two "Save my ..." workflows by hand.

THE CHECK. A page that is an onboarding, profile, settings or account page (by its pattern, route or name) and reads a
record the person owns (their account record, or an entity an ownership rule scopes to them) must be able to save it:
some workflow launched from that page writes at least one field the person may edit. A field the person may NOT edit
is one a workflow manages (a status, a rating, a count), a system field (id, timestamps), or a credential or identity
column. The finding names the fields and the shape of the workflow that fixes it, for Smith to write.

It is a refusal like the others in `functional_completeness`: the agent that wrote the workflows hears it and writes the
workflow, rather than the platform inventing one the author did not ask for.
"""
from __future__ import annotations

import re
from typing import Any

#: Pages that exist for a person to change their own details, by pattern.
_OWN_PATTERNS = frozenset({"wizard", "form", "profile", "settings", "onboarding", "account"})
#: ... or by what the route or name says.
_OWN_WORDS = re.compile(r"onboard|profile|setting|account|register|my[- ]details", re.I)
#: ... but a page that only SHOWS something about the person (a standing, a history, a summary, help) is not one where they
#: change their details.
_NOT_A_FORM = re.compile(r"status|history|earning|summary|overview|help|support|notification|log\b|list\b|report", re.I)

#: A field a person does not set about themselves, whatever the data model says: it is a system field, a credential or
#: identity column, a standing a workflow or a person in authority decides, or a figure the app computes.
_NOT_THEIRS = re.compile(
    r"^(id|createdAt|updatedAt|deletedAt|lastActiveAt|onlineSince|email|password|passwordHash|role|roles|isAdmin)$"
    r"|[sS]tatus|State$|[rR]ating|^total|Total[A-Z]|Count$|^count|[bB]alance|[sS]core$|[eE]arning|Notes?$"
    r"|[aA]pproved|[vV]erified|[sS]uspend|Reason$|currentLocation",
)


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED", "SUPERSEDED")]


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _entities(doc: dict) -> dict[str, dict]:
    """Id and name to entity."""
    out: dict[str, dict] = {}
    for e in _live((doc.get("data") or {}).get("entities")):
        out[str(e.get("id"))] = e
        out[str(e.get("name"))] = e
    return out


def own_entities(doc: dict) -> dict[str, dict]:
    """The records a person owns, by entity name: the account record, and any entity an ownership rule scopes to the
    person (`scope: user`)."""
    by = _entities(doc)
    own = {str(e.get("name")): e for e in by.values() if e.get("account") is True}
    for rule in ((doc.get("security") or {}).get("ownershipRules") or []):
        if isinstance(rule, dict) and rule.get("kind", "scope") == "scope" and rule.get("scope", "user") == "user":
            e = by.get(str(rule.get("entity") or ""))
            if e:
                own[str(e.get("name"))] = e
    return own


def _table(e: dict) -> str:
    return str(e.get("table") or "")


def _written_columns(doc: dict, wf: dict, table: str) -> set[str]:
    """The columns this workflow writes on `table`, normalised."""
    cols: set[str] = set()
    for st in wf.get("steps") or []:
        cfg = (st or {}).get("config") or {}
        if cfg.get("actionType") in ("db_update", "db_insert") and _norm(cfg.get("table")) == _norm(table):
            values = cfg.get("values") if isinstance(cfg.get("values"), dict) else {}
            cols |= {_norm(k) for k in values}
    return cols


def editable_fields(doc: dict, entity: dict) -> list[str]:
    """The fields of an owned record the person may change about themselves."""
    table = _table(entity)
    managed: set[str] = set()
    for wf in _live(doc.get("workflows")):
        launched = set(map(str, wf.get("launchedFrom") or []))
        # a workflow no screen of the person's launches (an administrator's decision, a system step) manages what it writes
        if not launched:
            managed |= _written_columns(doc, wf, table)
    out = []
    for f in entity.get("fields") or []:
        name = str(f.get("name") or "")
        if not name or _NOT_THEIRS.search(name) or str(f.get("type") or "") in ("uuid", "timestamp", "location"):
            continue
        if _norm(name) in managed:
            continue
        out.append(name)
    return out


def is_own_details_page(page: dict) -> bool:
    if str(page.get("pattern") or "").lower() in _OWN_PATTERNS:
        return True
    said = f"{page.get('route') or ''} {page.get('name') or ''}"
    return bool(_OWN_WORDS.search(said)) and not _NOT_A_FORM.search(said)


def _page_entities(doc: dict, page: dict) -> list[dict]:
    by = _entities(doc)
    data = page.get("data") if isinstance(page.get("data"), dict) else {}
    refs = [data.get("primaryEntity"), *(data.get("supportingEntities") or [])]
    out = []
    for ref in refs:
        ref = ref.get("entity") if isinstance(ref, dict) else ref
        if ref and str(ref) in by and by[str(ref)] not in out:
            out.append(by[str(ref)])
    return out


def findings(doc: dict) -> list[dict]:
    """`[{rule, page, detail}]`, one for each page of the person's own details that has no way to save them."""
    own = own_entities(doc)
    if not own:
        return []
    out: list[dict] = []
    workflows = _live(doc.get("workflows"))
    for page in _live(doc.get("pages")):
        if not is_own_details_page(page):
            continue
        pid = str(page.get("id") or "")
        for entity in _page_entities(doc, page):
            name = str(entity.get("name"))
            if name not in own:
                continue
            editable = editable_fields(doc, entity)
            if not editable:
                continue
            wanted = {_norm(f) for f in editable}
            saved = False
            for wf in workflows:
                if pid in set(map(str, wf.get("launchedFrom") or [])) and _written_columns(doc, wf, _table(entity)) & wanted:
                    saved = True
                    break
            if saved:
                continue
            shown = ", ".join(editable[:6]) + ("…" if len(editable) > 6 else "")
            out.append({
                "rule": "own-details-cannot-be-saved", "page": pid,
                "detail": (f"{page.get('route') or pid} shows the person's own {name} record, and no workflow launched from "
                           f"it saves any of what they may change ({shown}), so its form can be filled in and nothing is "
                           f"written. Add a \"Save my {name.lower()}\" workflow launched from this page: read the record by "
                           f"`$user.id`, refuse unless it is theirs, update only those fields, and keep a field left empty as it "
                           f"was with `{{{{field ?? find.field}}}}`."),
            })
    return out
