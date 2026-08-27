"""Wire list-page tables to open the row's detail view.

A generated list page (src/schemas/<entity>.json) renders a Table of the entity's
rows, and the app has a detail route (src/schemas/<entity>/[id].json) that opens as
a drawer overlay via AppNavigator. But the schema agent often omits the Table's
`rowHref`, so clicking a row does nothing — the detail drawer never opens.

The Table component navigates on row click when `rowHref` is set (it applies the
row as a template: rowHref="/entity/{{id}}" -> nav.push("/entity/<row id>")). This
guard sets that rowHref on the list's own entity table whenever a matching detail
route exists and the table doesn't already navigate. It only touches a table whose
`rows` binding references the page's own entity (so a secondary/related table on the
page isn't mis-pointed at the wrong detail route). Deterministic + idempotent.
"""
from __future__ import annotations

import glob
import json
import os
import re

from services.entity_names import singularize
from services.semantic_field_types import _iter_nodes


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _singularish(s: str) -> str:
    """Fold a binding/entity name to singular for matching.

    Delegates to :func:`services.entity_names.singularize` — the single
    naming authority. The local rules handled `ies → y` but not
    `es`, so `addresses` folded to `addresse` and never matched
    `address`; the row-nav guard then left that table's rows unlinked."""
    return singularize(_norm(s))


def _rows_entity(node: dict) -> str | None:
    """The entity/dataSource a Table's `rows` binding points at, e.g. {{reservations}}."""
    rows = (node.get("props") or {}).get("rows")
    if isinstance(rows, str):
        m = re.fullmatch(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", rows.strip())
        if m:
            return m.group(1)
    return None


def _rows_matches_page(re_ent: str, entity: str, ent_keys: set[str]) -> bool:
    """Does a table's rows source belong to this page's entity? Exact/singular
    match, or a prefix — the route slug is often a shorter stem of the source
    (maintenance ⊂ maintenanceOrders). Prefix requires a ≥4-char stem to avoid
    short-name false positives."""
    re_n = _norm(re_ent)
    sing = _singularish(re_ent)
    if re_n in ent_keys or sing in ent_keys:
        return True
    ent_n = _norm(entity)
    if len(ent_n) >= 4 and (re_n.startswith(ent_n) or ent_n.startswith(sing)):
        return True
    return False


def _detail_slugs(sdir: str) -> dict[str, str]:
    """Map normed-slug -> original dir name for every registered detail route
    (`src/schemas/<slug>/[id].json`). This is the set of `/slug/[id]` routes the
    `[entity]/[id]` catch-all will actually render — a rowHref that points anywhere
    else `notFound()`s (the 404-on-row-click defect)."""
    out: dict[str, str] = {}
    for fp in glob.glob(os.path.join(sdir, "*", "[[]id[]].json")):
        slug = os.path.basename(os.path.dirname(fp))
        out[_norm(slug)] = slug
    return out


def _match_registered(name: str, detail_slugs: dict[str, str]) -> str | None:
    """Resolve a data-source name (e.g. `rentals`, `applicantsRecent`) to a
    registered detail-route slug — exact, singular, or ≥4-char prefix stem — so a
    wrong rowHref can be REPOINTED at the row's real detail route. Returns the
    original slug (route casing) or None."""
    if not name:
        return None
    n = _norm(name)
    sing = _singularish(name)
    if n in detail_slugs:
        return detail_slugs[n]
    if sing in detail_slugs:
        return detail_slugs[sing]
    for norm_slug, orig in detail_slugs.items():
        if len(norm_slug) >= 4 and (n.startswith(norm_slug) or norm_slug.startswith(sing)):
            return orig
    return None


def _href_slug_and_tail(href: str) -> tuple[str | None, str]:
    """Split a rowHref `/slug/{id}` into (slug, tail). `tail` keeps the caller's
    brace style (`{id}` vs `{{id}}`) so a repoint preserves it. `/slug` alone -> tail=''."""
    if not isinstance(href, str):
        return None, ""
    m = re.match(r"^/+([^/]+)(?:/(.*))?$", href.strip())
    if not m:
        return None, ""
    return m.group(1), (m.group(2) or "")


def guard_table_row_nav(output_dir: str) -> dict:
    """Wire + VALIDATE list-page table row navigation. Returns {wired, files}.

    For every Table/DataTable on a top-level page:
    - no rowHref: ADD `/<entity>/{{id}}` when the page's own entity has a detail
      route and the table's rows bind to that entity (original behavior).
    - has rowHref: VALIDATE it against real `/slug/[id]` detail routes. A correct
      one is left untouched (idempotent). A WRONG one (slug with no detail route —
      e.g. a page-slug-derived `/overdue/{id}` when only `/rentals/[id]` exists) is
      REPOINTED to the row's data entity when that entity has a detail route, else
      STRIPPED so the rows render non-navigable instead of 404-ing.
    Never raises.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"wired": 0, "files": 0, "asserts_logged": 0}

    detail_slugs = _detail_slugs(sdir)

    # Phase 6a (Collection Authority) — composer-authored schemas run
    # in ASSERT-only mode; the composer's rowHref decisions are the
    # authority. Log drift, don't rewrite.
    from services.artifact_authority import should_assert_only_any as should_assert_only

    wired = touched = 0
    asserts_logged = 0
    for fp in glob.glob(os.path.join(sdir, "*.json")):  # top-level list pages only
        entity = os.path.splitext(os.path.basename(fp))[0]
        if entity in ("shell", "home"):
            continue
        try:
            schema = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if should_assert_only(schema):
            asserts_logged += 1
            continue
        ent_keys = {_norm(entity), _singularish(entity)}
        page_has_detail = _norm(entity) in detail_slugs
        changed = 0
        for node in _iter_nodes(schema):
            if not isinstance(node, dict) or node.get("type") not in ("Table", "DataTable"):
                continue
            props = node.setdefault("props", {})
            re_ent = _rows_entity(node)
            existing = props.get("rowHref")

            if isinstance(existing, str) and existing.strip():
                # VALIDATE an existing rowHref against the real detail routes.
                slug, tail = _href_slug_and_tail(existing)
                if slug and _norm(slug) in detail_slugs:
                    continue  # correct target — leave unchanged (idempotent)
                # Wrong target: repoint to the row's data entity if it has a detail
                # route, else strip so the row is non-navigable (never a 404).
                target = _match_registered(re_ent, detail_slugs) if re_ent else None
                if target:
                    props["rowHref"] = f"/{target}/{tail}" if tail else f"/{target}/{{{{id}}}}"
                else:
                    props.pop("rowHref", None)
                changed += 1
                continue

            # No rowHref: ADD one for the page's OWN entity table. Match the rows
            # source to the page route: exact/singular, OR a prefix — the route slug
            # is often shorter than the source name (`/maintenance` lists
            # `{{maintenanceOrders}}`), which the exact match missed, leaving rows
            # dead and the detail drawer unopenable. Only when a detail route exists.
            if page_has_detail and re_ent and _rows_matches_page(re_ent, entity, ent_keys):
                row_key = props.get("rowKey") or "id"
                props["rowHref"] = f"/{entity}/{{{{{row_key}}}}}"
                changed += 1
        if changed:
            touched += 1
            wired += changed
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
    return {"wired": wired, "files": touched, "asserts_logged": asserts_logged}
