"""The phone app, as the Editor sees it: which surfaces an application has, and the rewrite after a plan edit.

A page, the menu and the look are edits of the one Blueprint. The web app and the phone app are both projected from it, so an
edit made while looking at either is followed by the rewrite of EVERY surface the application has: the web files as before, and
the phone's theme, menu and route files here. The phone project's own fixed files (app.json, the Expo account that owns the
project, its address) are not touched."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def enabled(doc: dict) -> bool:
    """The application has a phone app (`mobile.native.enabled`)."""
    from services.blueprint.native_projection import enabled as native_enabled
    return native_enabled(doc)


def surfaces(doc: dict) -> dict[str, bool]:
    """What the Editor can show: the website, the phone app, or both."""
    from services.blueprint.app_target import web_pages_enabled
    return {"web": bool(web_pages_enabled(doc)), "phone": enabled(doc)}


def screen_pages(doc: dict) -> set[str]:
    """The ids of the pages that are phone screens: the ones with a screen written for them."""
    return {str(r.get("page")) for r in (doc.get("nativeCode") or [])
            if isinstance(r, dict) and r.get("status") != "DEPRECATED" and r.get("page")}


def reproject(doc: dict, root: str | Path) -> list[str]:
    """The phone's theme, navigation, schema and route files, rewritten from the Blueprint after a page, menu or look edit.

    Never raises: the edit is already saved in the Blueprint, and a phone project that cannot be rewritten now is rewritten by
    the next build. Returns the files written."""
    if not enabled(doc):
        return []
    from services.blueprint import native_projection as np
    try:
        return list(np.project_generated_modules(doc, root)) + list(np.project_screens(doc, root))
    except Exception as exc:  # noqa: BLE001 - said in the log, never a failed edit
        logger.warning("[react_editor.phone] the phone project was not rewritten: %s", exc)
        return []


def page_fields(doc: dict, page_id: str, screens: set[str]) -> dict[str, Any]:
    """What the pages list says about a page for the phone side."""
    return {"phone": page_id in screens}
