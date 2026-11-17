"""Smith asks for the Google Maps key when the plan needs a map.

WHY. Every built app can draw Google Maps and Google's road and arrival time, but only with a key; without one it quietly
falls back to a free map and a free demo router. An owner whose app is about delivery, tracking or zones never learns that a
key would make it better, so the app ships with the worse map for ever.

WHAT SMITH DOES. When the plan has a map (a screen section that shows a map, a map-first role, or zones) and no key is set,
Smith says so ONCE, names the Google APIs to turn on, and shows the box to paste the key in. It never stops the build: the free
map is a fine start, and the key can be added any time.

THE KEY NEVER TRAVELS IN THE CHAT. The box is the same `SecretCard` the UX Pilot and Figma keys use: it sends the key straight to
the organisation's integrations (`PUT /api/orgs/{org}/integrations`, encrypted, one key for all three names an app reads) and
sends Smith only the words in `SAVED`. The next turn copies the saved key into the app's `.env.local` (`prepare_project_tree`).
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROVIDER = "google_maps"
KEY = "GOOGLE_MAPS_API_KEY"

#: The sentence that identifies the ask in a transcript: `key_saved_in` accepts the saved words only straight after it.
_MARK = "needs Google Maps"
SAVED = "Google Maps key saved"
SKIP = "Use the free map"

#: The Google APIs the one key must be allowed to use, in the words Google's console shows.
APIS = ("Maps JavaScript API", "Routes API", "Directions API", "Geocoding API", "Places API", "Maps SDK for Android")

_ASKED = ".forge/maps-key-asked"

TEXT = (
    f"This app {_MARK}: {{why}}. It works without one on a free map, but a Google key gives it Google's map, real roads and "
    "arrival times. In Google Cloud (billing on) turn on: " + ", ".join(APIS) + ". Make one key, restrict it to your apps, "
    "and paste it in the box below. It is saved encrypted with your organisation's other integrations (the same place as "
    "Settings → Integrations → Google Maps), used for the page, the server and the phone, and never written into this "
    "conversation. I am carrying on with the free map meanwhile."
)

SECRET_FIELD: dict[str, str] = {
    "provider": PROVIDER,
    "key": KEY,
    "label": "Google Maps API key",
    "placeholder": "AIza...",
    "saved": SAVED,
}

SAVED_TEXT = (
    "Google Maps key saved. It reaches the app on its next preview or build, and a published app on its next publish. "
    "Until then the app keeps the free map."
)


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def why_maps(doc: dict) -> str:
    """The reason this plan has a map, in a few words; "" when it has none."""
    doc = doc or {}
    if (doc.get("geofencing") or {}).get("enabled"):
        return "the zones it watches are drawn on a map"
    if (doc.get("mobile") or {}).get("mapFirstRoles"):
        return "a role of the phone app is built around a map"
    for n in _walk(doc.get("pages") or []):
        if str(n.get("shows") or "").strip().lower() == "map":
            return "a screen shows records on a map"
    return ""


_MAP_WORDS = re.compile(r"\b(?:maps?|gps|live (?:location|tracking)|directions|geofenc\w*)\b", re.I)
_NOT_A_MAP = re.compile(r"\b(?:road ?map|site ?map|mind ?map|heat ?map|tree ?map|story ?map|journey map)\b", re.I)


def why_in_brief(brief: str) -> str:
    """The reason, read from what the person typed: Smith's first answer comes before anything is saved, so the brief itself is
    the only sign of a map that early."""
    text = _NOT_A_MAP.sub(" ", brief or "")
    if not text.strip():
        return ""
    try:
        from services.blueprint import geofence_plan

        if geofence_plan.analyse(text).needed:
            return "the zones it watches are drawn on a map"
    except Exception:  # noqa: BLE001
        pass
    if _MAP_WORDS.search(text):
        return "the brief talks about a map or live tracking"
    return ""


def why_in_files(output_dir: str | Path) -> str:
    """The same reason, read from what is saved beside the project, for the turns before a definition exists: the zones
    plan (written the first turn the brief names a geofence or a distance) and the platform plan (a map-first role)."""
    try:
        from services.blueprint import geofence_plan

        if geofence_plan.read(output_dir):
            return "the zones it watches are drawn on a map"
    except Exception:  # noqa: BLE001 — a reading that fails is no reason to ask
        pass
    try:
        from services.blueprint import platform_plan

        if platform_plan.map_first_roles(output_dir):
            return "a role of the phone app is built around a map"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _saved_doc(output_dir: str | Path) -> dict:
    import json

    try:
        return json.loads((Path(output_dir) / ".forge" / "blueprint" / "current.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def key_set(output_dir: str | Path) -> bool:
    """Whether a Google Maps key is already available to this project: the organisation's, or the server's own."""
    if any((os.environ.get(n) or "").strip() for n in (KEY, "NEXT_PUBLIC_GOOGLE_MAPS_API_KEY", "GOOGLE_MAPS_SERVER_KEY")):
        return True
    try:
        from services.figma.integrations import config_for

        return bool((config_for(output_dir, provider=PROVIDER) or {}).get(KEY))
    except Exception as exc:  # noqa: BLE001 — a lookup that fails must never block a build
        logger.info("[maps-key] lookup unavailable (%s)", type(exc).__name__)
        return False


def asked(output_dir: str | Path) -> bool:
    return (Path(output_dir) / _ASKED).is_file()


def _mark_asked(output_dir: str | Path) -> None:
    try:
        p = Path(output_dir) / _ASKED
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("asked\n", encoding="utf-8")
    except OSError:
        pass


def ask(doc: dict, output_dir: str | Path, brief: str = "") -> dict[str, Any] | None:
    """The message that asks for the key, or None: no map in the plan, a key already set, or already asked once.

    Asking is remembered, so an owner who carries on with the free map is not asked again at every build."""
    why = why_maps(doc) or why_in_files(output_dir) or why_in_brief(brief)
    if not why or asked(output_dir) or key_set(output_dir):
        return None
    _mark_asked(output_dir)
    return {"text": TEXT.format(why=why), "options": [SKIP], "secret": dict(SECRET_FIELD), "status": "asked"}


def is_prompt(text: str) -> bool:
    return _MARK in (text or "")


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _asked_lately(history: Iterable[tuple[str, str]], within: int = 40) -> bool:
    """Whether Smith asked for the key in the recent turns. Not only the last one: the build carries on after the ask, so
    its own messages follow it."""
    turns = [(str(r or "").lower(), str(t or "")) for r, t in history if str(t or "").strip()]
    return any(r in ("smith", "assistant") and is_prompt(t) for r, t in turns[-within:])


def key_saved_in(message: str, history: Iterable[tuple[str, str]]) -> bool:
    """Whether `message` is the panel saying the key was saved, after the ask."""
    return _norm(message) == _norm(SAVED) and _asked_lately(history)


def skipped_in(message: str, history: Iterable[tuple[str, str]]) -> bool:
    """Whether `message` is the owner choosing the free map, after the ask."""
    return _norm(message) == _norm(SKIP) and _asked_lately(history)


def ask_after_turn(output_dir: str | Path, brief: str = "") -> dict[str, Any] | None:
    """The ask, for a chat turn that has just answered: from the saved definition when there is one, else from the saved plans.
    Never raises: a suggestion must not break a turn."""
    try:
        return ask(_saved_doc(output_dir), output_dir, brief)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[maps-key] not asked for %s: %s", Path(str(output_dir)).name, exc)
        return None
