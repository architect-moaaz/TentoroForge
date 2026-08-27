"""Semantic-prefix decoder for the read-binding contract.

Pure functions, no I/O. A generated binding token like ``activeRecruitmentDrives``
encodes both a base entity (``recruitmentDrives``) and a *derived-view intent*
(``active``). These helpers split that prefix off and, given the entity's REAL
column metadata, decode the intent into a concrete ``{filter, sort, limit}``
view spec — emitting only the keys that actually apply to the columns present.

Nothing here is invented: a status filter is only produced when a real status
column with a matching enum value exists; a sort is only produced when a real
date/numeric column exists.
"""

# Known semantic prefixes, longest-first so e.g. "completed" wins over "complete"
# would-be shorter matches. Each must be followed by an uppercase letter in the
# token to count as a prefix.
_PREFIXES = [
    "completed",
    "upcoming",
    "pending",
    "closed",
    "recent",
    "latest",
    "active",
    "open",
    "new",
    "top",
]

# Date columns, in priority order, for "most recent" style prefixes.
_RECENT_DATE_COLS = ["createdAt", "created_at", "insertedAt"]
# Date columns, in priority order, for "upcoming/future" style prefixes.
_FUTURE_DATE_COLS = ["startsAt", "scheduledAt", "dueAt", "startDate", "date"]

# Status-like column names (lowercased) that may carry an enum lifecycle value.
_STATUS_COL_NAMES = {"status", "state", "stage"}

# prefix -> ordered list of case-insensitive tokens to match against enum members.
_STATUS_VALUE_TOKENS = {
    "active": ["active", "open"],
    "open": ["open", "active"],
    "pending": ["pending"],
    "closed": ["closed"],
    "completed": ["completed", "done"],
}

# Substrings that mark a column type as numeric.
_NUMERIC_TYPE_HINTS = ("int", "numeric", "decimal", "real")

_LIMIT = 5


def strip_prefix(token: str) -> tuple[str, str]:
    """Split a leading semantic prefix from a camelCase binding token.

    Returns ``(prefix_lower, remainder)`` where ``remainder`` has its leading
    character lowercased. A prefix only counts when it is immediately followed
    by an uppercase letter (so ``newsFeed`` does NOT match ``new``). No prefix
    yields ``("", token)``.
    """
    if not token:
        return "", token
    low = token.lower()
    for pref in _PREFIXES:
        if len(token) > len(pref) and low.startswith(pref):
            nxt = token[len(pref)]
            if nxt.isupper():
                remainder = nxt.lower() + token[len(pref) + 1:]
                return pref, remainder
    return "", token


def _find_status_col(cols: dict) -> tuple[str, list] | None:
    """Return (colName, enumValues) for the first status-like enum column."""
    for name, meta in cols.items():
        if not isinstance(meta, dict):
            continue
        if name.lower() in _STATUS_COL_NAMES:
            enum = meta.get("enum")
            if isinstance(enum, list) and enum:
                return name, enum
    return None


def _match_enum_value(prefix: str, enum: list) -> str | None:
    """Case-insensitive match of a prefix's status tokens against enum members."""
    tokens = _STATUS_VALUE_TOKENS.get(prefix)
    if not tokens:
        return None
    for tok in tokens:
        for member in enum:
            if isinstance(member, str) and tok in member.lower():
                return member
    return None


def _first_present(cols: dict, candidates: list) -> str | None:
    for name in candidates:
        if name in cols:
            return name
    return None


def _first_numeric_col(cols: dict) -> str | None:
    for name, meta in cols.items():
        typ = ""
        if isinstance(meta, dict):
            typ = str(meta.get("type", "")).lower()
        if any(h in typ for h in _NUMERIC_TYPE_HINTS):
            return name
    return None


def decode_view(prefix: str, cols: dict) -> dict:
    """Decode a semantic prefix into an only-applicable {filter, sort, limit}.

    ``cols`` maps colName -> {"type": str, "enum": [values]?}. Only keys whose
    backing column actually exists are emitted; an empty/unknown prefix yields
    ``{}``.
    """
    cols = cols or {}
    prefix = (prefix or "").lower()
    view: dict = {}

    if prefix in ("active", "open", "pending", "closed", "completed"):
        status = _find_status_col(cols)
        if status is not None:
            col_name, enum = status
            value = _match_enum_value(prefix, enum)
            if value is not None:
                view["filter"] = {col_name: value}
        return view

    if prefix in ("recent", "latest", "new"):
        field = _first_present(cols, _RECENT_DATE_COLS)
        if field is not None:
            view["sort"] = {"field": field, "direction": "desc"}
        view["limit"] = _LIMIT
        return view

    if prefix == "upcoming":
        field = _first_present(cols, _FUTURE_DATE_COLS)
        if field is not None:
            view["sort"] = {"field": field, "direction": "asc"}
        view["limit"] = _LIMIT
        return view

    if prefix == "top":
        field = _first_numeric_col(cols) or _first_present(cols, _RECENT_DATE_COLS)
        if field is not None:
            view["sort"] = {"field": field, "direction": "desc"}
        view["limit"] = _LIMIT
        return view

    return view
