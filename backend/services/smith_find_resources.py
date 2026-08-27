"""SMITH-SEARCH-1: single-call resource graph lookup for Smith.

The problem this cures — Smith is asked ``"fix the recruitment drive"`` and
must decide which of 5 pages + 2 workflows + 1 FK-dependent to touch. Today
that traversal takes 6-12 tool calls (read_registry, grep, read each match,
grep for FKs). Each call is a full ReAct round-trip that eats his max_iters
budget; he short-circuits by picking the first plausible file and edits it
(often the wrong one), or by punting with "which screen?".

``find_resources(query)`` collapses the whole traversal into one call that
returns every route, workflow, and FK edge for the matched entity. Smith
gets the same picture the human debugger has, in one turn.

Match strategy (in order):
  1. Exact entity name (``"RecruitmentDrive"``)
  2. Registry-alias hit (uses the same alias map the data engine registers)
  3. Substring / word-set fuzzy match on entity name / table / slug
  4. Route-stem hit (``"drives"`` → RecruitmentDrive via nav-flow)

Confidence is reported so Smith can decide "act" vs "confirm scope first".
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def find_resources(output_dir: str, query: str) -> dict[str, Any]:
    """Return the full graph slice for ``query`` — entity + pages +
    workflows + FKs — as one payload.

    Never raises; missing pieces come back as empty lists so Smith can
    reason about a partial hit ("entity found, no workflows registered"),
    and unknown queries return ``{"matched": None}`` so he knows to ask."""
    if not isinstance(query, str) or not query.strip():
        return {"matched": None, "reason": "empty query"}

    try:
        registry = _load_registry(output_dir)
    except Exception:  # noqa: BLE001
        logger.exception("find_resources: registry load failed")
        return {"matched": None, "reason": "registry unreadable"}

    entities = registry.get("entities") or {}
    if not entities:
        return {"matched": None, "reason": "registry has no entities"}

    match = _match_entity(query, entities, output_dir)
    if match is None:
        return {"matched": None, "query": query, "reason": "no entity matched"}
    entity_name, confidence = match
    entity = entities[entity_name]

    pages = _pages_for(entity_name, entity, output_dir)
    workflows = _workflows_for(entity_name, entity, output_dir)
    fks_out = _fks_out(entity)
    fks_in = _fks_in(entity_name, entity, entities)
    table = entity.get("table")
    slug = entity.get("slug")

    return {
        "matched_entity": entity_name,
        "confidence": confidence,   # "exact" | "alias" | "fuzzy" | "route-stem"
        "table": table,
        "slug": slug,
        "pages": pages,
        "workflows": workflows,
        "fks_out": fks_out,
        "fks_in": fks_in,
        "hint": _one_line_summary(entity_name, pages, workflows, fks_in),
    }


# --------------------------------------------------------------------------- #
# Matchers
# --------------------------------------------------------------------------- #

def _canon(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def _match_entity(
    query: str, entities: dict, output_dir: str,
) -> Optional[tuple[str, str]]:
    """Return (entity_name, confidence) or None. Priority: exact > alias >
    route-stem > fuzzy."""
    q_canon = _canon(query)
    if not q_canon:
        return None

    # (1) exact — entity key or one of its declared forms
    for name, ent in entities.items():
        if not isinstance(ent, dict):
            continue
        forms = [
            name, ent.get("name"), ent.get("table"),
            ent.get("slug"), ent.get("camel"), ent.get("id"),
        ]
        if any(_canon(f) == q_canon for f in forms if f):
            return name, "exact"

    # (2) route-stem — reads nav-flow / schemas for the route↔entity link
    stem_match = _match_by_route_stem(query, entities, output_dir)
    if stem_match is not None:
        return stem_match, "route-stem"

    # (3) fuzzy — token-set containment (query tokens ⊆ entity tokens or v.v.)
    q_tokens = set(_tokens(query))
    if q_tokens:
        best: Optional[tuple[str, int]] = None
        for name in entities:
            e_tokens = set(_tokens(name))
            overlap = len(q_tokens & e_tokens)
            if overlap == 0:
                continue
            score = overlap * 10 + (10 if q_tokens <= e_tokens or e_tokens <= q_tokens else 0)
            if best is None or score > best[1]:
                best = (name, score)
        # Floor is 20, not 10 (register S20-3).
        #
        # `score = overlap * 10 + (10 if containment)`, so a threshold of 10
        # accepted ONE incidental shared token with no containment: the phrase
        # "drive report" — which names no entity — resolved to RecruitmentDrive
        # purely on the word "drive", and Smith then edited that entity
        # confidently. 20 means the match must be justified by either
        # containment (the query IS the entity, e.g. "drive" ⊆
        # {recruitment, drive}) or at least two shared tokens. A single
        # accidental word in common is no longer evidence.
        if best is not None and best[1] >= 20:
            return best[0], "fuzzy"
        if best is not None:
            logger.info(
                "find_resources: %r shares only one token with %r (score %d) — "
                "too weak to resolve; returning no match.",
                query, best[0], best[1],
            )

    return None


def _tokens(s: str) -> list[str]:
    """"RecruitmentDrive" → ["recruitment", "drive"]; "recruitment drive" too."""
    # Split camelCase then non-alnum
    with_boundaries = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(s or ""))
    return [t for t in re.split(r"[^A-Za-z0-9]+", with_boundaries.lower()) if t]


def _match_by_route_stem(
    query: str, entities: dict, output_dir: str,
) -> Optional[str]:
    """The URL slug that user says ("drives") may not match the entity name
    ("RecruitmentDrive"). Look up the route stem via each schema's declared
    ``dataSources[0].entity`` — same logic as HAR-1's route-stem aliaser."""
    q_canon = _canon(query)
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return None
    for sp in schemas_dir.rglob("*.json"):
        if sp.name in ("registry.json", "shell.json", "nav-flow.json"):
            continue
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        sources = doc.get("dataSources") if isinstance(doc, dict) else None
        if not isinstance(sources, list) or not sources:
            continue
        focal = next(
            (s.get("entity") for s in sources
             if isinstance(s, dict) and isinstance(s.get("entity"), str)),
            None,
        )
        if not focal or focal not in entities:
            continue
        rel = sp.relative_to(schemas_dir)
        stem = rel.parts[0] if len(rel.parts) > 1 else rel.stem
        if _canon(stem) == q_canon:
            return focal
    return None


# --------------------------------------------------------------------------- #
# Graph slice
# --------------------------------------------------------------------------- #

def _pages_for(entity_name: str, entity: dict, output_dir: str) -> list[dict]:
    """Return ONLY primary pages for ``entity_name`` — pages whose FIRST
    dataSource is this entity, OR whose file path lives under the entity's
    slug directory, OR which the plan explicitly links to this entity
    (``plan.pages[].entity``).

    Deliberately excludes pages that merely REFERENCE the entity via a
    secondary dataSource (a dashboard/report reading candidate counts is
    NOT a "candidate profile page"). Over-inclusion here is what made
    Smith see 15 pages and punt on a straight-forward Candidate ask.

    Every returned page carries an optional ``name`` field (from
    ``plan.pages[].name`` when present) — the scope-check formatter uses
    it as the layman-facing label so users see "Candidate Apply Wizard"
    rather than "(create)".
    """
    # Load the plan once so we can (a) map route → name, and (b) discover
    # entity-linked pages the path/dataSource passes miss (e.g. /apply
    # for CandidateProfile — no dataSource, not under the entity slug).
    plan_pages_by_route, plan_entity_routes = _load_plan_page_index(
        output_dir, entity_name,
    )
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return []
    # Slug candidates for the entity's own directory ("candidate-profiles",
    # "candidateprofile"). A page under that directory is primary regardless
    # of its dataSource order.
    # Slug candidates for the entity's own directory. We also include a
    # short form ("candidates" from "candidate-profiles") so the common
    # user-friendly route ("/candidates") matches its entity.
    slug_forms: set[str] = set()
    for f in (entity_name, entity.get("slug"), entity.get("table"), entity.get("camel")):
        if f:
            slug_forms.add(_canon(f))
    # Short-noun form: "candidate-profiles" → "candidates" (drop trailing
    # "profile"/"profiles"). Handles the recruiting-app convention of
    # short route names for long entity names.
    for extra in _short_forms(entity_name, entity):
        slug_forms.add(_canon(extra))

    # Pass 1: primary-by-path. Any schema whose top directory (or top-
    # level file stem) canonicalizes to one of the entity's slug forms.
    primary: list[dict] = []
    for sp in sorted(schemas_dir.rglob("*.json")):
        if sp.name in ("registry.json", "shell.json", "nav-flow.json"):
            continue
        rel = sp.relative_to(schemas_dir)
        top_stem = _canon(rel.parts[0] if len(rel.parts) > 1 else rel.stem)
        if top_stem not in slug_forms:
            continue
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = doc.get("route") or ""
        primary.append({
            "route": route,
            "schema_path": f"src/schemas/{rel}",
            "kind": _classify_page(str(rel), route, plan_pages_by_route.get(route)),
            "name": plan_pages_by_route.get(route),
        })

    # Pass 2: dataSource-order match — catches entities without a
    # dedicated route (e.g. Notification), where the "pages" list is
    # legitimately every consumer. Additive; dedupes against pass 1.
    seen_routes: set[str] = {p["route"] for p in primary if p.get("route")}
    for sp in sorted(schemas_dir.rglob("*.json")):
        if sp.name in ("registry.json", "shell.json", "nav-flow.json"):
            continue
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        sources = doc.get("dataSources") if isinstance(doc, dict) else None
        if not isinstance(sources, list) or not sources:
            continue
        first = sources[0] if isinstance(sources[0], dict) else {}
        if first.get("entity") != entity_name:
            continue
        rel = sp.relative_to(schemas_dir)
        route = doc.get("route") or ""
        if route in seen_routes:
            continue
        primary.append({
            "route": route,
            "schema_path": f"src/schemas/{rel}",
            "kind": _classify_page(str(rel), route, plan_pages_by_route.get(route)),
            "name": plan_pages_by_route.get(route),
        })
        seen_routes.add(route)

    # Pass 3: plan-linked routes — the plan explicitly declares
    # ``page.entity = <this entity>`` even though the schema on disk has
    # no matching slug directory and no dataSources at all (e.g. a
    # wizard/multi-step form). Without this, "add candidate" asks would
    # never see /apply and the layman is stuck picking between list/
    # detail rows that don't answer the ask.
    for plan_route in plan_entity_routes:
        if plan_route in seen_routes:
            continue
        # Locate the schema file for this route so read_page can find it.
        schema_rel = _route_to_schema_rel(plan_route, schemas_dir)
        primary.append({
            "route": plan_route,
            "schema_path": (f"src/schemas/{schema_rel}"
                            if schema_rel else None),
            "kind": _classify_page(schema_rel or "", plan_route, plan_pages_by_route.get(plan_route)),
            "name": plan_pages_by_route.get(plan_route),
        })
        seen_routes.add(plan_route)

    return primary


def _load_plan_page_index(
    output_dir: str, entity_name: str,
) -> tuple[dict[str, str], list[str]]:
    """Read ``src/contracts/plan.json`` once and return
    ``(route → name, [route where page.entity == entity_name])``.

    Both empty on any read/parse failure — this is best-effort context
    enrichment; find_resources must never fail because plan.json is
    missing or malformed."""
    plan_path = Path(output_dir) / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return {}, []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}, []
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return {}, []
    by_route: dict[str, str] = {}
    entity_routes: list[str] = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        route = p.get("route")
        if not isinstance(route, str) or not route:
            continue
        name = p.get("name")
        if isinstance(name, str) and name.strip():
            by_route[route] = name
        if p.get("entity") == entity_name:
            entity_routes.append(route)
    return by_route, entity_routes


def _route_to_schema_rel(route: str, schemas_dir: Path) -> str | None:
    """Best-effort mapping ``/apply`` → ``apply.json`` (or
    ``candidates/new.json`` for ``/candidates/new``). Returns ``None``
    when no matching file exists — the scope-check tolerates a missing
    schema_path (read_page will just fail politely later)."""
    if not route or route == "/":
        return None
    parts = [p for p in route.strip("/").split("/") if p]
    if not parts:
        return None
    # Try nested layout first (e.g. /candidates/new → candidates/new.json)
    nested = schemas_dir / "/".join(parts[:-1]) / f"{parts[-1]}.json"
    if nested.is_file():
        return str(nested.relative_to(schemas_dir))
    # Fall back to a flat file (/apply → apply.json)
    flat = schemas_dir / f"{'/'.join(parts)}.json"
    if flat.is_file():
        return str(flat.relative_to(schemas_dir))
    return None


def _short_forms(entity_name: str, entity: dict) -> list[str]:
    """Common user-facing shortenings of an entity name.

    ``CandidateProfile`` → ``candidates``, ``candidate``.
    ``RecruitmentDrive`` → ``drives``, ``drive``.
    Handles the pattern where the LLM picks a shorter, natural route stem
    than the entity's PascalCase name — the route ``/candidates`` for
    ``CandidateProfile``, ``/drives`` for ``RecruitmentDrive``.
    """
    out: list[str] = []
    tokens = _tokens(entity_name)
    if not tokens:
        return out
    # First noun as the short form: "recruitment drive" → "drive" (last),
    # "candidate profile" → "candidate" (first). Try both.
    for t in {tokens[0], tokens[-1]}:
        out.append(t)
        # naive plural
        if t.endswith("s"):
            out.append(t[:-1])
        else:
            out.append(t + "s")
    return out


def _classify_page(rel_path: str, route: str, name: str | None = None) -> str:
    r = (route or "").lower()
    p = rel_path.lower()
    if p.endswith("/new.json") or r.endswith("/new"):
        return "create"
    if p.endswith("/edit.json") or r.endswith("/edit"):
        return "edit"
    if "[id]" in p or ":id" in r:
        return "detail"
    # URL alone was ambiguous — use plan.pages[].name as a hint.
    # E.g. "/apply" with name "CandidateApplyWizardPage" is a create
    # flow even though nothing in the URL says so.
    n = (name or "").lower()
    if any(k in n for k in ("wizard", "apply", "signup", "sign-up",
                             "register", "onboard", "intake",
                             "create", "new")):
        return "create"
    if any(k in n for k in ("edit", "update", "modify")):
        return "edit"
    if "detail" in n or "profile" in n:
        return "detail"
    return "list"


def _workflows_for(entity_name: str, entity: dict, output_dir: str) -> list[dict]:
    """Every workflow JSON that names ``entity_name`` in a db_insert/
    db_update/db_delete config's ``entity`` or ``table`` field."""
    wf_dir = Path(output_dir) / "workflows"
    if not wf_dir.exists():
        return []
    table = entity.get("table")
    out: list[dict] = []
    for fp in sorted(wf_dir.glob("*.json")):
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        defn = doc.get("definition") if isinstance(doc.get("definition"), dict) else doc
        nodes = defn.get("nodes") if isinstance(defn, dict) else None
        if not isinstance(nodes, list):
            nodes = doc.get("nodes") if isinstance(doc.get("nodes"), list) else []
        hit = False
        for n in nodes:
            if not isinstance(n, dict):
                continue
            cfg = ((n.get("data") or {}).get("config")) or n.get("config") or {}
            if not isinstance(cfg, dict):
                continue
            if (cfg.get("entity") == entity_name
                or (table and cfg.get("table") == table)):
                hit = True
                break
        if hit:
            out.append({
                "name": doc.get("name") or fp.stem,
                "path": f"workflows/{fp.name}",
            })
    return out


def _fks_out(entity: dict) -> list[dict]:
    """FKs declared ON the entity's own columns (points OUT to a target)."""
    out: list[dict] = []
    for c in (entity.get("columns") or []):
        if not isinstance(c, dict):
            continue
        target = c.get("fk") or (
            c.get("references") if isinstance(c.get("references"), str) else None
        )
        if target:
            out.append({"column": c.get("name"), "target": str(target)})
    return out


def _fks_in(entity_name: str, entity: dict, entities: dict) -> list[dict]:
    """FKs pointing IN — other entities' columns that reference this one.
    The dependents; deleting or renaming this entity affects them."""
    my_id = entity.get("id") or entity_name
    my_table = entity.get("table")
    out: list[dict] = []
    for other_name, other in entities.items():
        if other_name == entity_name or not isinstance(other, dict):
            continue
        for c in (other.get("columns") or []):
            if not isinstance(c, dict):
                continue
            target = str(c.get("fk") or c.get("references") or "")
            if not target:
                continue
            if target == my_id or target == my_table or _canon(target) == _canon(entity_name):
                out.append({
                    "from": f"{other_name}.{c.get('name')}",
                    "table": other.get("table"),
                })
    return out


def _one_line_summary(
    entity_name: str, pages: list, workflows: list, fks_in: list,
) -> str:
    parts = [entity_name, f"{len(pages)} page(s)", f"{len(workflows)} workflow(s)"]
    if fks_in:
        parts.append(f"{len(fks_in)} dependent(s): "
                     + ", ".join(sorted({f['from'].split('.')[0] for f in fks_in})))
    return " · ".join(parts)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _load_registry(output_dir: str) -> dict:
    for rel in ("contracts/resource-registry.json", "registry.json"):
        p = Path(output_dir) / rel
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and isinstance(data.get("entities"), dict):
            return data
    return {}
