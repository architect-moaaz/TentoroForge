"""Auto-place cart UI components on pages for commerce-flagged entities.

Reads the plan for entities marked ``commerce: true`` (see
:mod:`services.commerce_flag`) and edits the generated app to surface the cart
runtime primitive:

  1. On the LIST page of each commerce entity — inject an ``AddToCart`` button
     into each row's action column (per-row so shoppers can add without
     opening the detail).
  2. On the DETAIL page of each commerce entity — inject an ``AddToCart`` CTA
     into the primary action slot.
  3. Ensure a ``/cart`` route exists using the ``CartPage`` library node. If
     the schema file is missing, create it; if present, leave it alone.
  4. Inject a ``CartBadge`` into the shell menu (nav_flow / shell) so shoppers
     always see the count.

All edits are additive + idempotent — safe to run in every post-gen pass. If a
commerce entity has no list/detail page, that step silently no-ops. The pass
NEVER creates new entities; the runtime primitive already provides `forge_cart`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------- discovery ------------------------------------------------------

def _load_plan(output_dir: Path) -> dict:
    for candidate in (
        output_dir / "src" / "contracts" / "plan.json",
        output_dir / "contracts" / "plan.json",
    ):
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("commerce_placement: failed to read %s", candidate)
    return {}


def _commerce_entities(plan: dict) -> list[str]:
    """Names of entities marked commerce:true in the plan."""
    entities = plan.get("entities") or {}
    if not isinstance(entities, dict):
        return []
    out: list[str] = []
    for name, spec in entities.items():
        if isinstance(spec, dict) and spec.get("commerce") is True:
            out.append(name)
    return out


def _plan_pages_for_entity(plan: dict, entity: str) -> list[dict]:
    """Every plan page whose entity matches (case-insensitive)."""
    lc = entity.strip().lower()
    result: list[dict] = []
    for p in plan.get("pages") or []:
        if not isinstance(p, dict):
            continue
        pe = str(p.get("entity") or "").strip().lower()
        if pe == lc:
            result.append(p)
    return result


def _slug_from_route(route: str) -> str:
    """Same convention as services.route_slug.slugify_route (light copy so this
    module has no external service dependency)."""
    r = (route or "").strip("/").replace("/", "-")
    r = r.replace("[", "").replace("]", "")
    return r or "home"


# ---------- schema editing ------------------------------------------------

def _iter_nodes(node: Any):
    """Yield every dict node in the (possibly nested) schema tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_nodes(item)


def _has_addtocart_for(node_root: Any, entity: str) -> bool:
    """True if any AddToCart node in the schema already targets this entity."""
    lc = entity.strip().lower()
    for n in _iter_nodes(node_root):
        if not isinstance(n, dict):
            continue
        if n.get("type") == "AddToCart":
            props = n.get("props") or {}
            if isinstance(props, dict) and str(props.get("entity") or "").strip().lower() == lc:
                return True
    return False


def _make_addtocart_node(entity: str, item_id_binding: str = "{{row.id}}",
                          price_binding: str = "{{row.price}}",
                          label_binding: str = "{{row.name}}",
                          size: str = "sm", text: str = "Add") -> dict:
    """Produce a single AddToCart schema node bound to a row context."""
    return {
        "type": "AddToCart",
        "props": {
            "entity": entity,
            "itemId": item_id_binding,
            "price": price_binding,
            "label": label_binding,
            "size": size,
            "text": text,
            "variant": "primary",
        },
    }


def _inject_addtocart_into_list(page_root: dict, entity: str) -> bool:
    """List pages: append an AddToCart to any Table/DataGrid's row-action
    slot, if it isn't already there. Returns True when the schema changed."""
    if _has_addtocart_for(page_root, entity):
        return False
    changed = False
    for n in _iter_nodes(page_root):
        if not isinstance(n, dict):
            continue
        if n.get("type") not in ("Table", "DataGrid", "List"):
            continue
        props = n.setdefault("props", {})
        if not isinstance(props, dict):
            continue
        actions = props.get("rowActions")
        if not isinstance(actions, list):
            actions = []
        actions.append(_make_addtocart_node(entity))
        props["rowActions"] = actions
        changed = True
        break  # only the first table gets the injection
    return changed


def _inject_addtocart_into_detail(page_root: dict, entity: str) -> bool:
    """Detail pages: append an AddToCart CTA to the page's top-level
    action row (or content) so shoppers can add from the detail view."""
    if _has_addtocart_for(page_root, entity):
        return False
    # Prefer a top-level Card, Section, Hero, or Row.
    nodes = page_root.get("nodes") or page_root.get("children") or []
    if not isinstance(nodes, list):
        return False
    cta = _make_addtocart_node(
        entity,
        item_id_binding="{{record.id}}",
        price_binding="{{record.price}}",
        label_binding="{{record.name}}",
        size="md",
        text="Add to cart",
    )
    # Wrap in a Row so the layout stays predictable.
    nodes.append({
        "type": "Row",
        "props": {"gap": "md", "align": "center"},
        "children": [cta],
    })
    if "nodes" in page_root:
        page_root["nodes"] = nodes
    else:
        page_root["children"] = nodes
    return True


# ---------- /cart route + shell nav ---------------------------------------

_CART_ROUTE = "/cart"
_CART_SLUG = "cart"

def _ensure_cart_page(output_dir: Path) -> bool:
    """Emit src/schemas/cart.json if it's missing. Idempotent."""
    schemas_dir = output_dir / "src" / "schemas"
    if not schemas_dir.exists():
        return False
    cart_path = schemas_dir / f"{_CART_SLUG}.json"
    if cart_path.exists():
        return False
    payload = {
        "id": _CART_SLUG,
        "route": _CART_ROUTE,
        "type": "static",
        "nodes": [
            {"type": "CartPage", "props": {
                "title": "Your cart",
                "currency": "USD",
                "checkoutLabel": "Place order",
                "onCheckoutNavigate": "/orders",
            }},
        ],
    }
    cart_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return True


def _ensure_cart_page_in_plan(plan_path: Path, plan: dict) -> bool:
    """Add a /cart entry to plan.pages if it isn't already present."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return False
    for p in pages:
        if isinstance(p, dict) and str(p.get("route") or "").strip().rstrip("/") == _CART_ROUTE:
            return False
    pages.append({
        "route": _CART_ROUTE,
        "name": "Cart",
        "type": "static",
        "entity": None,
        "description": "Shopping cart with subtotal, quantity controls, and checkout.",
    })
    try:
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return True
    except Exception:
        logger.exception("commerce_placement: failed to write plan.json cart page")
        return False


def _inject_cart_badge_into_shell(output_dir: Path) -> bool:
    """Add a CartBadge to the app shell's menu when a shell.json exists.
    The badge is placed as a menu item; downstream shell_menu_sync tolerates
    it because CartBadge is a registered library component."""
    for candidate in (
        output_dir / "src" / "contracts" / "shell.json",
        output_dir / "contracts" / "shell.json",
    ):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        menu = data.get("menu")
        if not isinstance(menu, list):
            continue
        # Idempotent — bail if we already added one.
        for item in menu:
            if isinstance(item, dict) and str(item.get("label") or "").strip().lower() == "cart":
                return False
        menu.append({
            "label": "Cart",
            "route": _CART_ROUTE,
            "icon": "shopping-cart",
        })
        try:
            candidate.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return True
        except Exception:
            logger.exception("commerce_placement: failed to write shell.json")
            return False
    return False


# ---------- entry point ---------------------------------------------------

def apply_commerce_placement(output_dir: str) -> dict:
    """Main entry — call from post_generate_fixes. Returns a small dict of
    counts for the log line. Never raises."""
    root = Path(output_dir)
    plan_path = root / "src" / "contracts" / "plan.json"
    plan = _load_plan(root)
    entities = _commerce_entities(plan)
    result = {"entities": entities, "list_edits": 0, "detail_edits": 0,
              "cart_page_created": False, "cart_in_plan": False, "shell_badge": False}
    if not entities:
        return result

    schemas_dir = root / "src" / "schemas"

    for entity in entities:
        for page in _plan_pages_for_entity(plan, entity):
            route = page.get("route") or ""
            page_type = str(page.get("type") or "").lower()
            slug = _slug_from_route(route)
            schema_path = schemas_dir / f"{slug}.json"
            if not schema_path.exists():
                continue
            try:
                page_schema = json.loads(schema_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            changed = False
            if page_type == "list" or route.rstrip("/").endswith(entity.lower() + "s") or route.rstrip("/").endswith(entity.lower()):
                if _inject_addtocart_into_list(page_schema, entity):
                    result["list_edits"] += 1
                    changed = True
            if page_type == "detail" or "[id]" in route:
                if _inject_addtocart_into_detail(page_schema, entity):
                    result["detail_edits"] += 1
                    changed = True

            if changed:
                try:
                    schema_path.write_text(json.dumps(page_schema, indent=2), encoding="utf-8")
                except Exception:
                    logger.exception("commerce_placement: failed to write %s", schema_path)

    # /cart route + plan entry + shell badge.
    if _ensure_cart_page(root):
        result["cart_page_created"] = True
    if plan_path.exists() and _ensure_cart_page_in_plan(plan_path, plan):
        result["cart_in_plan"] = True
    if _inject_cart_badge_into_shell(root):
        result["shell_badge"] = True

    return result
