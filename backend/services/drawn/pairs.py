"""One screen drawn twice: for a phone and for a desktop.

A design that draws a product's app and its web version draws the same
screens at both sizes — the candidate's job search at 393 pixels in one
section ("M-J1 · Jobs — Search") and at 1440 in another ("CW-02 · Jobs —
search & results"). Built as they are, every such screen became two pages,
wired twice and free to drift apart. They are one page: it shows the phone
drawing on a phone and the desktop drawing elsewhere, on the same records and
the same processes (`binder`).

Which drawings are the same screen is a judgement — the names do not line up,
the codes are the designer's own — so it is asked once, of a model that sees
what each drawing is and shows, and kept as `drawnPairs`. The answer can only
name frames that exist (the schema lists them), each at most once.

A phone drawing with no desktop twin (a push notification, a bottom sheet) is
not paired and stays a screen of its own.
"""
from __future__ import annotations

import json
from typing import Any

#: Narrower than this is drawn for a phone…
PHONE_MAX = 600
#: …and at least this wide for a desktop.
WIDE_MIN = 900
#: Phone drawings asked about in one call. All 194 of DITANS's in one answer
#: spent 32,000 tokens reasoning and wrote nothing, then, given 64,000, was cut
#: off 70,000 characters in (2026-10-30); a batch is a short answer.
BATCH = 30


def _frames(doc: dict) -> list[dict]:
    from services.drawn.convert import _spec_frames
    from services.figma.store import frame_ref

    views = {str(v.get("key")): v for v in doc.get("drawnViews") or []
             if isinstance(v, dict) and v.get("kind") == "screen" and v.get("status") != "DEPRECATED"}
    out = []
    for source, frame in _spec_frames(doc):
        ref = frame_ref(str(source.get("id") or ""), str(frame["nodeId"]))
        try:
            width = float(frame.get("width") or 0)
        except (TypeError, ValueError):
            width = 0.0
        view = views.get(ref) or {}
        contract = view.get("contract") or {}
        out.append({"ref": ref, "name": str(frame.get("name") or ""), "shows": str(frame.get("shows") or ""),
                    "portal": str(frame.get("portal") or ""), "group": str(frame.get("group") or ""),
                    "width": width,
                    "data": [str(s.get("label") or s.get("name")) for s in contract.get("data") or []
                             if isinstance(s, dict)][:8],
                    "actions": [str(a.get("label") or a.get("name")) for a in contract.get("actions") or []
                                if isinstance(a, dict)][:8]})
    return out


def candidates(doc: dict) -> tuple[list[dict], list[dict]]:
    """``(phone drawings, desktop drawings)`` of the design held as the
    specification. Nothing to pair unless it draws both."""
    frames = _frames(doc)
    phones = [f for f in frames if 0 < f["width"] < PHONE_MAX]
    wides = [f for f in frames if f["width"] >= WIDE_MIN]
    return (phones, wides) if phones and wides else ([], [])


SYSTEM = (
    "You decide which drawings of a design are the same screen drawn twice — once for a phone and once for a "
    "desktop — so each pair is built as one page that shows the phone drawing on a phone and the desktop "
    "drawing elsewhere, on the same data.\n\n"
    "Two drawings are the same screen when a person does the same job on them with the same information: the "
    "job search and the job search; an offer with its decision and an offer with its decision. The names will "
    "not match — each section has its own codes — so judge by what each drawing is called, what it shows and "
    "what can be pressed on it. A dialog, sheet or step drawn for the phone pairs with the same dialog, drawer "
    "or step drawn for the desktop. Different jobs are not a pair because they look alike, and a drawing with "
    "no twin is left unpaired: a phone screen that only exists on a phone (a push notification, a camera "
    "sheet) stays a screen of its own. Pair each drawing at most once."
)


def _line(f: dict) -> str:
    bits = [f"`{f['ref']}` {f['name']}"]
    if f["shows"] and f["shows"] != f["name"]:
        bits.append(f"shows “{f['shows']}”")
    if f["group"]:
        bits.append(f"in {f['group']}")
    if f["data"]:
        bits.append("data: " + ", ".join(f["data"]))
    if f["actions"]:
        bits.append("actions: " + ", ".join(f["actions"]))
    return "- " + " · ".join(bits)


def user_prompt(phones: list[dict], wides: list[dict], *, feedback: str = "") -> str:
    out = [f"PHONE DRAWINGS ({len(phones)}):\n" + "\n".join(_line(f) for f in phones),
           f"DESKTOP DRAWINGS ({len(wides)}):\n" + "\n".join(_line(f) for f in wides),
           "Return every pair you find for these phone drawings: the phone drawing, its desktop twin, and in at "
           "most eight words what makes them the same screen."]
    if feedback:
        out.append("Your previous answer was refused:\n" + feedback)
    return "\n\n".join(out)


def schema(phones: list[dict], wides: list[dict]) -> dict[str, Any]:
    """The answer can only name drawings that exist, phone to desktop."""
    return {
        "type": "object", "additionalProperties": False, "required": ["pairs"],
        "properties": {"pairs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["phone", "wide", "because"],
            "properties": {"phone": {"type": "string", "enum": [f["ref"] for f in phones]},
                           "wide": {"type": "string", "enum": [f["ref"] for f in wides]},
                           "because": {"type": "string"}}}}},
    }


def settle(raw: list[dict], phones: list[dict], wides: list[dict]) -> tuple[list[dict], list[str]]:
    """The pairs, each drawing in one at most: ``(pairs, what was left out)``."""
    ok_phone = {f["ref"] for f in phones}
    ok_wide = {f["ref"] for f in wides}
    used_phone: set[str] = set()
    used_wide: set[str] = set()
    pairs, left = [], []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        phone, wide = str(item.get("phone") or ""), str(item.get("wide") or "")
        if phone not in ok_phone or wide not in ok_wide:
            left.append(f"{phone} ↔ {wide}: not a phone and a desktop drawing of this design")
            continue
        if phone in used_phone or wide in used_wide:
            left.append(f"{phone} ↔ {wide}: one of them is already paired")
            continue
        used_phone.add(phone)
        used_wide.add(wide)
        pairs.append({"phone": phone, "wide": wide, "because": str(item.get("because") or "")})
    return pairs, left


def pair(client: Any, doc: dict, *, usage: list | None = None) -> tuple[list[dict], list[str]]:
    """Which drawings are the same screen, asked a batch of phone drawings at
    a time against every desktop one; each drawing in one pair at most.
    ``([], [])`` when the design does not draw both sizes."""
    import time

    phones, wides = candidates(doc)
    if not phones:
        return [], []
    found: list[dict] = []
    for at in range(0, len(phones), BATCH):
        batch = phones[at:at + BATCH]
        t0 = time.monotonic()
        reply = client(system=SYSTEM, user=user_prompt(batch, wides), schema=schema(batch, wides))
        if usage is not None and getattr(reply, "usage", None) is not None:
            usage.append((reply.usage, time.monotonic() - t0))
        body = json.loads(getattr(reply, "text", reply))
        found += [x for x in body.get("pairs") or [] if isinstance(x, dict)]
    return settle(found, phones, wides)


def _live(doc: dict) -> list[dict]:
    return [p for p in doc.get("drawnPairs") or [] if isinstance(p, dict) and p.get("status") != "DEPRECATED"
            and p.get("phone") and p.get("wide")]


def phone_of(doc: dict) -> dict[str, str]:
    """``{desktop drawing: its phone drawing}``."""
    return {str(p["wide"]): str(p["phone"]) for p in _live(doc)}


def wide_of(doc: dict) -> dict[str, str]:
    """``{phone drawing: its desktop drawing}``."""
    return {str(p["phone"]): str(p["wide"]) for p in _live(doc)}
