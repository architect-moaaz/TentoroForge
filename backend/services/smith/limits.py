"""The asks that reach nothing, answered with the nearest thing that works.

Eight things people ask for cannot be done, and until now each of them landed
either on the verb that looked nearest — "delete the Wards page" read as a
control removal — or on "I did not recognise that as something I can do",
which is true and useless. Three of the eight have stopped being limits: undo
exists, "build it" builds, and a page can now be removed — see
`services.smith.page_change`, which took the entry below with it. The reply
this module gave it ("a screen exists because something is described as
needing it, so removing it here would put it back") was a description of the
machinery, and the owner had asked about their application.

Each of the rest is a VERB now, so the classifier has somewhere to put it and
this module answers it: what cannot be done, why in one clause, and the
nearest thing that can — offered as sentences a click can say.

Nothing here changes anything. That is the point: an honest refusal that hands
over the next move is a better turn than a wrong change.

No gate lives here any more. Smith v4 has no `cannot()` in front of the loop:
these four are ordinary verbs whose outcome is this module's answer, and §0 of
the loop spec makes each a case to close (`write_section`).
"""

from __future__ import annotations

from typing import Any


def answer(verb: str, understanding: dict, doc: dict) -> tuple[str, list[str]]:
    """What to say for a verb that cannot be done, and what to offer instead."""
    said = {k: str(understanding.get(k) or "").strip() for k in ("route", "entity", "new_value", "api")}
    field = understanding.get("field") if isinstance(understanding.get("field"), dict) else {}
    box = str(field.get("name") or "").strip()

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


__all__ = ["answer"]
