"""The asks that reach nothing, answered with the nearest thing that works.

Eight things people ask for cannot be done, and until now each of them landed
either on the verb that looked nearest — "delete the Wards page" read as a
control removal — or on "I did not recognise that as something I can do",
which is true and useless. Two of the eight stopped being limits today: undo
exists, and "build it" builds.

Each of the rest is a VERB now, so the classifier has somewhere to put it and
this module answers it: what cannot be done, why in one clause, and the
nearest thing that can — offered as sentences a click can say.

Nothing here changes anything. That is the point: an honest refusal that hands
over the next move is a better turn than a wrong change.
"""

from __future__ import annotations

from typing import Any


def _routes(doc: dict) -> list[str]:
    return [str(p.get("route")) for p in (doc or {}).get("pages") or []
            if isinstance(p, dict) and p.get("status") != "DEPRECATED" and p.get("route")]


def _page_named(doc: dict, route: str) -> dict:
    from services.smith.labels import normalise

    want = normalise(route)
    for page in (doc or {}).get("pages") or []:
        if not isinstance(page, dict) or page.get("status") == "DEPRECATED":
            continue
        if want in (normalise(page.get("route") or ""), normalise(page.get("name") or "")):
            return page
    return {}


def _entity_of(doc: dict, page: dict) -> str:
    eid = str((page.get("data") or {}).get("primaryEntity") or "")
    for ent in ((doc or {}).get("data") or {}).get("entities") or []:
        if isinstance(ent, dict) and str(ent.get("id")) == eid:
            return str(ent.get("name") or "")
    return ""


def answer(verb: str, understanding: dict, doc: dict) -> tuple[str, list[str]]:
    """What to say for a verb that cannot be done, and what to offer instead."""
    said = {k: str(understanding.get(k) or "").strip() for k in ("route", "entity", "new_value", "api")}
    field = understanding.get("field") if isinstance(understanding.get("field"), dict) else {}
    box = str(field.get("name") or "").strip()

    if verb == "remove_page":
        page = _page_named(doc, said["route"])
        name = str(page.get("name") or said["route"] or "that screen")
        record = _entity_of(doc, page)
        why = (f"I cannot remove **{name}** on its own — a screen exists "
               "because something is described as needing it, so removing it "
               "here would put it back the next time anything is built.")
        options = [f"Take {name} off the menu"]
        if record:
            options.append(f"Retire the {record} record and everything built on it")
        return why + "\n\nWhat I can do:", options

    if verb == "rename_entity":
        ent = said["entity"] or "that record"
        new = said["new_value"] or "the new name"
        return (f"I cannot rename the **{ent}** record to **{new}** everywhere — "
                "individual boxes can be renamed across the whole application, "
                "a whole kind of record cannot.\n\nThe nearest thing, and it is "
                "usually what people want: tell me the words to use, and every "
                "label a person reads changes.", [f"We say “{new}”, never “{ent}”"])

    if verb == "change_field_type":
        ent, name = said["entity"] or "that record", box or "that box"
        return (f"I cannot change what kind of value **{name}** holds after the "
                "fact — the column is already that type, and changing it in "
                "place would risk what is written in it.\n\nThe way round it is "
                "to remove it and add it again, which loses what is in that "
                f"box on every existing {ent} record.",
                [f"Remove {name} from {ent}", "Leave it as it is"])

    if verb == "edit_api":
        which = said["api"] or "that endpoint"
        return (f"I cannot edit **{which}** — endpoints are added or removed, "
                "not changed in place.\n\nRemove it and declare the one you "
                "want; nothing else refers to it by shape.",
                [f"Remove {which}", "Declare a new endpoint"])

    if verb == "reorder":
        where = said["route"] or "that screen"
        return (f"I cannot move things around on **{where}** — a composed "
                "screen is laid out as a whole, and there is nothing that "
                "nudges one block past another.\n\nWhat I can do is lay the "
                "whole screen out again, saying what should lead.",
                [f"Lay {where} out again", f"Compose {where} with the most important thing first"])

    return ("", [])


def cannot(verb: str) -> bool:
    """Whether this verb is one of the honest refusals."""
    return verb in {"remove_page", "rename_entity", "change_field_type", "edit_api", "reorder"}


__all__ = ["answer", "cannot"]
