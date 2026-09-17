"""Every projection the Blueprint drives, for the one caller that needs them all.

Each seam re-projects narrowly and deliberately: a rule change writes the
rules, an access change writes the middleware and the seed, a field change
writes the data layer and the screens. Narrow is right — a rule change has no
business rewriting middleware.

An UNDO has no such scope. It restores a document that may differ from the
current one in any section at all, so it has to put every projection back in
step with what it restored. That is a different question from any of theirs,
which is why this is a new function rather than a fourth copy of one of them.

Best-effort per projector, and in dependency order: the data layer first
because the screens bind to its columns, tokens last because nothing reads
them. A projector that cannot run is logged and the rest still run — an undo
that restores the Blueprint and half the files is worse than one that restores
the Blueprint and says which file it could not write.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def everything(svc: Any, app_root: str | None) -> list[str]:
    """Re-project every part of the application from `svc.doc`."""
    if not app_root:
        return []
    from services.blueprint.orchestrator import _project_integration
    from services.blueprint.projection import (
        apply_frontend_projection, project_business_rules, project_data_layer,
        project_design_tokens, project_entity_access, project_launch_roles,
        project_middleware, project_public_resources, project_seed,
    )
    from services.smith import accounts as _accounts

    files: list[str] = []

    def _run(name: str, fn: Any) -> None:
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 — one projector, not the undo
            logger.warning("[reproject] %s failed: %s", name, exc)
            return
        if isinstance(out, dict):
            files.extend(str(f) for f in (out.get("files") or []))

    _run("data_layer", lambda: project_data_layer(svc.doc, app_root))
    # Workflow definitions, the connected-services map and the seed: the
    # projection node's own function, so a re-projection writes exactly what
    # a build writes.
    _run("integrations", lambda: _project_integration(svc, app_root))
    files += ["src/lib/workflows/definitions", "src/lib/integrations/connected.ts"]
    _run("frontend", lambda: apply_frontend_projection(svc, app_root))
    _run("business_rules", lambda: project_business_rules(svc.doc, app_root))
    for name, fn in (("middleware", project_middleware),
                     ("public_resources", project_public_resources),
                     ("entity_access", project_entity_access),
                     ("launch_roles", project_launch_roles)):
        _run(name, lambda fn=fn: fn(svc.doc, app_root))
    # AN UNDONE IMPORT MUST STOP BEING LOADED. The declaration is gone from
    # the restored document; its payload file has to go from the app tree too,
    # or the seeder applies it on the next boot and the undo undid nothing.
    # Before the seed, because the seed's content depends on which entities
    # still hold imported data.
    _run("imports", lambda: {"files": _reconcile_imports(svc.doc, app_root)})
    _run("seed", lambda: project_seed(svc.doc, app_root))
    # THE ROSTER IS NOT IN THE DOCUMENT, and is re-projected anyway. Who may
    # log in is a project ledger, not a Blueprint section (`smith.accounts`),
    # so restoring an older document must not disturb it — but the file the
    # seed reads lives in the app tree, and putting every projection back in
    # step means putting that one back too.
    _run("accounts", lambda: {"files": _accounts.project(svc.output_dir, app_root)})
    _run("design_tokens", lambda: project_design_tokens(svc.doc, app_root))
    return sorted(set(f for f in files if f))


def _reconcile_imports(doc: dict, app_root: str) -> list[str]:
    from services.smith.data_import import reconcile
    return reconcile(doc, app_root)


__all__ = ["everything"]
