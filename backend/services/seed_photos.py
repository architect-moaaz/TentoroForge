"""A photo for each sample row that has somewhere to put one.

The seed rows (`contracts/seed-plan.json`, written by `seed_synthesizer`) have
no picture, so every card of a seeded app drew a blank square (UAT F&B: Iced
Lemon Tea, Spring Rolls). `blueprint/imagery.py` only finds three page-level
photos; this finds one per ROW, from the row's own name plus its record type
and a category-like value ("Iced Lemon Tea" + "Menu Item" + "Drinks"), through
the same Unsplash path and rules:

* the key is the organisation's (Settings -> Integrations -> Unsplash), the
  environment's ``UNSPLASH_ACCESS_KEY`` as fallback. No key, no photos, no
  failure: the image column stays EMPTY (never placeholder text) and the page
  draws its "No photo yet" tile;
* a search that fails leaves THOSE rows empty and nothing else;
* a photo already found is kept: the synthesizer rewrites the rows on every
  build, so found photos live in the plan under ``seed_photos`` (by query) and
  are put back without a search -- a rebuild does not re-roll;
* only a column that holds a picture's address is touched: a STRING column
  named ...url / ...src / ...image / ...photo / ...picture / ...thumbnail, empty
  or holding the synthesizer's placeholder text -- never alt text, captions,
  credits, ids, counts, flags, lists, objects, or a value already there;
* the photographer's credit travels WITH the address (a ``#credit=`` fragment,
  which the browser never sends and the Image component reads to show "Photo by
  ... on Unsplash"), and is also kept in ``seed_photo_credits``;
  `download_location` is pinged by ``imagery`` as the licence asks;
* cost is bounded: one search per distinct query (asking for as many photos as
  rows share it, so they are not all the same picture), at most ``MAX_SEARCHES``
  per build, queries capped at ``MAX_QUERY`` characters.

``get`` is injectable (a fake in tests), as in imagery.py. Never raises.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from services.blueprint.imagery import Fetcher, _unsplash, access_key, find_photos

logger = logging.getLogger(__name__)

MAX_SEARCHES = 24
#: Stop searching after this many failures in a row (a down or rate-limited service
#: would otherwise be asked 24 times, and again on the next build).
MAX_CONSECUTIVE_FAILURES = 3
#: How long a 429 keeps the next builds from asking again when no Retry-After says.
BLOCK_SECONDS = 900
#: A server's Retry-After is honoured only up to this: a block must never outlast the next day's work.
MAX_BLOCK_SECONDS = 3600


def _key_fingerprint(key: str) -> str:
    """A hash that says WHICH key was blocked (never the key): a new key is a new chance."""
    import hashlib
    return hashlib.sha256((key or "").encode("utf-8")).hexdigest()[:16]
MAX_QUERY = 100
MAX_PER_QUERY = 10
#: The word a picture-address column ENDS in (camel/snake aware).
_ADDRESS_ENDINGS = frozenset({"url", "src", "image", "photo", "picture", "thumbnail", "img"})
#: Pictures that are NOT the record's own photo: a person's avatar, a brand's logo, an icon, a
#: banner, a badge, a flag, a QR code. A stock photo of the row's name in one of these is wrong.
_NOT_THE_RECORDS_PHOTO = frozenset({"avatar", "logo", "icon", "profile", "banner", "favicon", "headshot", "badge", "flag",
                                    "qr", "qrcode", "cover", "background", "signature", "stamp", "emoji", "sticker", "thumb",
                                    "header", "hero", "wallpaper", "barcode", "selfie", "portrait"})
#: Words that make a column about a picture without being its address.
_NOT_ADDRESS = frozenset({"alt", "caption", "credit", "credits", "id", "ids", "meta", "metadata", "count", "letter",
                          "by", "photographer", "author", "has", "is", "show", "shown", "flag", "ratio", "size",
                          "width", "height", "type", "mime", "name", "title", "label", "description", "text"})
_NAME_COL = re.compile(r"^(name|title|label|displayname)$", re.I)
_CATEGORY_COL = re.compile(r"(category|cuisine|type|kind|genre|brand|group)$", re.I)
_REAL_ADDRESS = re.compile(r"^(https?://\S+|/\S+|data:image/\S+)$", re.I)
#: What the synthesizer used to leave in an image column ("Image Url 1").
_PLACEHOLDER = re.compile(r"^(image|photo|picture|thumbnail|img)[\w ]*\s\d+$", re.I)


def _words(col: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(col))
    return [w for w in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if w]


def is_photo_column(col: str, value: Any = "") -> bool:
    """A column that holds a picture's ADDRESS: a string (or empty) whose name ends
    in url/src/image/photo/picture/thumbnail and is not about the picture."""
    if value is not None and not isinstance(value, str):
        return False
    w = _words(col)
    if not w or w[-1] not in _ADDRESS_ENDINGS:
        return False
    return not (set(w[:-1]) & _NOT_ADDRESS) and w[-1] not in _NOT_ADDRESS and not (set(w) & _NOT_THE_RECORDS_PHOTO)


def is_placeholder(value: Any) -> bool:
    """Empty, or the synthesizer's placeholder text: safe to replace."""
    return value is None or (isinstance(value, str) and (value.strip() == "" or bool(_PLACEHOLDER.match(value.strip()))))


def _humanize(s: str) -> str:
    s = re.sub(r"[_\-]+", " ", s)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s).strip()


def _query(row: dict, table: str) -> str | None:
    name = next((str(v) for k, v in row.items() if _NAME_COL.match(k) and isinstance(v, str) and v.strip()), "")
    if not name:
        name = next((str(v) for k, v in row.items()
                     if re.search(r"(name|title)$", k, re.I) and isinstance(v, str) and v.strip()), "")
    if not name:
        return None
    name = re.sub(r"\s+\d+$", "", name.strip())      # "Menu Item 3" -> "Menu Item"
    kind = _humanize(table)
    extra = next((str(v) for k, v in row.items() if _CATEGORY_COL.search(k) and isinstance(v, str)
                  and v.strip() and not _REAL_ADDRESS.match(v) and len(v) < 40 and not re.fullmatch(r"[0-9a-f-]{16,}", v)), "")
    parts = [name] + ([] if name.lower() == kind.lower() else [kind]) + ([extra] if extra and extra.lower() not in name.lower() else [])
    return " ".join(parts).strip().lower()[:MAX_QUERY]


def _with_credit(photo: dict) -> str:
    c = photo.get("credit") or {}
    if not c.get("name"):
        return photo["url"]
    return f"{photo['url']}#credit={quote(str(c['name']), safe='')}&credit_link={quote(str(c.get('link') or ''), safe='')}"


def fill_seed_photos(output_dir: str | Path, get: Fetcher | None = None, *,
                     max_searches: int = MAX_SEARCHES, retry: bool = False) -> dict[str, Any]:
    """Give every seed row's empty image column a photo. Returns
    ``{found, kept, empty, searches, why}``."""
    out = {"found": 0, "kept": 0, "empty": 0, "searches": 0, "why": ""}
    try:
        path = os.path.join(str(output_dir), "contracts", "seed-plan.json")
        if not os.path.isfile(path):
            return out
        from services.guard_io import dump_like, read_raw
        raw_text = read_raw(path)
        plan = json.loads(raw_text)
        if not isinstance(plan, dict):
            return out
        cache: dict[str, Any] = plan.get("seed_photos") if isinstance(plan.get("seed_photos"), dict) else {}

        groups: dict[str, list[tuple[dict, str, str]]] = {}      # query -> [(row, column, table)]
        for t in plan.get("tables") or []:
            if not isinstance(t, dict):
                continue
            table = str(t.get("name") or "")
            for row in t.get("seed_data") or []:
                if not isinstance(row, dict):
                    continue
                for col, val in row.items():
                    if not is_photo_column(col, val):
                        continue
                    if not is_placeholder(val):
                        out["kept"] += 1                        # a real address, a data: URI, anything already there
                        continue
                    q = _query(row, table)
                    if q:
                        groups.setdefault(q, []).append((row, col, table))
                    else:
                        row[col] = ""
        if not groups:
            return out

        fetch = get
        if fetch is None and any(q not in cache for q in groups):
            key = access_key(output_dir)
            if not key:
                out["why"] = "no Unsplash key (Settings -> Integrations) - cards show a placeholder"
            else:
                fetch = _unsplash(key)

        import time
        blocked_until = float(plan.get("seed_photos_blocked_until") or 0)
        key_fp = _key_fingerprint(access_key(output_dir)) if get is None else "injected"
        if blocked_until and (retry or plan.get("seed_photos_blocked_key") != key_fp):
            # asked to retry, or the key changed since it was blocked: the block no longer applies
            plan.pop("seed_photos_blocked_until", None)
            plan.pop("seed_photos_blocked_key", None)
            blocked_until = 0.0
        if fetch is not None and blocked_until > time.time():
            fetch = None                                          # rate limited recently: do not ask again yet
            out["why"] = ("Unsplash asked us to slow down (rate limited); not asked again until "
                          + time.strftime("%H:%M", time.localtime(blocked_until)))
        failures = 0
        used: dict[str, set[str]] = {}
        for q, members in groups.items():
            photos = cache.get(q)
            if isinstance(photos, dict):
                photos = [photos]                                # an older cache held one photo per query
            if photos is None and q not in cache and fetch is not None and out["searches"] < max_searches:
                out["searches"] += 1
                try:
                    photos = [p for p in find_photos(q, fetch, min(len(members), MAX_PER_QUERY)) if p.get("url")]
                except Exception as exc:  # noqa: BLE001 — these rows, not the build
                    photos = None
                    failures += 1
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status == 429:
                        retry_after = getattr(getattr(exc, "response", None), "headers", {}) or {}
                        try:
                            wait = float(retry_after.get("Retry-After")) if retry_after.get("Retry-After") else BLOCK_SECONDS
                        except (TypeError, ValueError):
                            wait = BLOCK_SECONDS
                        wait = max(1.0, min(wait, MAX_BLOCK_SECONDS))
                        plan["seed_photos_blocked_until"] = time.time() + wait
                        plan["seed_photos_blocked_key"] = key_fp
                        out["why"] = f"Unsplash rate limited the searches (429); stopped, and not asked again for {int(wait // 60) or 1} min"
                        logger.warning("[seed-photos] rate limited (429): stopping")
                        max_searches = out["searches"]
                    elif failures >= MAX_CONSECUTIVE_FAILURES:
                        out["why"] = f"Unsplash searches failed {failures} times in a row ({str(exc)[:80]}); stopped"
                        logger.warning("[seed-photos] %s", out["why"])
                        max_searches = out["searches"]
                    else:
                        logger.warning("[seed-photos] %s: %s", q, str(exc)[:160])
                if photos:
                    cache[q] = photos
                    failures = 0
            photos = [p for p in (photos or []) if isinstance(p, dict) and p.get("url")]
            for i, (row, col, table) in enumerate(members):
                if not photos:
                    row[col] = ""                                # no picture: empty, never placeholder text
                    out["empty"] += 1
                    continue
                seen = used.setdefault(table, set())
                pick = next((p for p in photos[i % len(photos):] + photos[: i % len(photos)] if p["url"] not in seen), photos[i % len(photos)])
                seen.add(pick["url"])
                row[col] = _with_credit(pick)
                plan.setdefault("seed_photo_credits", {})[pick["url"]] = pick.get("credit") or {}
                out["found"] += 1

        if cache:
            plan["seed_photos"] = cache
        # sample_data mirrors seed_data (seed.ts reads either)
        sd = plan.get("sample_data")
        if isinstance(sd, dict):
            for t in plan.get("tables") or []:
                if isinstance(t, dict) and t.get("name") in sd and isinstance(t.get("seed_data"), list):
                    sd[t["name"]] = t["seed_data"]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(dump_like(raw_text, plan))
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 — never break the build
        logger.warning("seed_photos failed: %s", exc)
    return out
