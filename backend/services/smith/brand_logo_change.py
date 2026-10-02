"""The owner's logo becomes part of the application's definition.

`restyle` owns `designSystem` and re-decides it through the design agent: a
palette is a judgement, and the agent is what makes it. A logo is not a
judgement. It is a file the owner handed over, and there is nothing for a model
to decide about it — so this writes the section deterministically, the way
`field_change` renames a column, rather than briefing an agent to repeat back a
path it was given.

It is still the same section, written the same way: mutate, `validate`,
`commit` with the prior snapshot so the change is in `changeHistory` and `undo`
can take it back out, then re-project. The two projections that matter are
`project_shell` — which puts the reference in the rail — and
`project_brand_logo`, which puts the file where that reference resolves.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)


class BrandLogoChangeError(Exception):
    """The mark could not be set, with the reason the owner can act on."""


def _project(svc: Any, app_root: str | None) -> list[str]:
    """The rail and the file, in that order — the rail names the file."""
    if not app_root:
        return []
    from services.blueprint.projection import project_brand_logo, project_shell

    files: list[str] = []
    files += list(project_shell(svc.doc, app_root).get("files") or [])
    files += list(project_brand_logo(svc.doc, app_root).get("files") or [])
    return files


def set_logo(svc: Any, logo: dict, *, app_root: str | None = None,
             alt: str = "", reasoning: Any = None) -> dict:
    """Record `logo` as the application's mark and put it in the tree.

    `logo` is what :func:`services.brand_logo.store` returned — the contract
    body, already written to disk beside the Blueprint. Nothing here invents
    a path: a `designSystem.logo.file` that names a file the project does not
    have is a document that lies, and the projection would then reference an
    image that 404s on every screen.
    """
    from services import brand_logo as store

    if not isinstance(logo, dict) or not str(logo.get("file") or "").strip():
        raise BrandLogoChangeError("no logo file was given, so there is nothing to put in.")
    if store.path_of(svc.output_dir, logo) is None:
        raise BrandLogoChangeError(
            f"the logo file {logo.get('file')!r} is not in this project — "
            "upload it again and I will put it in.")

    design = svc.doc.setdefault("designSystem", {})
    previous = design.get("logo") if isinstance(design.get("logo"), dict) else None
    body = dict(logo)
    if alt.strip():
        body["alt"] = alt.strip()
    if body == previous:
        raise BrandLogoChangeError("that is already this application's logo.")

    before = svc.snapshot()
    design["logo"] = body
    svc.validate()
    svc.commit(
        user_request="put the logo in the application",
        smith_interpretation=("replace the application's mark" if previous
                              else "set the application's mark"),
        before=before,
        # No artifact ids: `affectedArtifacts` is a list of them (REQ-, PAGE-,
        # ENTITY-…) and `designSystem` is a singleton section with none. The
        # `blueprintDiff` on this record names the field that moved.
        affected=(),
    )
    tell(reasoning, "The logo is in the corner of every screen now.", "step")
    return {"applied": True, "logo": body, "previous": previous,
            "edited_paths": _project(svc, app_root),
            "version": svc.doc.get("version", 1)}


def clear_logo(svc: Any, *, app_root: str | None = None,
               reasoning: Any = None) -> dict:
    """Take the mark back off; the rail returns to the application's initial.

    The stored file is left where it is. It is content-addressed and unread
    once nothing references it, and deleting it would break `undo`, which
    restores a document that names it.
    """
    design = svc.doc.setdefault("designSystem", {})
    previous = design.get("logo")
    if not isinstance(previous, dict):
        raise BrandLogoChangeError("this application has no logo, so there is none to remove.")
    before = svc.snapshot()
    design.pop("logo", None)
    svc.validate()
    svc.commit(user_request="take the logo out of the application",
               smith_interpretation="clear the application's mark",
               before=before, affected=())
    tell(reasoning, "The logo is off; the rail shows the application's initial again.", "step")
    return {"applied": True, "logo": None, "previous": previous,
            "edited_paths": _project(svc, app_root),
            "version": svc.doc.get("version", 1)}


def summary_of(out: dict) -> str:
    """One sentence the owner can read."""
    logo = out.get("logo")
    if not logo:
        return ("Took the logo out. The rail shows the application's initial again, "
                "the way it did before.")
    size = (f" ({logo['width']}×{logo['height']})"
            if logo.get("width") and logo.get("height") else "")
    verb = "Replaced the logo" if out.get("previous") else "Put the logo in"
    return (f"{verb}{size}. It is in the corner of every screen — the rail's brand "
            f"block, where the application's initial used to be — and it travels "
            f"with the application, so a rebuild still has it.")


def run(output_dir: str, *, logo: dict | None = None, alt: str = "",
        remove: bool = False, reasoning: Any = None) -> dict:
    """The verb envelope — `{applied, edited_paths, diff_summary, reason}`, the
    shape `restyle.run` returns, so the route, the session and the tool loop
    share one implementation."""
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there is no "
                          "design system to put a logo in."}
    app_root = str(Path(output_dir) / "app")
    try:
        out = (clear_logo(svc, app_root=app_root, reasoning=reasoning) if remove
               else set_logo(svc, logo or {}, app_root=app_root, alt=alt,
                             reasoning=reasoning))
    except BrandLogoChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a verb degrades, it does not crash
        logger.exception("[smith] set_logo failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out["edited_paths"],
            "diff_summary": summary_of(out), "version": out["version"],
            "logo": out["logo"], "reason": ""}


__all__ = ["BrandLogoChangeError", "clear_logo", "run", "set_logo", "summary_of"]
