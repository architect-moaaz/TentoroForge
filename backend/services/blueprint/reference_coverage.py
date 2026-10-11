"""The model is held to the domain reference — every item answered or declined.

`domainReference` (written first, by `domain_reference`) says what a
practitioner expects of a product in this sub-domain: screens, records,
processes, rules, integrations. Each model node is told to answer every item
of its kind — the artifact that answers it names it in `reference` — or to
decline it with a reason (`domainReference.declined`). This is the
deterministic check behind that: an item neither answered nor declined is a
finding on the edge that relates the reference to the section, owned by the
section's author, so the observer sends it back like any other gap (§73).

Coverage is by exact name first (`reference`), then by the artifact's own
name normalised (case, separators, a plural). Nothing is inferred from
purpose text: a screen called something else that happens to do the job is
the author's to name, not this module's to guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.blueprint.verification import Finding

#: kind -> (reference list, Blueprint section, edge, the artifacts' list in the doc)
KINDS: dict[str, tuple[str, str, str]] = {
    "screen": ("screens", "pages", "Reference↔Page"),
    "record": ("records", "data.entities", "Reference↔Record"),
    "process": ("processes", "workflows", "Reference↔Process"),
    "rule": ("rules", "businessRules", "Reference↔Process"),
    "integration": ("integrations", "integrations", "Reference↔Integration"),
}

REFERENCE_EDGES: tuple[str, ...] = ("Reference↔Page", "Reference↔Record", "Reference↔Process", "Reference↔Integration")


@dataclass(frozen=True)
class CoverageItem:
    kind: str
    name: str
    purpose: str
    for_roles: tuple[str, ...]
    covered_by: str | None          # the artifact id (or name) that answers it
    declined: dict | None           # the decline, when one names it

    @property
    def open(self) -> bool:
        return self.covered_by is None and self.declined is None


def _norm(name: Any) -> str:
    s = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    if s.endswith("ies"):
        s = s[:-3] + "y"
    elif s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _artifacts(doc: dict, kind: str) -> list[dict]:
    section = KINDS[kind][1]
    if section == "data.entities":
        return _live((doc.get("data") or {}).get("entities"))
    return _live(doc.get(section))


def _answers(artifact: dict, item_name: str) -> bool:
    ref = str(artifact.get("reference") or "").strip().lower()
    if ref:
        return ref == item_name.strip().lower()
    names = [artifact.get("name"), artifact.get("menuEntry"), artifact.get("kind")]
    return _norm(item_name) in {_norm(n) for n in names if n}


def coverage(doc: dict, kinds: tuple[str, ...] = tuple(KINDS)) -> list[CoverageItem]:
    """Every reference item of the kinds asked, with what answers it."""
    ref = doc.get("domainReference") or {}
    declines = [d for d in ref.get("declined") or [] if isinstance(d, dict) and d.get("name")]
    out: list[CoverageItem] = []
    for kind in kinds:
        list_key = KINDS[kind][0]
        artifacts = _artifacts(doc, kind)
        for item in ref.get(list_key) or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"])
            by = next((a for a in artifacts if _answers(a, name)), None)
            declined = next((d for d in declines if d.get("kind") == kind
                             and _norm(d.get("name")) == _norm(name)), None)
            out.append(CoverageItem(
                kind=kind, name=name, purpose=str(item.get("purpose") or item.get("statement") or ""),
                for_roles=tuple(str(r) for r in item.get("forRoles") or item.get("roles") or []),
                covered_by=str(by.get("id") or by.get("name")) if by is not None else None,
                declined=declined))
    return out


def _findings(doc: dict, kinds: tuple[str, ...]) -> list[Finding]:
    out: list[Finding] = []
    for it in coverage(doc, kinds):
        if not it.open:
            continue
        _list_key, section, edge = KINDS[it.kind]
        who = f" for {', '.join(it.for_roles)}" if it.for_roles else ""
        out.append(Finding(
            edge, section=section, artifact_id=None,
            detail=(f"the reference {it.kind} '{it.name}'{who}"
                    + (f" — {it.purpose[:160]}" if it.purpose else "")
                    + f" is neither answered by a {section.split('.')[-1][:-1] if section.endswith('s') else section}"
                      " whose `reference` names it, nor declined with a reason in domainReference.declined"),
        ))
    return out


def check_reference_pages(doc: dict) -> list[Finding]:
    return _findings(doc, ("screen",))


def check_reference_records(doc: dict) -> list[Finding]:
    return _findings(doc, ("record",))


def check_reference_processes(doc: dict) -> list[Finding]:
    return _findings(doc, ("process", "rule"))


def check_reference_integrations(doc: dict) -> list[Finding]:
    return _findings(doc, ("integration",))


def summary(doc: dict) -> dict:
    """`{total, green, red: [{kind, item, why}], declined: [{kind, item, reason, by}]}`
    over every reference item — what the model gate says, and the
    deterministic half of the domain score."""
    items = coverage(doc)
    red = [{"kind": it.kind, "item": it.name, "why": "not in the model and not declined"} for it in items if it.open]
    declined = [{"kind": it.kind, "item": it.name, "reason": str(it.declined.get("reason") or ""),
                 "by": str(it.declined.get("by") or "owner")} for it in items if it.declined]
    counted = [it for it in items if it.declined is None]
    return {"total": len(counted), "green": len([it for it in counted if it.covered_by]), "red": red,
            "declined": declined}


def record_declines(svc: Any, declines: list[dict], *, by: str) -> list[dict]:
    """Merge well-formed declines into `domainReference.declined`, by name
    and kind, keeping the first reason. Returns what was added."""
    ref = dict(svc.doc.get("domainReference") or {})
    have = list(ref.get("declined") or [])
    seen = {(str(d.get("kind")), _norm(d.get("name"))) for d in have if isinstance(d, dict)}
    added: list[dict] = []
    for d in declines or []:
        if not isinstance(d, dict) or d.get("kind") not in KINDS or not str(d.get("name") or "").strip() \
                or not str(d.get("reason") or "").strip():
            continue
        key = (str(d["kind"]), _norm(d["name"]))
        if key in seen:
            continue
        seen.add(key)
        row = {"kind": str(d["kind"]), "name": str(d["name"]).strip(), "reason": str(d["reason"]).strip()[:400],
               "by": str(d.get("by") or by)}
        have.append(row)
        added.append(row)
    if added:
        ref["declined"] = have
        svc.doc["domainReference"] = ref
    return added


__all__ = ["KINDS", "REFERENCE_EDGES", "CoverageItem", "check_reference_integrations", "check_reference_pages",
           "check_reference_processes", "check_reference_records", "coverage", "record_declines", "summary"]
