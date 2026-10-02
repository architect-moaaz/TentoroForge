"""What a change did to the record types, field by field, in words.

A data change is proposed whole — the entity as the agent now sees it — so
what it altered beyond the ask is invisible unless it is compared. Asked to
make a dish name unique, the data agent also renamed `image` to `photo` and
made `price` a plain number (2026-10-02); the push then failed on a column
nobody had asked for. Said field by field, an unasked change is visible to
whoever must put it back, and a loosened rule is visible to the owner.
"""
from __future__ import annotations


#: The settings of a field a person relies on: loosening one is said aloud.
_KEPT = ("unique", "required", "type")


def field_settings(doc: dict) -> dict[tuple[str, str], dict]:
    """{(entity, field): {unique, required, type}} over the definition."""
    out: dict[tuple[str, str], dict] = {}
    for e in ((doc.get("data") or {}).get("entities") or []):
        for f in e.get("fields") or []:
            if isinstance(f, dict) and f.get("name"):
                out[(str(e.get("name")), str(f["name"]))] = {k: f.get(k) for k in _KEPT}
    return out


def what_changed(before: dict, after: dict) -> list[str]:
    """What a repair did to the fields, in words: a rule dropped, a type
    changed, a field gone or added."""
    a, b = field_settings(before), field_settings(after)
    out = []
    for key in sorted(set(a) | set(b)):
        name = ".".join(key)
        if key not in b:
            out.append(f"{name} was removed")
        elif key not in a:
            out.append(f"{name} was added")
        else:
            for rule in ("unique", "required"):
                if a[key].get(rule) and not b[key].get(rule):
                    out.append(f"{name} is no longer {rule}")
                elif b[key].get(rule) and not a[key].get(rule):
                    out.append(f"{name} is now {rule}")
            if a[key].get("type") != b[key].get("type"):
                out.append(f"{name} changed from {a[key].get('type')} to {b[key].get('type')}")
    return out
