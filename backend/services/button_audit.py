"""Deterministic button-action auditor (Slice 0 of the validate→repair loop).

A click 'working' is a runtime chain: the button must (1) exist, (2) carry an
action, (3) whose target resolves, (4) with the dispatch machinery wired. QA and
`next build` only see (1). This pass statically catches the most common break at
link (2): an actionable Button with NO action at all (a decorative "Approve" that
does nothing). It auto-wires the confident cases and reports the rest as findings
for the repair loop.

Resolution of *existing* actions (nav target exists, workflow name resolves) is
handled by nav_guard + schema_binding.canonicalize_and_guard_workflow_buttons —
this focuses on the missing-action case.
"""
from __future__ import annotations

import re

from services.nav_guard import _parts, _tokens, _entity_sig

_ACTION_PROPS = ("navigate", "workflow", "onClick", "href", "submit", "action")
_CANCEL_WORDS = ("cancel", "back", "close", "discard", "dismiss")
_NEW_WORDS = {"new", "add", "create"}
# Stopwords stripped from labels before scoring against workflow ids —
# they contribute noise, not intent. "Approve request" and "Request
# approve" match the same workflow regardless of order.
_LABEL_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "in", "on",
    "at", "by", "from", "as", "this", "that", "it", "my", "our",
}


def _words(label: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", str(label or "").lower()) if w]


def _sing(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") else t


def audit_button_actions(schema: dict, known_routes, workflow_index=None, route=None):
    """Walk a page schema; for each Button/NavLink with no resolvable action:
    auto-wire `New <Entity>` → `/entity/new` when such a route exists, else emit a
    `dead_button` finding. Returns (schema, findings). Buttons inside a Form (which
    owns submit/cancel) and Cancel/Back buttons are never flagged."""
    idx = workflow_index or {}
    exact = set(idx.get("exact") or [])
    norm = idx.get("norm") or {}
    routes = list(known_routes or [])
    findings: list[dict] = []

    def _wf_ok(w) -> bool:
        if not isinstance(w, str) or not w:
            return False
        return w in exact or re.sub(r"[^a-z0-9]", "", w.lower()) in norm

    def walk(node, in_form: bool) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, in_form)
            return
        if not isinstance(node, dict):
            return
        here_form = in_form or node.get("type") == "Form"
        if node.get("type") in ("Button", "NavLink"):
            p = node.get("props")
            if isinstance(p, dict):
                label = str(p.get("label") or p.get("text") or "")
                low = _words(label)
                has_action = any(p.get(k) for k in _ACTION_PROPS) or _wf_ok(p.get("workflow"))
                if not has_action:
                    if here_form or any(c in low for c in _CANCEL_WORDS):
                        pass  # the Form owns submit/cancel wiring
                    elif not (
                        _try_wire_new(p, low, routes)
                        or _try_wire_workflow(p, label, idx)
                        or _try_wire_nav(p, label, routes)
                    ):
                        f = {"type": "dead_button", "buttonLabel": label or "(unlabeled)",
                             "reason": "no action"}
                        if route:
                            f["route"] = route
                        findings.append(f)
        for c in node.get("children") or []:
            walk(c, here_form)
        if "root" in node:
            walk(node["root"], here_form)

    root = schema.get("root") if isinstance(schema, dict) and "root" in schema else schema
    walk(root, False)
    return schema, findings


def audit_app_buttons(app_dir) -> dict:
    """Run the button auditor over every page schema in a generated app (used by
    the repair loop). Auto-wires confident cases in place; returns {wired, dead}."""
    import json
    from pathlib import Path
    from services.crud_actions import build_workflow_index
    from services.route_slug import route_from_slug

    sroot = Path(app_dir) / "src" / "schemas"
    if not sroot.exists():
        return {"wired": 0, "dead": 0}
    routes = [route_from_slug(str(p.relative_to(sroot).with_suffix("")).replace("\\", "/"))
              for p in sroot.rglob("*.json")]
    idx = build_workflow_index(app_dir)
    wired = dead = 0
    for p in sroot.rglob("*.json"):
        try:
            sc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = route_from_slug(str(p.relative_to(sroot).with_suffix("")).replace("\\", "/"))
        before = json.dumps(sc)
        sc, findings = audit_button_actions(sc, routes, idx, route=route)
        if json.dumps(sc) != before:
            p.write_text(json.dumps(sc, indent=2), encoding="utf-8")
            wired += 1
        dead += len(findings)
    return {"wired": wired, "dead": dead}


def _try_wire_new(props: dict, words: list[str], routes: list[str]) -> bool:
    """`New/Add/Create <Entity>` with a matching `/entity/new` route → wire navigate."""
    if not (set(words) & _NEW_WORDS):
        return False
    entity_tokens = {_sing(w) for w in words if w not in _NEW_WORDS}
    if not entity_tokens:
        return False
    for r in routes:
        parts = _parts(r)
        if len(parts) >= 2 and parts[-1] == "new":
            if entity_tokens & _tokens(parts[-2]):
                props["navigate"] = r
                return True
    return False


def _try_wire_nav(props: dict, label: str, routes: list[str]) -> bool:
    """Conservatively wire a no-action button to a *list* route whose entity
    tokens strongly + uniquely match the label (e.g. "Timeline" → /timeline).
    Only fires on a single high-confidence match, so it never guesses wrong."""
    lab = {_sing(w) for w in _words(label)} - _NEW_WORDS
    if not lab:
        return False
    best, best_score, ties = None, 0.0, 0
    for r in routes:
        parts = _parts(r)
        if not parts or "<dyn>" in parts:  # only static list-style routes
            continue
        sig = _entity_sig(r)
        if not sig:
            continue
        score = len(lab & sig) / len(lab | sig)
        if score > best_score:
            best, best_score, ties = r, score, 1
        elif score == best_score and score > 0:
            ties += 1
    if best is not None and best_score >= 0.6 and ties == 1:
        props["navigate"] = best
        return True
    return False


def _label_tokens(label: str) -> set[str]:
    """Content tokens for label→workflow matching. Strips stopwords + the
    "New/Add/Create" verbs (those route to /new, not a workflow)."""
    return {
        _sing(w) for w in _words(label)
        if w not in _LABEL_STOPWORDS and w not in _NEW_WORDS
    }


def _try_wire_workflow(props: dict, label: str, workflow_index: dict) -> bool:
    """Wire a no-action button to a WORKFLOW when its label uniquely
    matches one workflow's id/name/label tokens.

    General fix, not per-domain: any workflow whose id contains the
    label's content tokens (and no other workflow does) is a
    high-confidence match. Falls back to Jaccard similarity when
    substring doesn't isolate one candidate. Only fires on a UNIQUE
    single-winner match — never guesses under ambiguity.
    """
    if not workflow_index or not isinstance(label, str):
        return False
    lab = _label_tokens(label)
    if not lab:
        return False

    # workflow_index shape from crud_actions.build_workflow_index:
    #   {"exact": [id, ...], "norm": {norm_key: real_id}, "meta": {id: {label,name,...}}?}
    exact_ids = list(workflow_index.get("exact") or [])
    meta = workflow_index.get("meta") if isinstance(workflow_index.get("meta"), dict) else {}

    def _tok(s: str) -> set[str]:
        # Split camelCase / PascalCase before running the normal word
        # split — workflow ids are usually camelCase (ApproveRequest,
        # SendNotification) so treating them as a single token would
        # make the match unreachable.
        split = re.sub(r"(?<!^)(?=[A-Z])", " ", str(s or ""))
        return {_sing(w) for w in _words(split) if w not in _LABEL_STOPWORDS}

    scored: list[tuple[float, str]] = []
    for wid in exact_ids:
        # Combine id + optional metadata label/name into one token bag.
        toks = _tok(wid)
        m = meta.get(wid) if isinstance(meta, dict) else None
        if isinstance(m, dict):
            for k in ("label", "name", "title"):
                v = m.get(k)
                if isinstance(v, str):
                    toks |= _tok(v)
        if not toks:
            continue
        overlap = lab & toks
        if not overlap:
            continue
        # Jaccard over the content tokens — biases toward tight matches
        # so "approve request" matches ApproveRequest but not
        # ApproveRequestAndArchive (which is broader).
        score = len(overlap) / len(lab | toks)
        scored.append((score, wid))

    if not scored:
        return False
    scored.sort(reverse=True)
    top_score, top_id = scored[0]
    # Unique winner + majority-of-label-covered.
    if top_score < 0.5:
        return False
    if len(scored) > 1 and scored[1][0] == top_score:
        return False  # tie → refuse to guess
    props["workflow"] = top_id
    return True
