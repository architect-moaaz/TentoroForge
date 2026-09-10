"""Deterministic nav-target 404 guard.

The pipeline's cross-reference gate checks page→API links but not page→page
`navigate` targets. LLM-authored pages routinely point buttons at routes that
don't exist — naming drift (`/rate-approvals` when the page is `/rate-changes`),
missing edit pages (`/guests/[id]/edit`), or list pages that were never generated
(`/users`). Each is a dead click → a 404.

Given the full set of generated routes (from the schema files), this rewrites
every `navigate` target so nothing 404s:
  1. resolves as-is (incl. dynamic `[id]` / `{{...}}` segments) → keep;
  2. an `.../edit` with no edit page but a detail page → repoint to the detail
     page (view instead of edit);
  3. a close single naming-drift match → repoint to it;
  4. otherwise → neutralize (drop `navigate`) so the control is inert, not broken.

Pure route logic is unit-tested; `guard_nav_targets` does the file I/O.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _norm(r: str) -> str:
    r = (r or "").split("?")[0].split("#")[0].strip()
    return r.rstrip("/") if len(r) > 1 else r


def _parts(route: str) -> list[str]:
    """Path segments with dynamic ones (`[id]`, `:id`, `{{x}}`) collapsed to a
    single wildcard token."""
    out: list[str] = []
    for s in _norm(route).strip("/").split("/"):
        if s == "":
            continue
        out.append("<dyn>" if (s.startswith("[") or s.startswith(":") or "{{" in s) else s)
    return out


def _resolves(target: str, known: list[list[str]]) -> bool:
    tp = _parts(target)
    if not tp:  # "/"
        return True
    for kp in known:
        if len(kp) == len(tp) and all(a == "<dyn>" or a == b for a, b in zip(kp, tp)):
            return True
    return False


def _tokens(seg: str) -> set[str]:
    # Singularise (strip a trailing 's' on tokens >3 chars) so naming drift like
    # `change`/`changes` and `request`/`requests` overlaps.
    out = set()
    for t in re.split(r"[-_]", seg.lower()):
        if not t:
            continue
        out.add(t[:-1] if len(t) > 3 and t.endswith("s") else t)
    return out


# Generic action/leaf words carry no entity meaning — they must not drive a
# naming-drift match (else every `/x/new` collides with every other `/y/new`).
_GENERIC = {"new", "edit", "create", "list", "view", "detail", "index", "add", "id"}


def _entity_sig(route: str) -> set[str]:
    """Tokens of a route's concrete (non-dynamic) segments, minus generic words."""
    sig: set[str] = set()
    for seg in _parts(route):
        if seg != "<dyn>":
            sig |= _tokens(seg) - _GENERIC
    return sig


def repoint(target: str, known_routes: list[str]) -> str | None:
    """Best safe replacement for a dead `navigate` target, or None to neutralize.

    known_routes are concrete route strings (with leading slash, `[id]` form).
    """
    known_parts = [_parts(r) for r in known_routes]
    if _resolves(target, known_parts):
        return target  # already fine

    tp = _parts(target)
    raw = _norm(target)

    # (2) Drop the trailing action segment to the parent — covers `.../edit`
    #     (→ detail), `.../new` (→ list), and any missing action page whose
    #     parent DOES exist. This is the safe, entity-correct fallback.
    if len(tp) >= 2:
        parent = "/" + "/".join(raw.strip("/").split("/")[:-1])
        if _resolves(parent, known_parts):
            return parent

    # (3) naming-drift: the single known route with the most entity-token overlap
    #     (generic action words excluded, so `/x/new` never matches on "new").
    tsig = _entity_sig(target)
    if tsig:
        best, best_score = None, 0.0
        for r in known_routes:
            rs = _entity_sig(r)
            if not rs:
                continue
            score = len(tsig & rs) / len(tsig | rs)
            if score > best_score:
                best, best_score = r, score
        if best is not None and best_score >= 0.5:
            return best

    # (4) neutralize
    return None


def guard_nav_targets(output_dir: str | Path) -> dict:
    """Rewrite dead `navigate` targets across all page schemas. Returns
    {"repointed": n, "neutralized": n, "changes": [(from,to|None)...]}."""
    root = Path(output_dir) / "src" / "schemas"
    result = {"repointed": 0, "neutralized": 0, "changes": []}
    if not root.exists():
        return result

    from services.route_slug import route_from_slug
    known_routes: list[str] = []
    for jf in root.rglob("*.json"):
        slug = str(jf.relative_to(root).with_suffix("")).replace("\\", "/")
        known_routes.append(route_from_slug(slug))

    def walk(node, changed: list) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n, changed)
            return
        if not isinstance(node, dict):
            return
        props = node.get("props")
        if isinstance(props, dict) and isinstance(props.get("navigate"), str):
            tgt = props["navigate"]
            if tgt.startswith("/"):
                new = repoint(tgt, known_routes)
                if new != tgt:
                    changed.append((tgt, new))
                    if new is None:
                        props.pop("navigate", None)
                    else:
                        props["navigate"] = new
        for k in ("children", "root"):
            if k in node:
                walk(node[k], changed)

    for jf in sorted(root.rglob("*.json")):
        try:
            schema = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        changed: list = []
        walk(schema, changed)
        if changed:
            jf.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            for frm, to in changed:
                result["changes"].append((frm, to))
                if to is None:
                    result["neutralized"] += 1
                else:
                    result["repointed"] += 1
    return result
