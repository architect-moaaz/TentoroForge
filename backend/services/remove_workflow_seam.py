"""Delete a workflow — the removal sibling of :mod:`services.add_workflow_seam`.

Deleting the file is the whole change; the references are not chased here. Every
Button/Form bound to the workflow now names one that does not exist, which the
completeness check ``workflow-not-defined`` surfaces so the composer rebinds or
drops the control. This is why the tool that calls it confirms first: a delete
is reference-breaking, and the blast radius is every control that dispatched it.
"""
from __future__ import annotations

import os

from services.atomic_apply import BundleOp


class RemoveWorkflowError(ValueError):
    """Raised when the seam cannot build a bundle. Caller renders the message."""


def build_remove_workflow_bundle(output_dir: str, *, workflow_id: str) -> list[BundleOp]:
    """Compose the atomic bundle that deletes the named workflow file.

    ``workflow_id`` is resolved the same case/separator-insensitive way every
    resolver in the system resolves it, so an ambiguous name is refused rather
    than deleting whichever file ``listdir`` yields first.
    """
    from services.edit_workflow_seam import _resolve_workflow_path

    workflow_id = str(workflow_id or "").strip()
    if not workflow_id:
        raise RemoveWorkflowError("workflow_id is required")

    path = _resolve_workflow_path(output_dir, workflow_id)
    if not path or not os.path.exists(path):
        raise RemoveWorkflowError(f"workflow not found: {workflow_id!r}")

    rel = os.path.relpath(path, output_dir)
    return [BundleOp(path=rel, content="", kind="delete")]
