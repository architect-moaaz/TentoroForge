"""One captured call, whether the platform browser saw it or the person's
own recording did: the method, the path with ids normalised, the request
body's KEYS, the response's SHAPE — never its values, never a header that
could carry a credential. The shape is what a study needs (what records
look like, what an action sends); the values are the product's data and
nobody's business. `scrub` runs over every string before a call is kept.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from services.smith.secrets_scrub import scrub

#: Headers that are dropped whole, by name or by what the name carries.
DROP_HEADERS = {"cookie", "set-cookie", "authorization", "proxy-authorization", "x-api-key", "x-auth-token",
                "x-csrf-token", "x-xsrf-token"}
_DROP_HEADER_WORDS = re.compile(r"token|secret|key|session|auth|cookie|credential", re.I)
#: Query parameters dropped by name.
_DROP_QUERY = re.compile(r"^(token|key|auth|session|sig|signature|access_token|refresh_token|code|state|"
                         r"api_key|apikey|secret|password|passwd)$", re.I)
_ID = re.compile(r"^(?:[0-9]+|[0-9a-f]{8,}(?:-[0-9a-f]{4,}){0,4}|[A-Za-z0-9_-]{20,})$")
#: Response bodies kept up to this many bytes before shaping.
MAX_BODY = 2_000_000
#: Strings this short are candidates for enum values.
ENUM_MAX = 24
MIME_KEPT = ("application/json", "text/html", "application/xhtml")


def normalise_path(path: str) -> str:
    """`/orders/8f3a…/items/42` → `/orders/{id}/items/{id}`."""
    parts = [p for p in (path or "/").split("/")]
    return "/".join("{id}" if p and _ID.match(p) else p for p in parts) or "/"


def clean_url(url: str) -> tuple[str, list[str]]:
    """The URL without credential-shaped query values; the query keys kept."""
    parsed = urlparse(str(url or ""))
    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not _DROP_QUERY.match(k)]
    rebuilt = urlunparse(parsed._replace(query=urlencode(kept), fragment=""))
    return scrub(rebuilt), sorted({k for k, _ in kept})


def keep_header(name: str) -> bool:
    low = str(name or "").lower()
    return low not in DROP_HEADERS and not _DROP_HEADER_WORDS.search(low)


def shape(value: Any, *, depth: int = 0, enums: dict[str, set] | None = None, path: str = "",
          seen: dict[str, int] | None = None) -> Any:
    """The shape of a JSON value: objects become `{field: kind}`, lists their
    length and their first item's shape, scalars their kind. Short strings
    are collected per field path into `enums` (what the field's values are
    seen to be)."""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:60]:
            out[str(k)] = shape(v, depth=depth + 1, enums=enums, path=f"{path}.{k}" if path else str(k), seen=seen)
        return out
    if isinstance(value, list):
        if not value:
            return {"list": 0, "of": "empty"}
        # Every item is read for enum values; the first gives the shape.
        first = shape(value[0], depth=depth + 1, enums=enums, path=path + "[]", seen=seen)
        for item in value[1:40]:
            shape(item, depth=depth + 1, enums=enums, path=path + "[]", seen=seen)
        return {"list": len(value), "of": first}
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    s = str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return "date"
    if "@" in s and "." in s.split("@")[-1]:
        return "email"                                 # a person's address: never an enum value
    if s.startswith(("http://", "https://")):
        return "url"
    if re.match(r"^\+?[\d\s().-]{7,}$", s):
        return "phone"
    # A short word is a candidate enum value (a state, a kind); an id, a
    # number or anything with a space and a capital (a name) is not.
    if enums is not None and 0 < len(s) <= ENUM_MAX and not _ID.match(s) and not s.replace(".", "").isdigit() \
            and not re.search(r"\s[A-Z]", s):
        enums.setdefault(path, set()).add(scrub(s))
        if seen is not None:
            seen[path] = seen.get(path, 0) + 1
    return "text"


def keys_of(body: Any) -> list[str]:
    """The keys a request body carries, values dropped."""
    if isinstance(body, dict):
        return sorted(str(k) for k in body.keys())[:60]
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return sorted(str(k) for k in body[0].keys())[:60]
    return []


def record(method: str, url: str, status: int | None, mime: str, *, request_body: Any = None,
           response_body: Any = None, page: str = "", source: str = "web", at: float = 0.0) -> dict | None:
    """A kept call, or None when it is not one a study wants (not same-kind
    content, or a method nobody records)."""
    mime = str(mime or "").split(";")[0].strip().lower()
    if not any(mime.startswith(m) for m in MIME_KEPT):
        return None
    clean, query_keys = clean_url(url)
    parsed = urlparse(clean)
    enums: dict[str, set] = {}
    seen: dict[str, int] = {}
    resp_shape = None
    if mime.startswith("application/json") and response_body is not None:
        resp_shape = shape(response_body, enums=enums, seen=seen)
    return {"method": str(method or "GET").upper(), "url": clean, "host": parsed.hostname or "",
            "path": normalise_path(parsed.path), "query_keys": query_keys, "status": status, "mime": mime,
            "request_keys": keys_of(request_body), "response_shape": resp_shape,
            # A field's short values and how many times the field was seen:
            # an enum is a field whose values REPEAT (a state, a kind), not a
            # field that is different every time (a name).
            "enums": {k: {"values": sorted(v)[:12], "seen": seen.get(k, 0)} for k, v in enums.items() if v},
            "page": scrub(str(page or ""))[:300], "source": source, "at": at}


__all__ = ["normalise_path", "clean_url", "keep_header", "shape", "keys_of", "record", "MAX_BODY", "MIME_KEPT",
           "DROP_HEADERS"]
