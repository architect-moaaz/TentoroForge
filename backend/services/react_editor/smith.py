"""Smith on a selection — propose, validate, apply, as one revision.

The person selects something on the canvas and says what they want of it.
Smith is handed the page and the selection (SMITH-003): the selected nodes'
source, their ancestors, the whole view and load as read context, the SDK and
kit the page is written against, the registry of what can be added, and the
allowed write scope. It answers with replacements for the selected nodes —
never a rewritten page (SMITH-004). The replacements are applied to a copy,
checked by the compiler, and staged as a proposal the person applies or
discards (SMITH-005). A proposal remembers the revision it was made against;
applying it onto a different one is refused (SMITH-006).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from services.react_editor import adapter, service
from services.react_editor.adapter import AdapterError, revision_of
from services.react_editor.registry import palette_summary
from services.react_editor.service import EditorError, Project

logger = logging.getLogger(__name__)

PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "explanation", "replacements", "imports", "needs", "questions"],
    "properties": {
        "summary": {"type": "string", "description": "One plain sentence: what changes, for the person who asked."},
        "explanation": {"type": "string", "description": "Two or three plain sentences on how, no code terms."},
        "replacements": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["nodeId", "jsx"],
                      "properties": {"nodeId": {"type": "string"},
                                     "jsx": {"type": "string", "description": "The complete new JSX for this node."}}},
        },
        "imports": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["source", "names"],
                      "properties": {"source": {"type": "string"},
                                     "names": {"type": "array", "items": {"type": "string"}}}},
        },
        "needs": {"type": "array", "items": {"type": "string"},
                  "description": "What the request needs that is outside this selection or this page — say so instead of doing it."},
        "questions": {
            "type": "array",
            "description": "Only when the request is genuinely ambiguous: at most one question with 2–4 concrete choices.",
            "items": {"type": "object", "additionalProperties": False, "required": ["question", "options"],
                      "properties": {"question": {"type": "string"},
                                     "options": {"type": "array", "items": {"type": "string"}}}},
        },
    },
}

_RULES = """
# You are editing ONE PART of an existing page

The person selected something on the page and said what they want of it. You return the new JSX
for the selected node(s) — nothing else on the page changes.

- Return a replacement for EVERY selected node you change, keyed by its id, and the complete JSX
  of that node (its whole subtree). Keep its `data-fid`-free form: never add data-fid attributes.
- Do not restate or rewrite parts of the page you were not given to change. If the request truly
  needs the parent to change (e.g. two fields side by side need their container to become a grid),
  you may return one replacement for the nearest ancestor listed under "ancestors you may extend
  to", and say so in `explanation`.
- Anything the request needs that is outside the selection — new data in load.ts, a new workflow,
  a change to another page, a shared component, a new dependency — goes in `needs`, in plain
  words. Do not attempt it.
- New components come from the UI kit and the SDK listed above, and need their import in
  `imports` (source and names) — the page will have the import added.
- Keep every existing handler, binding and workflow call that the person did not ask to change.
- Use the design tokens (semantic Tailwind classes), never hex colours.
- If the request is genuinely ambiguous, return no replacements and ONE question with 2–4 concrete
  options in `questions`. Otherwise answer without asking.
- `summary` and `explanation` are for a person who does not know React: no tags, props, classes
  or file names.
"""


def _ancestors(model: dict, node_id: str) -> list[dict]:
    out = []
    cur = model["nodes"].get(node_id)
    while cur and cur.get("parent"):
        cur = model["nodes"][cur["parent"]]
        out.append(cur)
    return out


def _opening(view: str, node: dict) -> str:
    inner = node.get("innerSpan")
    end = inner[0] if inner else node["span"][1]
    return view[node["span"][0]:end].strip()


def _request_context(doc: dict, view: str, load: str, model: dict, page: dict, selection: dict,
                     scope: dict, annotation: str, prompt: str, breakpoint: str) -> str:
    ids = [str(x) for x in selection.get("nodeIds") or []]
    parts = [f"# The page\n{page.get('name')} — {page.get('route')}\n{page.get('purpose') or ''}\n"]
    parts.append(f"# Selection ({selection.get('type') or 'component'}, {len(ids)} node(s)), viewed at {breakpoint} width\n")
    common: list[str] = []
    for nid in ids:
        node = model["nodes"].get(nid)
        if not node:
            continue
        chain = " › ".join(a["type"] for a in reversed(_ancestors(model, nid)))
        parts.append(f"## {nid} — <{node['type']}> {('inside ' + chain) if chain else ''}"
                     f"{' (in a repeated list)' if node.get('context') == 'repeat' else ''}"
                     f"{' (shown conditionally)' if node.get('context') == 'conditional' else ''}\n"
                     f"```tsx\n{view[node['span'][0]:node['span'][1]]}\n```")
    ext = scope.get("extendableNodeIds") or []
    if ext:
        parts.append("# Ancestors you may extend to, if the request truly needs it\n" + "\n".join(
            f"- {aid}: {_opening(view, model['nodes'][aid])[:160]}" for aid in ext if aid in model["nodes"]))
    if annotation:
        parts.append(f"# The person's note on the selection\n{annotation}")
    parts.append(f"# What they want\n{prompt}")
    parts.append("# The rest of the page, for context only (read, do not return it)\n"
                 f"```tsx\n// view.tsx\n{view}\n```\n```ts\n// load.ts\n{load}\n```")
    parts.append("# Things that can be added (from the registry)\n" + palette_summary())
    return "\n\n".join(parts)


def _proposal_path(project: Project, proposal_id: str) -> Path:
    return project.editor_dir / "proposals" / f"{proposal_id}.json"


def get_proposal(project: Project, proposal_id: str) -> dict:
    path = _proposal_path(project, proposal_id)
    if not path.exists():
        raise EditorError(404, "no-proposal", "That proposal is gone — ask again.")
    return json.loads(path.read_text("utf-8"))


def _save(project: Project, proposal: dict) -> None:
    path = _proposal_path(project, proposal["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal, indent=1), "utf-8")


def _public(proposal: dict) -> dict:
    return {k: v for k, v in proposal.items() if k not in ("viewAfter", "loadAfter")}


def propose(project: Project, page_id: str, *, base_revision: str, prompt: str, selection: dict,
            scope: dict | None = None, annotation: str = "", breakpoint: str = "desktop",
            client: Any, proposal_id: str | None = None, prior: dict | None = None) -> dict:
    """Ask Smith, validate the answer against a copy of the page, stage it."""
    from services.blueprint.ui_engineer import system_prompt
    scope = dict(scope or {})
    svc = service.load_blueprint(project)
    doc = svc.doc
    page, row, view, load, revision = service._state(svc, project, page_id)
    if row is None:
        raise EditorError(409, "not-coded", "This page has no designed code for Smith to change yet.")
    if base_revision != revision:
        raise EditorError(409, "stale", "The page changed since you loaded it — reload before asking Smith.",
                          current=revision)
    try:
        model = adapter.model(view, load, app_root=project.app_root)
    except AdapterError as exc:
        raise EditorError(422, exc.code, str(exc))
    ids = [str(x) for x in selection.get("nodeIds") or []]
    missing = [i for i in ids if i not in model["nodes"]]
    if not ids or missing:
        raise EditorError(409, "deleted-target",
                          "What was selected is no longer on the page — select again.", missing=missing)
    allowed = set(scope.get("allowedNodeIds") or ids)
    # The nearest ancestors are what a layout request may need to extend to.
    ext: list[str] = []
    for nid in ids:
        node = model["nodes"][nid]
        if node.get("parent") and node["parent"] not in allowed:
            ext.append(node["parent"])
    scope["extendableNodeIds"] = sorted(set(ext))

    system = system_prompt(doc) + _RULES
    user = _request_context(doc, view, load, model, page, selection, scope, annotation, prompt, breakpoint)
    if prior and prior.get("choice"):
        user += f"\n\n# The person answered your question\n{prior['question']}\n→ {prior['choice']}"
    t0 = time.monotonic()
    reply = client(system=system, user=user, schema=PROPOSAL_SCHEMA)
    text = getattr(reply, "text", reply)
    elapsed = time.monotonic() - t0
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditorError(502, "malformed", "Smith's answer could not be read — try asking again.") from exc

    pid = proposal_id or uuid.uuid4().hex[:12]
    proposal: dict[str, Any] = {
        "id": pid, "pageId": page_id, "baseRevision": revision, "prompt": prompt, "annotation": annotation,
        "selection": {"type": selection.get("type") or "component", "nodeIds": ids},
        "summary": str(body.get("summary") or ""), "explanation": str(body.get("explanation") or ""),
        "needs": [str(n) for n in body.get("needs") or []],
        "questions": [q for q in body.get("questions") or [] if isinstance(q, dict) and q.get("question")],
        "replacements": [], "imports": [i for i in body.get("imports") or [] if isinstance(i, dict)],
        "expandsScope": [], "refused": [], "findings": [], "valid": False, "status": "staged",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "timing": {"generationMs": int(elapsed * 1000), "validationMs": 0},
        "model": getattr(client, "model", None),
    }
    if proposal["questions"] and not body.get("replacements"):
        proposal["status"] = "needs-choice"
        _save(project, proposal)
        return _public(proposal)

    ops: list[dict[str, Any]] = []
    for rep in body.get("replacements") or []:
        nid, jsx = str(rep.get("nodeId") or ""), str(rep.get("jsx") or "")
        if nid not in model["nodes"] or not jsx.strip():
            proposal["refused"].append({"nodeId": nid, "why": "not on the page"})
            continue
        if nid in allowed:
            pass
        elif nid in scope["extendableNodeIds"]:
            proposal["expandsScope"].append(nid)
        else:
            proposal["refused"].append({"nodeId": nid, "why": "outside what was selected"})
            continue
        before = view[model["nodes"][nid]["span"][0]:model["nodes"][nid]["span"][1]]
        proposal["replacements"].append({"nodeId": nid, "type": model["nodes"][nid]["type"], "before": before, "after": jsx})
        ops.append({"op": "replaceNode", "id": nid, "jsx": jsx})
    for imp in proposal["imports"]:
        names = [str(n) for n in imp.get("names") or []]
        if imp.get("source") and names:
            ops.append({"op": "addImport", "source": str(imp["source"]), "names": names})
    if not ops:
        proposal["status"] = "nothing" if not proposal["needs"] else "needs-more"
        _save(project, proposal)
        return _public(proposal)

    # An ancestor replaced together with a descendant: the inner one first (its
    # id still resolves), then the outer replacement supersedes it.
    ops.sort(key=lambda o: (o["op"] != "replaceNode", -len(o.get("id", "")) if o["op"] == "replaceNode" else 0))
    t1 = time.monotonic()
    try:
        view_after = adapter.patch(view, ops, app_root=project.app_root)
        findings = service._check(doc, project, page_id, view_after, load)
        proposal["viewAfter"], proposal["loadAfter"] = view_after, load
    except AdapterError as exc:
        findings = [{"file": "view.tsx", "line": exc.line, "code": exc.code, "raw": str(exc),
                     "plain": str(exc), "severity": "must-fix"}]
    except EditorError as exc:
        findings = [{"file": None, "line": None, "code": exc.code, "raw": str(exc), "plain": str(exc),
                     "severity": "must-fix"}]
    proposal["timing"]["validationMs"] = int((time.monotonic() - t1) * 1000)
    proposal["findings"] = findings
    proposal["valid"] = not findings and "viewAfter" in proposal
    proposal["status"] = "ready" if proposal["valid"] else "invalid"
    _save(project, proposal)
    return _public(proposal)


def apply_proposal(project: Project, page_id: str, proposal_id: str, *, base_revision: str,
                   allow_scope_expansion: bool = False) -> dict[str, Any]:
    proposal = get_proposal(project, proposal_id)
    if proposal.get("pageId") != page_id:
        raise EditorError(409, "wrong-page", "That proposal belongs to another page.")
    if proposal.get("status") == "applied":
        # Idempotent: the same apply twice is one change.
        return {"proposal": _public(proposal), "revision": proposal.get("appliedRevision"), "alreadyApplied": True}
    if not proposal.get("valid"):
        raise EditorError(409, "invalid-proposal", "This proposal did not pass its checks and cannot be applied.",
                          findings=proposal.get("findings") or [])
    if proposal["baseRevision"] != base_revision:
        raise EditorError(409, "stale", "The page changed since Smith proposed this — ask again so the "
                                        "proposal is made against the page as it is now.",
                          current=base_revision)
    if proposal.get("expandsScope") and not allow_scope_expansion:
        raise EditorError(409, "scope", "This change also touches the part around what you selected. "
                                        "Allow that to apply it.", expandsScope=proposal["expandsScope"])
    result = service.apply(project, page_id, base_revision=base_revision, ops=[],
                           source={"view": proposal["viewAfter"], "load": proposal["loadAfter"]},
                           label=f"Smith: {proposal.get('summary') or proposal.get('prompt')}"[:120],
                           kind="smith", check=False)
    proposal["status"] = "applied"
    proposal["appliedRevision"] = result["revision"]
    proposal["appliedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _save(project, proposal)
    result["proposal"] = _public(proposal)
    return result


def discard(project: Project, proposal_id: str) -> dict:
    proposal = get_proposal(project, proposal_id)
    if proposal.get("status") != "applied":
        proposal["status"] = "discarded"
        _save(project, proposal)
    return _public(proposal)


def default_client() -> Any:
    from services.blueprint.executors import SMITH_MODEL, AnthropicModel
    return AnthropicModel(model=SMITH_MODEL, effort="medium")


__all__ = ["propose", "apply_proposal", "discard", "get_proposal", "default_client", "PROPOSAL_SCHEMA"]
