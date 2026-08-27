"""Build plan.pages directly from a Figma file's frame tree.

When figma_url is supplied to the generate pipeline, this becomes the
source of truth for plan.pages — bypassing the LLM planner. One
plan.pages entry per top-level FRAME found in the Figma file.
"""
from __future__ import annotations

from figma_parser import parse_figma_url
from services.figma_client import fetch_figma_file
from services.figma_route_inferer import infer_route_from_frame_name


_EXCLUDED_TYPES = {"COMPONENT", "COMPONENT_SET", "SLICE", "INSTANCE"}


def _classify_type_from_name(name: str) -> str | None:
    """Best-effort page_type classification from the frame name.
    Returns one of: auth/dashboard/list/detail/form/error, or None."""
    n = (name or "").lower()
    if any(k in n for k in ("login", "sign in", "signin", "signup", "sign up",
                            "register", "forgot", "reset")):
        return "auth"
    if any(k in n for k in ("dashboard", "overview", "home")):
        return "dashboard"
    if any(k in n for k in ("list", "index")) or n.endswith("s"):
        return "list"
    if any(k in n for k in ("detail", "[id]", "{id}")):
        return "detail"
    if any(k in n for k in ("new", "create", "edit", "form")):
        return "form"
    if any(k in n for k in ("error", "404", "not-found")):
        return "error"
    return None


def _extract_frames(file_meta: dict) -> list[dict]:
    """Walk file_meta.document.children (CANVAS) → their children (FRAMEs).
    Returns a list of {id, name, route, type} dicts with deduped routes.
    Skips: non-FRAME types (COMPONENT/COMPONENT_SET/SLICE), hidden frames.
    """
    out: list[dict] = []
    document = (file_meta or {}).get("document") or {}
    for canvas in document.get("children") or []:
        if canvas.get("type") != "CANVAS":
            continue
        for frame in canvas.get("children") or []:
            if frame.get("type") != "FRAME":
                continue
            if frame.get("visible") is False:
                continue
            name = frame.get("name") or ""
            out.append({
                "id": frame.get("id"),
                "name": name,
                "route": infer_route_from_frame_name(name),
                "type": _classify_type_from_name(name),
            })

    # Deduplicate routes by suffixing -2, -3, ... on collision
    seen: dict[str, int] = {}
    for f in out:
        base = f["route"]
        if base in seen:
            seen[base] += 1
            f["route"] = f"{base}-{seen[base]}"
        else:
            seen[base] = 1
    return out


async def build_plan_from_figma(figma_url: str, token: str) -> dict:
    """See module docstring."""
    parsed = parse_figma_url(figma_url)
    file_key = parsed["file_key"]
    file_meta = await fetch_figma_file(file_key, token, depth=2)
    raw_frames = _extract_frames(file_meta)

    pages = []
    for fr in raw_frames:
        slug = fr["route"].strip("/").replace("/", "-") or "home"
        pages.append({
            "route": fr["route"],
            "name": fr["name"],
            "figma_node_id": fr["id"],
            "type": fr["type"],
            "file": f"src/schemas/{slug}.json",
            "entity": None,
        })

    return {
        "pages": pages,
        "figma_file_key": file_key,
        "figma_url": figma_url,
        "name": (file_meta or {}).get("name", "Untitled"),
        "_figma_driven": True,
    }
