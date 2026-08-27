"""Infer button workflows / navigation targets from Figma Dev Mode labels.

Heuristic rules used during the JSX→PageV2 transform. Best-effort: when a
label clearly indicates an action ("Sign in", "Reset Filters") or a route
("Dashboard", "Settings"), emit the corresponding `workflow` or `navigate`
prop. Unknown labels are left alone — the button stays clickable but inert.
"""
from __future__ import annotations
import re

# Auth / session actions.
# Sign-in / Sign-up / Sign-out emit ONLY the workflow prop — no hardcoded
# navigate path. The workflow runtime reads nav-flow's post_login_redirect /
# post_logout_redirect and routes appropriately so schemas stay project-agnostic.
_AUTH_PATTERNS: list[tuple[re.Pattern, dict]] = [
    (re.compile(r"^sign\s*in$|^log\s*in$", re.I), {"workflow": "auth.signIn"}),
    (re.compile(r"^sign\s*up$|^register$|^create\s+account$", re.I), {"workflow": "auth.signUp"}),
    (re.compile(r"^sign\s*out$|^log\s*out$|^logout$", re.I), {"workflow": "auth.signOut"}),
    (re.compile(r"^forgot.+password", re.I), {"navigate": "/forgot-password"}),
    (re.compile(r"^reset.+password", re.I), {"navigate": "/reset-password"}),
]

# Form actions
_FORM_PATTERNS: list[tuple[re.Pattern, dict]] = [
    (re.compile(r"^reset(\s+filters)?$", re.I), {"workflow": "filters.reset"}),
    (re.compile(r"^apply(\s+filters)?$", re.I), {"workflow": "filters.apply"}),
    (re.compile(r"^submit$|^save$", re.I), {"workflow": "form.submit"}),
    (re.compile(r"^cancel$", re.I), {"workflow": "form.cancel"}),
    (re.compile(r"^delete$", re.I), {"workflow": "item.delete"}),
]

# Known nav-tab labels → routes
_NAV_LABELS: dict[str, str] = {
    "dashboard": "/dashboard",
    "settings": "/settings",
    "analytics": "/analytics",
    "leads": "/leads",
    "intent intelligence": "/intent-intelligence",
    "outreach automation": "/outreach-automation",
    "outreach": "/outreach",
    "inbox": "/inbox",
    "messages": "/messages",
    "profile": "/profile",
    "notifications": "/notifications",
    "billing": "/billing",
    "team": "/team",
    "integrations": "/integrations",
    "help": "/help",
    "home": "/",
}


def classify_button_action(label: str, data_name: str = "", className: str = "") -> dict:
    """Return {workflow?: str, navigate?: str} for the given Button.

    Empty dict means "no inference" — caller leaves the Button as-is.
    """
    if not label:
        return {}
    norm = label.strip().lower()

    # Auth / session
    for pat, action in _AUTH_PATTERNS:
        if pat.search(label):
            return dict(action)

    # Form actions
    for pat, action in _FORM_PATTERNS:
        if pat.search(label):
            return dict(action)

    # Nav labels (exact match against known canonical paths)
    if norm in _NAV_LABELS:
        return {"navigate": _NAV_LABELS[norm]}

    # "View Analytics" / "View Context" → either a nav target if the
    # second word maps, else a workflow.
    view_match = re.match(r"^view\s+(.+)$", label, re.I)
    if view_match:
        rest = view_match.group(1).strip().lower()
        if rest in _NAV_LABELS:
            return {"navigate": _NAV_LABELS[rest]}
        return {"workflow": f"view.{_slugify(rest)}"}

    # Default: assume an action workflow keyed by the slugified label
    return {"workflow": _slugify(label)}


def infer_input_name(data_name: str, type_: str, placeholder: str = "") -> str | None:
    """Infer a sensible `name` for an Input from Figma name + type."""
    if data_name:
        m = re.match(r"(.+?)\s+input$", data_name, re.I)
        if m:
            return _camel(m.group(1))
    # Type-based fallback
    if type_ == "email":
        return "email"
    if type_ == "password":
        return "password"
    if type_ == "number":
        return "amount"
    if placeholder:
        return _slugify(placeholder.split()[0])
    return None


def _camel(text: str) -> str:
    """camelCase without dots: 'Phone Number' → 'phoneNumber'."""
    words = re.split(r"\W+", text.strip())
    words = [w for w in words if w]
    if not words:
        return ""
    head = words[0].lower()
    tail = "".join(w[:1].upper() + w[1:].lower() for w in words[1:])
    return head + tail


def _slugify(text: str) -> str:
    """Compact slugify: 'Convert to Lead' → 'convert.toLead'.

    Head word is always lowercased. Remaining words are joined without any
    case transformation (preserving their original casing), so stop words
    like "to" stay lowercase and capitalised words like "Lead" stay titlecased.
    The head and tail are separated by a single dot.
    """
    words = re.split(r"\W+", text.strip())
    words = [w for w in words if w]
    if not words:
        return ""
    head = words[0].lower()
    if len(words) == 1:
        return head
    tail = "".join(words[1:])
    return f"{head}.{tail}"
