"""Route ↔ file-path slug conversion.

A route like `/notes/new` maps to file `notes/new.json` under
`src/schemas/`. Routes outside the allowed character set are rejected to
prevent path traversal and shell injection — we treat schema paths as
file paths on disk, not as URLs.

Express-style params (`:id`) are normalised to Next.js bracket form (`[id]`)
before validation, so planners that emit either convention work.
"""
from __future__ import annotations
import re

_HOME_SLUG = "home"
_SAFE_SEGMENT = re.compile(r"^[a-z0-9_\-\[\]]+$")
_COLON_PARAM_RE = re.compile(r":(\w+)")


def normalise_route(route: str) -> str:
    """Convert Express-style `:param` segments to Next.js `[param]`."""
    if not route:
        return ""
    return _COLON_PARAM_RE.sub(lambda m: f"[{m.group(1)}]", route)


def slugify_route(route: str) -> str:
    """Convert a Next.js app-router-style route to a file path slug.

    Rules:
      - "/" or "" → "home"
      - `:param` segments are normalised to `[param]` first
      - Leading/trailing slashes stripped, repeated slashes collapsed
      - Each segment must match _SAFE_SEGMENT or ValueError is raised

    Example:
        slugify_route("/notes/new") == "notes/new"
        slugify_route("/notes/[id]") == "notes/[id]"
        slugify_route("/notes/:id") == "notes/[id]"
    """
    if not route or route == "/":
        return _HOME_SLUG
    route = normalise_route(route)
    segments = [seg for seg in route.split("/") if seg]
    for seg in segments:
        if not _SAFE_SEGMENT.match(seg):
            raise ValueError(f"route segment {seg!r} contains unsafe characters")
    return "/".join(segments)


def route_from_slug(slug: str) -> str:
    """Inverse of slugify_route. Used when scanning files back to routes."""
    if slug == _HOME_SLUG:
        return "/"
    return "/" + slug
