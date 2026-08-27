"""Deterministic auth-page schema emitter — SP1.5-F4.

Produces valid PageV2 schemas for login and signup pages so the preview
renders a real centered auth card form instead of a data dashboard.

Key design decisions:
  - Uses the same PageV2 root-keyed envelope as page_template_generator.py
    (schemaVersion, id, route, dataSources, root).
  - Form uses declarative mode (fields=[...]) with submitLabel; no workflow
    required because Form.workflow is optional per Form.schema.ts.
  - Password field uses kind="text" because the Form schema discriminated
    union only accepts text/email/number/textarea/select/checkbox/date —
    there is no "password" kind.
  - Card props omit "padding" (not in Card.schema.ts strict schema);
    layout padding is handled via Stack / Container instead.
  - Defensive: emit_auth_page_schemas never raises; failures are swallowed
    and the partial slug list is returned.
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Schema builders ───────────────────────────────────────────────────────────

def build_login_schema() -> dict:
    """Return a PageV2 schema for a centered login card with email + password form."""
    return {
        "schemaVersion": "2",
        "id": "login",
        "route": "/login",
        "dataSources": [],
        "root": _centered_auth_card(
            heading="Sign in",
            subtext="Welcome back. Enter your credentials to continue.",
            form_fields=[
                {"kind": "email", "name": "email",    "label": "Email",    "required": True,
                 "placeholder": "you@company.com"},
                {"kind": "text",  "name": "password", "label": "Password", "required": True,
                 "placeholder": "••••••••"},
            ],
            submit_label="Sign in",
            footer_text="Don't have an account? Sign up",
        ),
    }


def build_signup_schema() -> dict:
    """Return a PageV2 schema for a centered signup card with name, email, password form."""
    return {
        "schemaVersion": "2",
        "id": "signup",
        "route": "/signup",
        "dataSources": [],
        "root": _centered_auth_card(
            heading="Create account",
            subtext="Sign up for a new account to get started.",
            form_fields=[
                {"kind": "text",  "name": "name",     "label": "Full name", "required": True,
                 "placeholder": "Your name"},
                {"kind": "email", "name": "email",    "label": "Email",     "required": True,
                 "placeholder": "you@company.com"},
                {"kind": "text",  "name": "password", "label": "Password",  "required": True,
                 "placeholder": "••••••••"},
            ],
            submit_label="Create account",
            footer_text="Already have an account? Sign in",
        ),
    }


def _build_generic_auth_schema(page: dict) -> dict:
    """Fallback for auth pages that are neither /login nor /signup."""
    name  = page.get("name") or "Sign in"
    route = page.get("route") or "/auth"
    return {
        "schemaVersion": "2",
        "id": _route_to_id(route),
        "route": route,
        "dataSources": [],
        "root": _centered_auth_card(
            heading=name,
            subtext="Enter your credentials to continue.",
            form_fields=[
                {"kind": "email", "name": "email",    "label": "Email",    "required": True,
                 "placeholder": "you@company.com"},
                {"kind": "text",  "name": "password", "label": "Password", "required": True,
                 "placeholder": "••••••••"},
            ],
            submit_label="Sign in",
            footer_text="",
        ),
    }


# ── Layout helpers ────────────────────────────────────────────────────────────

def _centered_auth_card(
    heading: str,
    subtext: str,
    form_fields: list[dict],
    submit_label: str,
    footer_text: str,
) -> dict:
    """Build a vertically + horizontally centred card containing an auth form."""
    inner_children: list[dict] = [
        {"type": "Heading", "props": {"content": heading, "level": 1}},
    ]
    if subtext:
        inner_children.append({"type": "Text", "props": {"content": subtext}})
    inner_children.append({
        "type": "Form",
        "props": {
            "submitLabel": submit_label,
            "fields": form_fields,
        },
    })
    if footer_text:
        inner_children.append({"type": "Text", "props": {"content": footer_text}})

    return {
        "type": "Stack",
        "props": {
            "direction": "vertical",
            "align": "center",
            "justify": "center",
            "gap": "tokens.spacing.6",
        },
        "children": [
            {
                "type": "Card",
                # Card.schema.ts is strict: only title, footer, elevation, style
                "props": {"elevation": "md"},
                "children": [
                    {
                        "type": "Stack",
                        "props": {"direction": "vertical", "gap": "tokens.spacing.4"},
                        "children": inner_children,
                    }
                ],
            }
        ],
    }


# ── File emitter ──────────────────────────────────────────────────────────────

def emit_auth_page_schemas(output_dir: str, plan: Any) -> list[str]:
    """Write deterministic auth schemas for every auth page in plan.pages.

    For each page with type=="auth":
      - Route "/login"  → build_login_schema()
      - Route "/signup" → build_signup_schema()
      - Other auth page → _build_generic_auth_schema(page)

    Writes to <output_dir>/src/schemas/<slug>.json where slug mirrors
    slugify_route() (leading slash stripped, "/" → "/", sub-segments joined
    with "/", then the file is written at that relative path).

    Returns the list of slugs written (e.g. ["login", "signup"]).
    Never raises.
    """
    written: list[str] = []
    try:
        if not plan or not isinstance(plan, dict):
            return written
        pages = plan.get("pages") or []
        for page in pages:
            if not isinstance(page, dict):
                continue
            if (page.get("type") or "").lower() != "auth":
                continue
            route = page.get("route") or ""
            if not route:
                continue
            try:
                slug = _slugify(route)
                schema = _pick_schema(page)
                _write_schema(output_dir, slug, schema)
                written.append(slug)
            except Exception as page_ex:
                logger.warning("[Auth] failed to emit schema for %r: %s", route, page_ex)
    except Exception as outer_ex:
        logger.warning("[Auth] emit_auth_page_schemas aborted: %s", outer_ex)
    return written


# ── Private helpers ───────────────────────────────────────────────────────────

def _pick_schema(page: dict) -> dict:
    route = (page.get("route") or "").lower().rstrip("/")
    # Normalise: strip query/fragment if any (shouldn't happen but defensive)
    route = route.split("?")[0].split("#")[0]
    slug = route.lstrip("/")
    if slug in ("login", "signin", "sign-in"):
        return build_login_schema()
    if slug in ("signup", "sign-up", "register"):
        return build_signup_schema()
    return _build_generic_auth_schema(page)


def _slugify(route: str) -> str:
    """Minimal slug: strip leading slash, collapse repeated slashes.

    Mirrors slugify_route() from services.route_slug but avoids importing
    it to keep this module self-contained (and thus testable without sys.path
    gymnastics).
    """
    if not route or route == "/":
        return "home"
    # Try importing the real slugifier for consistency
    try:
        from services.route_slug import slugify_route
        return slugify_route(route)
    except Exception:
        pass
    # Fallback: manual
    parts = [seg for seg in route.split("/") if seg]
    return "/".join(parts)


def _route_to_id(route: str) -> str:
    slug = _slugify(route)
    return slug.replace("/", "-")


def _write_schema(output_dir: str, slug: str, schema: dict) -> None:
    """Write schema JSON to <output_dir>/src/schemas/<slug>.json."""
    dest = os.path.join(output_dir, "src", "schemas", f"{slug}.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        json.dump(schema, f, indent=2)
