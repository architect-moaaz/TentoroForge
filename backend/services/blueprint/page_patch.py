"""An observer repair on a composed page is an edit, not a regeneration.

The observer judged a page and found one thing wrong — the Female metric's
filter says Male, the table lacks its '#' column. The repair re-ran the
composer from nothing: a 45–115 s model call that re-decided every section,
was held to the whole contract again, and as often as not re-introduced a
fault the first pass had right (round 2 on DC5 dropped the row actions
while adding a column). Two repairs per page, each a full page, was most of
what "Page Design" cost.

A page that already has an accepted tree is repaired IN PLACE: the model is
shown the tree and the findings and returns JSON Patch edits (RFC 6902:
add / replace / remove on paths under `/root` and `/dataSources`). The
edited tree is held to the same contract as a composed one — the catalog,
the completeness rules, the wire — before it is proposed; a patch the
contract refuses falls back to the full compose it replaces, so nothing
gets weaker, only cheaper. What the model cannot touch it cannot break:
the edits are small, the untouched sections stay exactly as accepted.
"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

#: What the model returns. Structured-outputs safe: the API refuses an empty
#: schema ("accepts any JSON value"), so `value` travels as a STRING holding
#: JSON — the same convention the agent envelope uses for bodies — and is
#: decoded before the patch is applied.
PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": ["add", "replace", "remove"]},
                    "path": {"type": "string"},
                    "value": {"type": "string",
                              "description": "JSON text of the value for add/replace "
                                             "(e.g. \"Female\", 3, {\"key\":\"n\"}); omit for remove"},
                },
                "required": ["op", "path"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["edits"],
    "additionalProperties": False,
}

MAX_EDITS = 40

_FINDING_LINE = re.compile(r"^\s*-\s+\[")


def findings_of(feedback: str) -> str:
    """The bullet findings inside an observer brief, without the 'author it
    again' framing that tells a composer to replace everything."""
    lines = [l for l in (feedback or "").splitlines() if _FINDING_LINE.match(l)]
    return "\n".join(lines) if lines else (feedback or "").strip()


def _present_types(root: Any) -> set[str]:
    out: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type"):
                out.add(str(n["type"]))
            for c in n.get("children") or []:
                walk(c)
        elif isinstance(n, list):
            for c in n:
                walk(c)
    walk(root)
    return out


def _props_digest(catalog: Mapping[str, Any], types: set[str]) -> str:
    """Prop signatures for the component types the page uses — what an edit
    may set. The full catalogue is 31k characters; a patch needs the page's
    own vocabulary."""
    lines = []
    for name in sorted(types):
        entry = catalog.get(name) or {}
        schema = entry.get("props") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        sig = ", ".join(f"{p}{'*' if p in required else ''}" for p in props) or "(none)"
        lines.append(f"- {name}: {sig}")
    return "\n".join(lines)


def build_patch_prompt(doc: Mapping[str, Any], page: Mapping[str, Any],
                       layout: Mapping[str, Any], feedback: str,
                       catalog: Mapping[str, Any]) -> tuple[str, str]:
    reqs = {str(r.get("id")): r for r in (doc.get("requirements") or []) if isinstance(r, dict)}
    wanted = [reqs[r] for r in (page.get("requirements") or []) if r in reqs]
    req_text = "\n".join(
        f"- {r.get('id')}: {str(r.get('description') or '').strip()[:300]}" for r in wanted
    ) or "- (none listed)"
    workflows = "\n".join(
        f"- {w.get('id')}: {w.get('name')} — inputs: "
        + ", ".join(str(i.get('name')) for i in (w.get('inputs') or []) if isinstance(i, dict))
        for w in (doc.get("workflows") or []) if isinstance(w, dict)
    ) or "- (none)"
    tree = {"root": layout.get("root"), "dataSources": layout.get("dataSources") or []}
    system = (
        "You repair ONE composed page of a generated application by editing it in place.\n"
        "You are given the page's current tree (accepted by the contract) and the "
        "observer's findings. Return JSON Patch edits (RFC 6902) that fix exactly the "
        "findings — nothing else.\n\n"
        "Rules:\n"
        "- Paths are JSON Pointers into the document {root, dataSources}: e.g. "
        "/dataSources/2/filter/gender, /root/children/1/props/columns/0, "
        "/root/children/1/props/rowActions/- (append).\n"
        "- `value` is the JSON TEXT of the value: \"\\\"Female\\\"\" for a string, "
        "\"3\" for a number, \"{\\\"key\\\":\\\"rowNumber\\\",\\\"label\\\":\\\"#\\\"}\" "
        "for an object. Omit it for remove.\n"
        "- Edit the smallest thing that fixes each finding. Keep every control, data "
        "source, route and workflow binding that is not named by a finding; a page that "
        "loses a control it had is refused.\n"
        "- A control's action stays what it is: a Delete runs the workflow that deletes; "
        "an Edit navigates to the form or runs the workflow that updates.\n"
        "- Use only the props the component allows (listed below). Do not invent "
        "component types.\n"
        "- Data-source names and the bindings that read them ({{name}}) must stay "
        "consistent; rename nothing.\n"
        f"- At most {MAX_EDITS} edits. If a finding cannot be fixed by editing this "
        "tree, leave it and say so in `note`.\n\n"
        "Components on this page and the props each allows (`*` = required):\n"
        + _props_digest(catalog, _present_types(layout.get("root")))
    )
    user = (
        f"Page {page.get('id')} — route {page.get('route')} — pattern {page.get('pattern') or '-'}.\n"
        f"Declared actions: {', '.join(str(a) for a in (page.get('actions') or [])) or '-'}.\n\n"
        f"Requirements this page claims:\n{req_text}\n\n"
        f"Workflows in the application:\n{workflows}\n\n"
        f"The observer's findings to fix:\n{findings_of(feedback)}\n\n"
        f"The page's current tree:\n{json.dumps(tree, indent=1, ensure_ascii=False)}\n\n"
        "Return {\"edits\": [...], \"note\": \"...\"}."
    )
    return system, user


def apply_edits(layout: Mapping[str, Any], edits: list[dict]) -> dict:
    """The tree with the edits applied — a copy; the accepted tree is not
    touched until the result is proposed and the contract has spoken."""
    import jsonpatch
    if len(edits) > MAX_EDITS:
        raise ValueError(f"{len(edits)} edits — more than {MAX_EDITS}; a repair is small")
    for e in edits:
        path = str(e.get("path") or "")
        if not (path.startswith("/root") or path.startswith("/dataSources")):
            raise ValueError(f"edit outside the tree: {path!r}")
    target = {"root": copy.deepcopy(layout.get("root")),
              "dataSources": copy.deepcopy(layout.get("dataSources") or [])}
    ops = [{k: v for k, v in e.items() if k in ("op", "path", "value")} for e in edits]
    return jsonpatch.apply_patch(target, ops, in_place=False)


def parse_edits(text: str) -> tuple[list[dict], str]:
    """The model's edits, with each `value` decoded from its JSON text. A
    value that is not valid JSON is taken as the literal string — a model
    that answers `Female` where `"Female"` was asked still means Female."""
    data = json.loads(text)
    if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
        raise ValueError("reply is not {edits: [...]}")
    edits: list[dict] = []
    for e in data["edits"]:
        if not isinstance(e, dict):
            continue
        e = dict(e)
        if isinstance(e.get("value"), str):
            try:
                e["value"] = json.loads(e["value"])
            except ValueError:
                pass
        edits.append(e)
    return edits, str(data.get("note") or "")


def patch_page_layout(svc: Any, spec: Any, client: Callable[..., Any], *,
                      usage: Any = None, tell: Callable[[str], None] | None = None) -> Any:
    """Propose the current tree with the model's edits applied — or ``None``
    when there is no accepted tree to edit, the model's reply is unusable,
    or the edited tree fails the contract. ``None`` means: compose in full."""
    from services.blueprint.agent_contract import (
        AgentResult, ArtifactProposal, check_pattern_templates, InvalidPatternTemplate,
    )
    from services.blueprint.page_planner import load_catalog

    with svc.lock:
        doc = copy.deepcopy(svc.doc)
    page = next((p for p in doc.get("pages") or [] if p.get("id") == spec.subject), None)
    layout = next((l for l in doc.get("pageLayouts") or []
                   if isinstance(l, dict) and str(l.get("page")) == spec.subject
                   and l.get("status") != "SUPERSEDED"), None)
    if not page or not layout or not layout.get("root"):
        return None
    catalog = load_catalog()
    system, user = build_patch_prompt(doc, page, layout, spec.feedback or "", catalog)
    t0 = time.monotonic()
    try:
        raw = client(system=system, user=user, schema=PATCH_SCHEMA)
    except Exception as exc:  # noqa: BLE001 — a failed patch is a full compose
        logger.info("[patch] %s: model call failed: %s", spec.subject, exc)
        return None
    elapsed = time.monotonic() - t0
    text = getattr(raw, "text", raw)
    reply_usage = getattr(raw, "usage", None)
    if usage is not None and reply_usage is not None:
        try:
            usage.record(node=spec.node, agent=f"{spec.agent}:patch", usage=reply_usage,
                         elapsed_s=elapsed,
                         project=str((doc.get("application") or {}).get("id", "")))
        except Exception:  # noqa: BLE001
            pass
    try:
        edits, note = parse_edits(str(text))
        patched = apply_edits(layout, edits)
    except Exception as exc:  # noqa: BLE001
        logger.info("[patch] %s: edits unusable (%s) — composing in full", spec.subject, exc)
        return None
    if not edits:
        logger.info("[patch] %s: the model proposed no edits (%s) — composing in full",
                    spec.subject, note[:120])
        return None
    body = {k: v for k, v in layout.items() if k not in ("id", "status", "syncNote")}
    body.update({"page": spec.subject, "root": patched["root"],
                 "dataSources": patched["dataSources"],
                 "repairedBy": "patch",
                 "rationale": f"{layout.get('rationale') or 'composed'}; repaired in place "
                              f"({len(edits)} edit{'s' if len(edits) != 1 else ''})"
                              + (f": {note[:160]}" if note else "")})
    result = AgentResult(task_id=spec.task_id, agent=spec.agent,
                         proposals=[ArtifactProposal(section="pageLayouts",
                                                     natural_key=spec.subject, body=body)],
                         confidence=0.9)
    try:
        check_pattern_templates(result, doc)
    except InvalidPatternTemplate as exc:
        logger.info("[patch] %s: edited tree refused (%s) — composing in full",
                    spec.subject, str(exc)[:200])
        if tell is not None:
            tell(f"Tried to repair {page.get('route')} in place; the edit was refused "
                 f"({str(exc).split(';')[0][:120]}) — re-composing it.")
        return None
    if tell is not None:
        tell(f"Repaired {page.get('route')} in place with {len(edits)} "
             f"edit{'s' if len(edits) != 1 else ''} instead of re-composing it"
             + (f" — {note[:100]}" if note else "") + ".")
    return result


__all__ = ["PATCH_SCHEMA", "MAX_EDITS", "findings_of", "build_patch_prompt",
           "apply_edits", "parse_edits", "patch_page_layout"]
