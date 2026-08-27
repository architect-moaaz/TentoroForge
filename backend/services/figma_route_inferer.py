"""Convert a Figma frame name to a clean URL route.

Heuristic pipeline (first match wins):
  1. Strip product / brand / numbering prefixes
  2. Auth patterns (login/signup/forgot/reset)
  3. Home patterns (home/dashboard/overview)
  4. List/detail/form patterns (suffix-driven)
  5. Camel/snake/kebab normalisation as fallback
  6. Numeric "Frame 32" → "/page-32"
  7. Empty / unrecognisable → "/page"

The rules are deliberate and conservative. Tests are the spec.
"""
from __future__ import annotations
import re

_AUTH_RE    = re.compile(r"\b(sign[- ]?in|login)\b", re.I)
_SIGNUP_RE  = re.compile(r"\b(sign[- ]?up|signup|register)\b", re.I)
_FORGOT_RE  = re.compile(r"\bforgot[- ]?password\b", re.I)
_RESET_RE   = re.compile(r"\breset[- ]?password\b", re.I)
_HOME_RE    = re.compile(r"^(home|dashboard|overview|index)$", re.I)

_CAMEL_RE     = re.compile(r"(?<!^)(?=[A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_FRAME_NUM_RE = re.compile(r"^frame\s+(\d+)$", re.I)

# Words to strip when they appear after "screen", "page", etc.
_NOISE_SUFFIX_RE = re.compile(r"\b(screen|page|view)\b", re.I)


def _kebab(s: str) -> str:
    """Convert a token to kebab-case."""
    # Insert hyphens before uppercase letters (camelCase → camel-case)
    s = _CAMEL_RE.sub("-", s)
    s = s.lower()
    s = _NON_ALNUM_RE.sub("-", s).strip("-")
    return s or ""


def _strip_product_prefix(name: str) -> str:
    """For names like 'Commitbiz_intentai_login' or '01 - Login screen',
    return just the meaningful tail."""
    cleaned = name.strip()

    # Strip leading numbering: "01 - Login" → "Login"
    cleaned = re.sub(r"^\d+\s*[-_.]?\s*", "", cleaned).strip()

    # If underscored, strip known brand/product prefix segments and keep the rest
    if "_" in cleaned:
        parts = cleaned.split("_")
        last = parts[-1].lower()
        # Only use the last segment alone if it's an auth keyword (login, signup, etc.)
        # For descriptive words like "settings", keep the context (e.g. user_settings)
        auth_words = {"login", "signin", "signup", "register", "forgot", "reset"}
        if last in auth_words:
            return last
        # If there are many prefix segments (brand prefix pattern), keep last 2
        if len(parts) > 2:
            return "_".join(parts[-2:])
        # Two segments — keep both (e.g. "user_settings" → "user_settings")
        return cleaned

    return cleaned


def infer_route_from_frame_name(name: str) -> str:
    """Convert a Figma frame name into a clean URL route.

    Returns routes like "/login", "/users", "/users/new", "/users/[id]",
    "/users/[id]/edit", "/", or "/page-32" for unrecognised numeric frames.
    """
    raw = (name or "").strip()
    if not raw:
        return "/page"

    # Numeric frame fallback first (so "Frame 32" doesn't kebab-fail)
    m = _FRAME_NUM_RE.match(raw)
    if m:
        return f"/page-{m.group(1)}"

    cleaned = _strip_product_prefix(raw)
    lower = cleaned.lower().strip()

    # Strip noise words like "screen" before matching auth patterns
    # e.g. "Login screen" → check against "Login"
    lower_no_noise = _NOISE_SUFFIX_RE.sub("", lower).strip()

    if _FORGOT_RE.search(lower_no_noise):
        return "/forgot-password"
    if _RESET_RE.search(lower_no_noise):
        return "/reset-password"
    if _SIGNUP_RE.search(lower_no_noise):
        return "/signup"
    # IMPORTANT: auth check must come AFTER signup so "sign up" doesn't match "sign"
    if _AUTH_RE.search(lower_no_noise):
        return "/login"

    if _HOME_RE.match(lower_no_noise.strip()):
        return "/"

    # For structural patterns, use the original cleaned (with noise) to build tokens,
    # but then re-strip noise from individual tokens
    tokens_raw = re.split(r"\s*/\s*|\s+", cleaned)
    parts = []
    for p in tokens_raw:
        k = _kebab(p)
        # Remove noise-only tokens
        if k and k not in {"screen", "page", "view"}:
            parts.append(k)

    # "Users list" / "Users / List" → /users
    if len(parts) >= 2 and parts[-1] in {"list", "index"}:
        return "/" + "-".join(parts[:-1])

    # "New user" / "Create user" → /users/new (prepend "new", entity at end)
    if parts and parts[0] in {"new", "create"}:
        entity = "-".join(parts[1:]) if len(parts) > 1 else "page"
        # Pluralise simple nouns — "new user" → "/users/new"
        if not entity.endswith("s"):
            entity = entity + "s"
        return f"/{entity}/new"

    # "Edit user" / "User edit" → /users/[id]/edit
    if "edit" in parts:
        non_edit = [p for p in parts if p != "edit"]
        entity = "-".join(non_edit) if non_edit else "page"
        if not entity.endswith("s"):
            entity = entity + "s"
        return f"/{entity}/[id]/edit"

    # "User detail" / "User details" → /users/[id]
    if parts and parts[-1] in {"detail", "details"}:
        non_detail = parts[:-1]
        entity = "-".join(non_detail) if non_detail else "page"
        if not entity.endswith("s"):
            entity = entity + "s"
        return f"/{entity}/[id]"

    # Single-token or multi-token fallback — kebab join
    if not parts:
        return "/page"
    return "/" + "-".join(parts)
