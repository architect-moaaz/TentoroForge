"""The business rules are a Blueprint section, and Smith can change them.

"Years of experience cannot be more than 60", "a nurse needs at least one
speciality": rules the `business_rules` agent authors from the requirements
and the entities, projected into the runtime's rules directory so they fire
on the form. Nothing in the verb set touched `businessRules`; the
`create_business_rule` tool wrote the runtime store directly and the
Blueprint never learned of it.

Add: the ask becomes a requirement; the agent is briefed for ONE new rule
(existing rules are never returned — a re-authored rule under the same name
would replace one the user did not ask about); the rules are re-projected.
Edit: the ask becomes a decision on the rule; the agent re-authors that one.
Remove: the rule is retired, never deleted, and re-projected out.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import (
    SectionChangeError, find_named, names, record_requirement, rerun,
)

logger = logging.getLogger(__name__)

NODE = "business_rules"


class _Covered(Exception):
    """The reply was one existing rule: the ask is already enforced."""


def _rules(doc: dict) -> list[dict]:
    return [r for r in (doc.get("businessRules") or []) if isinstance(r, dict)]


def _live(doc: dict) -> list[dict]:
    return [r for r in _rules(doc) if r.get("status") != "DEPRECATED"]


def _project(svc: Any, app_root: str | None) -> list[str]:
    if not app_root:
        return []
    from services.blueprint.projection import project_business_rules
    return list(project_business_rules(svc.doc, app_root).get("files") or [])


def _rule_line(r: dict) -> str:
    return f"{r.get('name')} ({r.get('id')}): {r.get('statement')}" + (f" — when {r.get('when')}" if r.get("when") else "")


def add_rule(svc: Any, request: str, *, app_root: str | None = None, executor: Any = None,
             reasoning: Any = None) -> dict:
    request = (request or "").strip()
    if not request:
        raise SectionChangeError("no rule was described, so there is nothing to add.")
    req = record_requirement(svc, request, owner="businessRules")
    existing = {str(r.get("name") or "").strip().lower() for r in _live(svc.doc)}
    brief = (
        "THIS IS A CHANGE to an application that is already built, not a first authoring.\n"
        f"The user asked for ONE new rule: \"{request}\". It satisfies {req.get('id')} — cite it in "
        "the rule's `requirements`.\n"
        f"These rules exist already and are NOT to be returned or re-stated: {names(_live(svc.doc))}. "
        "Return exactly ONE proposal, for the new rule, under a new name that says what it enforces — "
        "the rule the user asked for and no other, even if you can see rules the application lacks. "
        "If an existing rule already enforces exactly this, return that one rule under its own name, "
        "revised to say so. "
        "Where it governs a form field, make it `condition_action` on that entity with a FEEL `when` "
        "and a `then` the form can act on, so it fires rather than merely being stated."
    )
    covered: list[str] = []
    def keep(props):
        # EXACTLY ONE NEW RULE, or nothing. Asked "years of experience cannot
        # exceed 60" the agent returned several rules it thought the app
        # lacked, and the first of them — a specialities check — was taken
        # as the answer. Several new rules is a reply to a question nobody
        # asked; it is refused with the reason and asked again. A reply that
        # is ONLY an existing rule says the ask is already enforced — that
        # is an answer, not a refusal, and it ends the turn honestly below.
        mine = [p for p in props if p.section == "businessRules"]
        fresh = [p for p in mine if str((p.body or {}).get("name") or "").strip().lower() not in existing]
        if not fresh and len(mine) == 1:
            covered.append(str((mine[0].body or {}).get("name") or ""))
            raise _Covered()
        return fresh if len(fresh) == 1 else []
    try:
        props, out = rerun(svc, NODE, brief=brief, request=request, interpretation=f"add a rule: {request}",
                           keep=keep, executor=executor, reasoning=reasoning, app_root=app_root,
                           empty=(f"return exactly ONE new rule, for \"{request}\" and nothing else — no "
                                  "existing rule re-stated, no other rule you think the app lacks"),
                           say=f"Authoring a rule for: {request}.")
    except _Covered:
        rule = find_named(_rules(svc.doc), covered[0]) or {}
        raise SectionChangeError(f"that is already enforced by the rule {rule.get('name') or covered[0]}"
                                 + (f" ({rule.get('id')}): {rule.get('statement')}" if rule else "")
                                 + " — nothing has been changed. Ask me to change that rule if it should say something else.")
    name = str((props[0].body or {}).get("name") or "")
    rule = next((r for r in _live(svc.doc) if str(r.get("name") or "").strip().lower() == name.strip().lower()), None)
    if rule is None:
        raise SectionChangeError("the rule was committed but cannot be found by its name.")
    if req.get("id") and req["id"] not in (rule.get("requirements") or []):
        rule["requirements"] = list(rule.get("requirements") or []) + [req["id"]]
        svc.save()
    return {"applied": True, "rule": str(rule["id"]), "name": name, "requirement": req.get("id"),
            "kind": rule.get("kind"), "statement": rule.get("statement"), "when": rule.get("when"),
            "edited_paths": _project(svc, app_root)}


def edit_rule(svc: Any, ref: str, change: str, *, app_root: str | None = None, executor: Any = None,
              reasoning: Any = None) -> dict:
    """A RULE'S IDENTITY IS ITS STATEMENT — the registry keys `businessRules`
    by a hash of it (`prose_key`), so a rule re-stated is, to the registry, a
    new rule. Rather than fight the scheme, the edit lets the revised rule
    land where the registry puts it and, when that is a new id, retires the
    old one and records the decision on the live one. The name carries over,
    so a person still finds it by the name they used."""
    from services.smith.decisions import NotADecision, record
    change = (change or "").strip()
    rule = find_named(_rules(svc.doc), ref)
    if rule is None:
        raise SectionChangeError(f"I cannot tell which rule {ref!r} means. The rules are: {names(_rules(svc.doc))}.")
    if not change:
        raise SectionChangeError(f"what should be different about {rule.get('name')}?")
    old_id = str(rule["id"])
    before = _rule_line(rule)
    brief = (
        "THIS IS A CHANGE to an application that is already built.\n"
        f"The user asked to change the rule \"{rule.get('name')}\" ({rule['id']}): \"{change}\".\n"
        f"As it stands: {before}\n"
        "Return exactly ONE proposal, for this rule, under the SAME name, revised to honour the ask; "
        "return no other rule."
    )
    want = str(rule.get("name") or "").strip().lower()
    def keep(props):
        mine = [p for p in props if p.section == "businessRules"]
        named = [p for p in mine if str((p.body or {}).get("name") or "").strip().lower() == want]
        chosen = (named or mine)[:1]
        for p in chosen:
            p.body["name"] = rule.get("name")           # the name carries over; a respelling is a second rule
            p.body["requirements"] = list(rule.get("requirements") or [])
        return chosen
    props, _ = rerun(svc, NODE, brief=brief, request=change, interpretation=f"change {rule.get('name')}: {change}",
                     keep=keep, executor=executor, reasoning=reasoning, app_root=app_root,
                     say=f"Re-authoring the rule {rule.get('name')}: {change}.")
    statement = str((props[0].body or {}).get("statement") or "")
    now = next((r for r in _live(svc.doc) if str(r.get("statement") or "") == statement
                and str(r.get("name") or "").strip().lower() == want), None) \
        or next(r for r in _rules(svc.doc) if r["id"] == old_id)
    superseded = None
    if str(now["id"]) != old_id:
        old = next(r for r in _rules(svc.doc) if r["id"] == old_id)
        old["status"] = "DEPRECATED"
        superseded = old_id
        svc.save()
    try:
        decision = record(svc, artifact_id=str(now["id"]), decision=change,
                          reason="Asked in conversation after the build; the rule was re-authored against it.")
    except NotADecision as exc:
        raise SectionChangeError(str(exc)) from exc
    return {"applied": True, "rule": str(now["id"]), "name": str(now.get("name")), "decision": decision.id,
            "superseded": superseded, "before": before, "after": _rule_line(now),
            "edited_paths": _project(svc, app_root)}


def remove_rule(svc: Any, ref: str, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    rule = find_named(_rules(svc.doc), ref)
    if rule is None:
        raise SectionChangeError(f"I cannot tell which rule {ref!r} means. The rules are: {names(_rules(svc.doc))}.")
    rule["status"] = "DEPRECATED"
    svc.save()
    tell(reasoning, f"Retired the rule {rule.get('name')}.", "step")
    return {"applied": True, "rule": str(rule["id"]), "name": str(rule.get("name")),
            "edited_paths": _project(svc, app_root)}


def summary_of(verb: str, out: dict) -> str:
    if verb == "add_rule":
        fires = (f" It fires on the form when `{out['when']}`." if out.get("when") else
                 " It is stated, not enforced on a form — no field condition was given.")
        return f"Added the rule {out['name']} ({out['rule']}): {out['statement']}{fires} Recorded as {out['requirement']}."
    if verb == "edit_rule":
        return (f"Changed the rule {out['name']} ({out['rule']}), recorded as {out['decision']}"
                + (f"; it supersedes {out['superseded']}" if out.get("superseded") else "")
                + f". Now: {out['after']} (was: {out['before']}).")
    return f"Retired the rule {out['name']} ({out['rule']}); it no longer fires."


def run(output_dir: str, verb: str, *, rule: str = "", change: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [], "reason": "this project has no Blueprint yet, so there are no rules to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        if verb == "add_rule":
            out = add_rule(svc, rule, app_root=app_root, reasoning=reasoning)
        elif verb == "edit_rule":
            out = edit_rule(svc, rule, change, app_root=app_root, reasoning=reasoning)
        elif verb == "remove_rule":
            out = remove_rule(svc, rule, app_root=app_root, reasoning=reasoning)
        else:
            return {"applied": False, "edited_paths": [], "reason": f"unknown rule verb {verb!r}"}
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] %s failed", verb)
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(verb, out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["add_rule", "edit_rule", "remove_rule", "run", "summary_of"]
