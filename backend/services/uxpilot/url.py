"""What a user pastes to name a UX Pilot page (PRD §41).

A page id, or the page's URL from the UX Pilot app. Either becomes the same
:class:`services.figma.url.FigmaTarget` the store serialises — ``file_key``
holds the page id and ``kind`` says which tool it belongs to — so one target
type crosses every seam.
"""
from __future__ import annotations

import re

from services.figma.url import FigmaTarget

_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_URL = re.compile(r"https?://(?:[a-z0-9-]+\.)*uxpilot\.(?:ai|net)/[^\s<>\"')]*", re.I)
_QUERY_PAGE = re.compile(r"[?&](?:page|pageId|page_id)=([A-Za-z0-9_-]+)")


def page_id_of(text: str) -> str:
    """The page id in ``text``: a bare id, or the id a UX Pilot URL names."""
    s = (text or "").strip()
    if not s:
        return ""
    m = _URL.search(s)
    if m:
        url = m.group(0)
        q = _QUERY_PAGE.search(url)
        if q:
            return q.group(1)
        parts = [p for p in url.split("?", 1)[0].split("#", 1)[0].split("/") if p]
        # scheme, host, then the path; the last segment names the page.
        return parts[-1] if len(parts) > 2 and _ID.match(parts[-1]) else ""
    return s if _ID.match(s) else ""


def parse(text: str) -> FigmaTarget | None:
    """A target for the page ``text`` names, or None when it names none."""
    page_id = page_id_of(text)
    if not page_id:
        return None
    m = _URL.search(text or "")
    return FigmaTarget(file_key=page_id, source_url=m.group(0) if m else "", kind="uxpilot")
