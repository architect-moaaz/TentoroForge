"""The application's photographs, found where the design agent said to look.

The design agent decides WHAT each picture is of — a `query` and an `alt` per
job (`auth`, `hero`, `empty`) in `designSystem.imagery`. This service node
finds the picture: one Unsplash search per query, the first result, its URL
sized for the web, and the photographer's credit, which the licence asks to be
shown beside the picture and which the page author is handed with it.

NO KEY, NO PHOTO — AND NO FAILURE. Unsplash's API needs an access key
(``UNSPLASH_ACCESS_KEY``); the old keyless `source.unsplash.com` was retired in
2024. Without a key every entry keeps an empty `url`, the page author is told
so, and pages fall back to the brand gradient. A search that fails does the
same for its entry alone. A picture already found is kept: a rebuild does not
re-roll the sign-in page.

Unsplash's guidelines also ask that a chosen photo's `download_location` be
hit once it is used; that is done here, at the moment of choosing.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: The environment variable holding the Unsplash access key.
UNSPLASH_KEY_ENV = "UNSPLASH_ACCESS_KEY"
#: Attribution the licence asks for, pointing back at the photographer.
_UTM = "?utm_source=tentoro_forge&utm_medium=referral"
#: The width pages get; Unsplash resizes on the fly from `raw`.
_WIDTH = 1800

Fetcher = Callable[[str, dict[str, str]], Any]


def _unsplash(key: str) -> Fetcher:
    """GET against the Unsplash API; returns the JSON body."""
    import httpx

    client = httpx.Client(base_url="https://api.unsplash.com", timeout=20.0,
                          headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"})

    def get(path: str, params: dict[str, str]) -> Any:
        r = client.get(path, params=params)
        r.raise_for_status()
        return r.json()
    return get


def find_photo(query: str, get: Fetcher) -> dict[str, Any] | None:
    """The first landscape photo for `query`: its URLs and credit, or None."""
    body = get("/search/photos", {"query": query, "per_page": "1", "orientation": "landscape",
                                   "content_filter": "high"})
    results = (body or {}).get("results") or []
    if not results:
        return None
    photo = results[0]
    urls = photo.get("urls") or {}
    raw = str(urls.get("raw") or "")
    user = photo.get("user") or {}
    links = photo.get("links") or {}
    # The licence: register the use, once, when the picture is chosen.
    if links.get("download_location"):
        try:
            get(str(links["download_location"]).replace("https://api.unsplash.com", ""), {})
        except Exception as exc:  # noqa: BLE001 — a courtesy call, never the picture
            logger.info("[imagery] download_location not registered: %s", str(exc)[:120])
    return {
        "url": f"{raw}&w={_WIDTH}&q=80&auto=format&fit=crop" if raw else str(urls.get("regular") or ""),
        "thumbUrl": str(urls.get("small") or ""),
        "credit": {"name": str(user.get("name") or "Unsplash"),
                   "link": str(user.get("links", {}).get("html") or "https://unsplash.com") + _UTM},
    }


def fill_imagery(doc: dict, get: Fetcher | None = None) -> dict[str, Any]:
    """Fill `designSystem.imagery[*].url/thumbUrl/credit` in place. Returns what
    happened, for the ledger: how many were found, kept, or left empty and why."""
    design = doc.get("designSystem") or {}
    entries = [e for e in design.get("imagery") or [] if isinstance(e, dict) and e.get("query")]
    if not entries:
        return {"found": 0, "kept": 0, "empty": 0, "why": "the design names no pictures"}
    if get is None:
        key = os.environ.get(UNSPLASH_KEY_ENV, "").strip()
        if not key:
            empty = sum(1 for e in entries if not e.get("url"))
            return {"found": 0, "kept": len(entries) - empty, "empty": empty,
                    "why": f"no {UNSPLASH_KEY_ENV} — pages use the brand gradient instead"}
        get = _unsplash(key)
    found = kept = empty = 0
    for entry in entries:
        if entry.get("url"):
            kept += 1
            continue
        try:
            photo = find_photo(str(entry["query"]), get)
        except Exception as exc:  # noqa: BLE001 — one picture, not the run
            logger.warning("[imagery] %s: %s", entry.get("query"), str(exc)[:160])
            photo = None
        if photo and photo["url"]:
            entry.update(photo)
            found += 1
        else:
            empty += 1
    return {"found": found, "kept": kept, "empty": empty, "why": ""}


def imagery_brief(doc: dict) -> str:
    """What the page author is told about the pictures: each job's URL and
    credit, or that there are none and the gradient stands in."""
    entries = [e for e in ((doc.get("designSystem") or {}).get("imagery") or []) if isinstance(e, dict)]
    with_url = [e for e in entries if e.get("url")]
    if not with_url:
        return ("No photographs: the platform has none for this application. Where a picture "
                "would go (the sign-in panel, a hero band, an empty state) use the brand gradient.")
    lines = ["Photographs, by job — show each with its credit beside it (small, muted, a link):"]
    for e in with_url:
        credit = e.get("credit") or {}
        lines.append(f'- {e.get("role")}: src="{e["url"]}" alt="{e.get("alt") or e.get("query")}" — '
                     f'Photo by {credit.get("name", "Unsplash")} ({credit.get("link", "https://unsplash.com")})')
    return "\n".join(lines)


__all__ = ["UNSPLASH_KEY_ENV", "fill_imagery", "find_photo", "imagery_brief"]
