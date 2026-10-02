"""Whose design language this application is built in — asked at the gate.

The organisation has one on record: discovered from their website when
somebody signed up, editable in Settings, shared by everyone in the company.
Most applications built there should look like the company. Not all of them —
a customer-facing storefront and an internal tool for the warehouse are the
same company and not the same design problem, and the person who knows which
is the person about to press Approve.

So it is asked, once, per application. Not assumed in either direction:
defaulting to the company's palette silently overrides a design agent that
had a reason, and defaulting away from it wastes a discovery the user
completed.

WHY HERE AND NOT IN THE CLARIFIER. The same reason `ui_designer` gives: the
clarifier's questions are worded by a model and answered in prose that becomes
part of the brief, and this answer has to reach CODE — `brand_design_system`
dispatches on it, and `brand_language.addendum` decides on it whether the
agents see design.md at all. Both the question and the recognition of its
answer are fixed text.

The approval gate is also the right moment. It is the last thing the user says
before a build, and the two nodes that consume the answer both run inside that
build. Asking earlier would be asking about an application that does not exist
yet; asking later would be asking after the palette was already chosen.

ONLY WHEN THERE IS SOMETHING TO OFFER. An organisation that skipped discovery,
or whose site could not be read, has no design language — and a two-option
question where one option is empty is not a choice, it is an obstacle in front
of a build. Those applications are never asked and never answered, which is
also why `chosen()` treats absent as `custom` everywhere.

Recorded twice, like every deterministic decision: `application.designLanguage`
is the fact code reads, and a `decisions` row is the citable record of a person
having chosen (§20). Written in one call so they cannot drift.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

COMPANY = "company"
CUSTOM = "custom"

#: The sentence that identifies the question in a transcript. `answer_in`
#: accepts an option only when the turn before it carried this.
_MARK = "Which design language should this application use?"

_DECISION_PREFIX = "The design language is"


def options(company_name: str) -> list[str]:
    """The two buttons, in the order they are shown.

    The company's own name is on the first one rather than the word
    "company": a person recognises "Northwind's design language" instantly
    and has to think about "use the organisation design language", and the
    thinking is all about what the phrase means rather than about the choice.
    """
    label = (company_name or "").strip() or "our company"
    return [f"Use {label}'s design language", "Design this app its own look"]


_GENERIC_COMPANY_ANSWERS = frozenset({
    "company", "our company", "company design language", "use our brand",
    "our brand", "the company design language", "our design language",
    "use our design language", "brand", "company brand", "same as our website",
    "use our company s design language", "use our companys design language",
})

_GENERIC_CUSTOM_ANSWERS = frozenset({
    "custom", "design this app its own look", "its own look", "own look",
    "custom design", "something custom", "design something custom",
    "a custom design", "new design", "something new", "fresh design",
})


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def chosen(doc: dict) -> str:
    """`company` / `custom` as recorded, or "" when nobody has been asked."""
    value = str(((doc or {}).get("application") or {})
                .get("designLanguage") or "").strip()
    return value if value in (COMPANY, CUSTOM) else ""


def _live(items: Any) -> list[dict]:
    return [x for x in (items or [])
            if isinstance(x, dict) and x.get("status") != "DEPRECATED"]


def undecided(doc: dict, *, available: bool) -> bool:
    """Whether approving now should ask first.

    Three conditions, all necessary: the organisation has a language to offer,
    there is a definition worth building, and nobody has answered. An empty
    document has nothing to ask about, and asking would stall an approval that
    builds nothing.
    """
    if not available:
        return False
    defined = bool(_live(doc.get("requirements")) or _live(doc.get("pages")))
    return defined and not chosen(doc)


def question(company_name: str, *, summary: str = "") -> str:
    """What Smith says at the gate.

    `summary` is one line about what was read — the palette's brand colour and
    the typeface, when there are any. It is there so the choice is concrete:
    "use our design language" is a policy, and "build it in our green, set in
    Inter" is a decision somebody can actually make.
    """
    label = (company_name or "").strip() or "your company"
    read = f" ({summary})" if summary.strip() else ""
    return (
        f"Your definition is approved. {_MARK}\n\n"
        f"• {label}'s design language{read}: the palette, type and shape "
        f"read from your website during onboarding. Use this when the "
        f"application should look like it belongs to {label}.\n"
        f"• Its own look: the design is decided from what this "
        f"application is for, as usual. Use this when it is not meant to look "
        f"like the rest of your things — a public storefront, a white-label "
        f"tool, a product with its own brand."
    )


def summary_of(design: dict | None) -> str:
    """The one-line description of a design language, or "".

    Deliberately only what a person can check at a glance. A list of eleven
    colour roles in a chat message is not something anyone reads.
    """
    colors = (design or {}).get("colors") or {}
    typography = (design or {}).get("typography") or {}
    parts = []
    if colors.get("primary"):
        parts.append(colors["primary"])
    family = typography.get("fontFamilyHeading") or typography.get("fontFamilyBase")
    if family:
        parts.append(f"set in {family}")
    return ", ".join(parts)


def is_question(text: str) -> bool:
    return _MARK in (text or "")


def answer_in(message: str, history: Iterable[tuple[str, str]],
              company_name: str = "") -> str:
    """`company` / `custom` when `message` answers the question Smith just
    asked, else "".

    The turn immediately before must be the question. A message mentioning the
    company's name in an unrelated turn is not a decision — which matters more
    here than it did for `ui_designer`, because the company's name appears in
    ordinary conversation constantly.
    """
    turns = [(str(r or "").lower(), str(t or ""))
             for r, t in history if str(t or "").strip()]
    if not turns:
        return ""
    role, text = turns[-1]
    if role not in ("smith", "assistant") or not is_question(text):
        return ""

    answer = _norm(message)
    if not answer:
        return ""
    # The exact button labels first, since that is what a click sends.
    labels = options(company_name)
    if answer == _norm(labels[0]):
        return COMPANY
    if answer == _norm(labels[1]):
        return CUSTOM
    if answer in _GENERIC_COMPANY_ANSWERS:
        return COMPANY
    if answer in _GENERIC_CUSTOM_ANSWERS:
        return CUSTOM
    # "Use Northwind's design language" typed rather than clicked.
    name = _norm(company_name)
    if name and name in answer and "design language" in answer:
        return COMPANY
    return ""


def chose_company_earlier(history: Iterable[tuple[str, str]],
                          company_name: str) -> bool:
    """Whether they already picked the company's palette from the clarifier.

    The clarifier offers the organisation's own design language as an option
    on its colour question (`clarify_brief.company_palette_option`), which is
    the first and most natural moment to ask. Somebody who took it there has
    ANSWERED this — putting the same question to them again at the approval
    gate, in different words, is the product forgetting what it was just told.

    Matched on the option string rather than on the turn before it, unlike
    `answer_in`: this is read from the whole accumulated history, long after
    the question scrolled away, and the string is specific enough
    ("Use Northwind's own palette (#1B7F5A, set in Inter)") that nobody types
    it by accident.
    """
    from services.smith.clarify_brief import company_palette_option

    # The PREFIX, not the whole option. The offered string carries a summary
    # of what was read — "(#336791, set in Open Sans)" — which this function
    # has no way to know and which a client may or may not echo back. The part
    # that names the company is the part that identifies the choice.
    bare = _norm(company_palette_option(company_name, ""))
    if not bare:
        return False
    for role, text in history or []:
        if str(role or "").lower() != "user":
            continue
        said = _norm(text)
        if said.startswith(bare):
            return True
    return False


def record(svc: Any, choice: str, *, company_name: str = "",
           reason: str = "Chosen at the approval gate.") -> str:
    """Write the choice to the application and a decision row; return what
    Smith says about it."""
    if choice not in (COMPANY, CUSTOM):
        raise ValueError(f"not a design language: {choice!r}")

    svc.doc.setdefault("application", {})["designLanguage"] = choice
    label = ((company_name or "").strip() or "the company") + "'s own" \
        if choice == COMPANY else "this application's own"
    text = f"{_DECISION_PREFIX} {label}."
    try:
        # The allocator needs the document's ids bound before a new row can be
        # keyed; the same step every other deterministic decision takes.
        from services.smith.smith import bootstrap as _bind_ids

        _bind_ids(svc)
        # A change of mind supersedes (§20, §92) rather than accumulating: the
        # earlier row is retired and the new one names it, so the history
        # reads as one decision that changed. The same answer twice is one row.
        current = _current_row(svc.doc)
        if current is None or current.get("decision") != text:
            body = {
                "decision": text,
                "reason": reason,
                "source": "user",
                "approvedBy": "user",
                "binding": True,
                "status": "APPROVED",
                "version": svc.doc.get("version", 1),
            }
            if current is not None:
                body["supersedes"] = current["id"]
                current["status"] = "DEPRECATED"
            svc.upsert("decisions", body, natural_key=f"design-language-{choice}")
    except Exception as exc:  # noqa: BLE001 — the fact is written; the citation is a courtesy
        logger.warning("[design-language] decision row not recorded: %s", exc)

    svc.validate()
    svc.save()
    if choice == COMPANY:
        name = (company_name or "").strip() or "your company"
        return (f"{name}'s design language it is — the palette, type and "
                f"shape from your site, and its voice in the copy. Building now.")
    return ("Its own look it is: the design will be decided from what this "
            "application is for. Building now.")


def _current_row(doc: dict) -> dict | None:
    """The live decision about the design language, if one was recorded."""
    for d in doc.get("decisions") or []:
        if (isinstance(d, dict) and d.get("id")
                and str(d.get("decision") or "").startswith(_DECISION_PREFIX)
                and d.get("status") != "DEPRECATED"):
            return d
    return None
