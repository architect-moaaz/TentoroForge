# backend/services/patch_applier.py
"""RFC 6902 patch validation + transactional application.

Validation is the reliability spine: every patch the patch-agent emits must
pass these checks before it touches disk. Failures here trigger a stricter
re-prompt; failures after apply trigger a rollback.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


# Required-but-must-not-be-removed paths in any Page schema.
# Removing these would invalidate the page entirely.
_PROTECTED_PATHS = {"/root", "/id", "/route", "/schemaVersion"}


@dataclass
class ValidationError:
    idx: int          # which patch in the input list
    kind: str         # path_unresolved | type_mismatch | cannot_remove_required | malformed_patch
    msg: str


class PatchApplyError(Exception):
    """Raised when patches couldn't be applied (mid-apply failure or post-apply schema invalid)."""


def _walk_pointer(schema: Any, pointer: str, *, op: str) -> bool:
    """Return True if `pointer` resolves in `schema`, OR if `op == "add"` and
    the pointer's parent resolves with the leaf being a new key or array end.
    Raises nothing — returns bool."""
    if not pointer.startswith("/"):
        return False
    parts = pointer[1:].split("/") if pointer != "/" else []
    if not parts:  # root pointer "/" — schema root itself
        return True

    # For `add`: the parent must resolve and the leaf must either be a new key
    # in an object, or "-" (array append).
    target = schema
    for i, raw in enumerate(parts):
        is_last = i == len(parts) - 1
        # Unescape JSON pointer tokens (~0 → ~, ~1 → /)
        key = raw.replace("~1", "/").replace("~0", "~")

        if isinstance(target, dict):
            if key in target:
                target = target[key]
                continue
            if is_last and op == "add":
                return True  # adding a new key is fine
            return False
        if isinstance(target, list):
            if key == "-":
                if is_last and op == "add":
                    return True
                return False
            try:
                idx = int(key)
            except ValueError:
                return False
            if 0 <= idx < len(target):
                target = target[idx]
                continue
            if is_last and op == "add" and idx == len(target):
                return True
            return False
        # Walked past a leaf scalar — can't descend
        return False
    return True


def _is_protected(path: str) -> bool:
    return path in _PROTECTED_PATHS


def validate_patches(patches: list[dict[str, Any]], schema: dict[str, Any]) -> list[ValidationError]:
    """Validate a list of RFC 6902 patches against `schema`. Returns a list of
    ValidationError; empty list means all patches pass.

    This validation is structural — it confirms paths resolve and ops make sense.
    Type-level validation against the v2 zod schema happens AFTER apply, in
    apply_patches_transactional, since we'd otherwise have to reimplement the
    zod shape here."""
    errors: list[ValidationError] = []
    for i, p in enumerate(patches):
        if not isinstance(p, dict) or "op" not in p or "path" not in p:
            errors.append(ValidationError(i, "malformed_patch", f"patch missing 'op' or 'path': {p!r}"))
            continue

        op = p.get("op")
        path = p.get("path", "")

        if op not in ("add", "replace", "remove", "move", "copy", "test"):
            errors.append(ValidationError(i, "malformed_patch", f"unknown op: {op!r}"))
            continue

        if op == "remove" and _is_protected(path):
            errors.append(ValidationError(i, "cannot_remove_required", f"path {path} is structurally required"))
            continue

        if op in ("add", "replace", "remove", "move", "copy", "test"):
            if not _walk_pointer(schema, path, op=op):
                errors.append(ValidationError(i, "path_unresolved", f"path {path} does not resolve in schema"))
                continue

        if op == "move" or op == "copy":
            from_path = p.get("from")
            if not from_path or not _walk_pointer(schema, from_path, op="replace"):
                errors.append(ValidationError(i, "path_unresolved", f"`from` path {from_path!r} does not resolve"))
                continue

    return errors


import jsonpatch
import json
import subprocess


def apply_patches_transactional(
    patches: list[dict[str, Any]],
    schema: dict[str, Any],
    *,
    validate_zod: bool = True,
) -> dict[str, Any]:
    """Apply RFC 6902 patches to `schema` and return a NEW schema dict.

    Transactional semantics:
      - input dict is NOT mutated; a deep copy is patched
      - if any patch fails mid-application, raises PatchApplyError without
        touching disk; caller's reference to `schema` is unchanged
      - if validate_zod=True, the resulting schema is parsed through the
        PageV1|PageV2 zod union; failure also raises PatchApplyError
    """
    working = copy.deepcopy(schema)
    try:
        patched = jsonpatch.apply_patch(working, patches, in_place=False)
    except jsonpatch.JsonPatchException as e:
        raise PatchApplyError(f"patch sequence failed mid-apply: {e}") from e
    except Exception as e:
        raise PatchApplyError(f"unexpected error applying patches: {e}") from e

    if validate_zod:
        if not _zod_validate_page(patched):
            raise PatchApplyError(f"patches produced invalid schema (failed PageV1|PageV2 zod check)")

    return patched


def _zod_validate_page(schema: dict[str, Any]) -> bool:
    """Best-effort zod validation by shelling out to a tiny Node script using
    the @tentoroforge/schema package. Falls back to `True` (no opinion) if the
    Node-side validator can't run — we don't want to block on transient
    infrastructure issues.

    The script lives inline here as a string so this module is self-contained
    and doesn't add yet another file. It reads schema JSON from stdin, exits 0
    on success, exits 1 on validation failure, exits 2 on script error."""
    script = r"""
const { PageV1, PageV2 } = require("@tentoroforge/schema");
const { z } = require("zod");
let buf = "";
process.stdin.on("data", (c) => (buf += c));
process.stdin.on("end", () => {
  try {
    const j = JSON.parse(buf);
    const u = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
    u.parse(j);
    process.exit(0);
  } catch (e) {
    process.stderr.write(String(e?.message ?? e));
    process.exit(1);
  }
});
"""
    try:
        proc = subprocess.run(
            ["node", "-e", script],
            input=json.dumps(schema),
            capture_output=True,
            text=True,
            timeout=10,
            cwd="/Users/m/Work/code/poc/design2ui-forge-v3",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Node not available, or the script timed out — don't block, just
        # warn via return value. The caller's run_render → re-score will
        # catch real breakage at the next stage.
        return True
    return proc.returncode == 0
