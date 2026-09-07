"""Smith's Claude-Code-style file toolset — read/edit/verify against
the real app files, not the structural summaries.

The one-shot `propose_fix` flow leaves Smith blind: he authors a patch
from a `read_page` summary, the applier writes it, and he never sees
what actually landed. That's how the "I'll remove password" +
reorder-Switch drift happened.

These tools let him work like Claude Code does inside a real repo:

* ``read_file(path)`` — the literal bytes at ``output_dir / path``.
* ``edit_file(path, old_string, new_string)`` — exact-string replace,
  writes the file immediately, refuses no-op and ambiguous edits.
* ``verify_promise(path, claim)`` — parse the file, walk its
  identifiers, check the claim ("password field removed"). Level 1 of
  the runtime-verify story — a jsdom-based level 2 belongs to a
  future slice.

All three are sandboxed to ``output_dir``. Path escapes (``..``,
absolute paths outside the tree) and non-source extensions are
rejected. Every function returns a dict — never raises — so the
Smith loop can surface tool errors back to the model without
crashing.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Only these extensions are editable — protects against Smith editing
# unrelated binaries, secrets, or lockfiles.
_ALLOWED_EXT: set[str] = {
    ".json", ".ts", ".tsx", ".js", ".jsx",
    ".md", ".txt", ".css", ".scss",
    ".mjs", ".cjs", ".mts",
}
_MAX_READ_BYTES = 200_000
_MAX_LINES = 500

# Identifier keys we treat as salient when walking a schema tree — the
# ones that carry a user-visible name a natural-language claim can
# refer to. Kept broad on purpose: false-positive matches are fine
# because the coherence check is a rough "did the promise hold" gate,
# not a schema validator.
_ID_KEYS: set[str] = {
    "name", "label", "id", "type", "title", "route", "key",
    "field", "workflow", "component", "entity",
}


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #

def _safe_path(output_dir: str, rel_path: Any) -> Path | None:
    """Resolve ``rel_path`` under ``output_dir``. Returns None on any
    escape attempt, absolute-outside-root path, or disallowed
    extension. Directories are permitted (read_file rejects them
    separately) so a callers can list them via other tools."""
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    try:
        root = Path(output_dir).resolve()
        # An absolute path is fine IF it lands inside the project — the
        # containment check below is what actually enforces the boundary.
        # Rejecting every absolute path was over-broad and created two path
        # dialects across one seam: `edit_workflow` returns a path that
        # `verify_promise` then refused to read, so the verify step Smith is
        # REQUIRED to run could not consume the edit's own output
        # (register S24-7). `(root / abs)` in pathlib yields `abs`, so the
        # join alone is not a guard — `relative_to(root)` is.
        candidate = Path(rel_path)
        p = (candidate if candidate.is_absolute() else root / rel_path).resolve()
    except Exception:
        return None
    try:
        p.relative_to(root)
    except ValueError:
        return None
    if p.suffix and p.suffix.lower() not in _ALLOWED_EXT:
        return None
    return p


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #

def read_file(output_dir: str, args: dict) -> dict:
    """Return the literal contents of ``args["path"]`` (relative to
    the app root). Truncates on very long files so a runaway Smith
    read of a 20k-line lockfile can't blow up the context window."""
    rel = args.get("path")
    p = _safe_path(output_dir, rel)
    if p is None:
        return {"error": f"invalid or forbidden path: {rel!r}"}
    if not p.exists():
        return {"error": f"file not found: {rel}"}
    if p.is_dir():
        return {"error": f"path is a directory, not a file: {rel}"}
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"read failed: {exc}"}
    truncated = False
    if len(content.encode("utf-8", errors="replace")) > _MAX_READ_BYTES:
        content = content[:_MAX_READ_BYTES]
        truncated = True
    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines > _MAX_LINES:
        content = "\n".join(lines[:_MAX_LINES])
        content += f"\n… [truncated at {_MAX_LINES}/{total_lines} lines]"
        truncated = True
    return {
        "path": rel,
        "content": content,
        "lines": total_lines,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------- #
# edit_file
# --------------------------------------------------------------------------- #

def edit_file(output_dir: str, args: dict) -> dict:
    """Exact-string replace. Refuses ambiguous or no-op edits so Smith
    can't silently overwrite the wrong region or claim work he didn't
    do.

    Args::

        {"path":       "src/schemas/referrals/new.json",
         "old_string": "…exact substring, unique in the file…",
         "new_string": "…what to replace it with…"}

    On success returns ``{edited, path, matches_replaced, before_len,
    after_len}``. On any error returns ``{error}`` — the loop surfaces
    that back to the model so it can adjust and retry.
    """
    rel = args.get("path")
    old = args.get("old_string")
    new = args.get("new_string")
    if not isinstance(rel, str) or not rel.strip():
        return {"error": "path required"}
    if not isinstance(old, str) or old == "":
        return {"error": "old_string required (non-empty string)"}
    if not isinstance(new, str):
        return {"error": "new_string required (string; may be empty to delete)"}
    if old == new:
        return {"error": "old_string == new_string — no-op edit refused"}
    p = _safe_path(output_dir, rel)
    if p is None:
        return {"error": f"invalid or forbidden path: {rel!r}"}
    if not p.exists():
        return {"error": f"file not found: {rel}"}
    if p.is_dir():
        return {"error": f"path is a directory, not a file: {rel}"}
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"read failed: {exc}"}
    count = content.count(old)
    if count == 0:
        return {"error": f"old_string not found in {rel}"}
    if count > 1:
        return {
            "error": (
                f"old_string matches {count} places in {rel} — make it "
                "unique (add surrounding context) or split into per-match edits"
            ),
        }
    new_content = content.replace(old, new, 1)

    # Structural check BEFORE the write (register S21-1). The only guard used
    # to be "old_string occurs exactly once", so a splice any model could
    # produce — dropping one brace — wrote a workflow that is no longer valid
    # JSON, reported success, and broke every reader of that file. Refusing
    # before touching the disk is stronger than writing and reverting: the
    # file on disk is never in the broken state at all.
    struct_error = _structural_error(rel, new_content)
    if struct_error:
        return {"error": struct_error}

    try:
        p.write_text(new_content, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"write failed: {exc}"}

    result = {
        "edited": True,
        "path": rel,
        "matches_replaced": 1,
        "before_len": len(content),
        "after_len": len(new_content),
    }

    # Run the SAME graph gate fresh generation runs (register S21-2). It used
    # to be called only from `post_generate_fixes`, so a Smith edit could
    # leave a dangling edge, delete the end node or set an unknown
    # actionType and the one pass that catches those never ran on this path.
    gate = _run_graph_gate(output_dir, rel)
    if gate:
        result["gate"] = gate

    # Refresh BLUEPRINT.md so the app snapshot Smith reads next turn
    # reflects this edit. Best-effort; idempotent when the edit didn't
    # affect summarized fields. Never poisons the edit return.
    try:
        from services.blueprint_writer import write_blueprint_safe
        write_blueprint_safe(
            output_dir,
            source="smith",
            summary=f"Smith edit_file: {rel}",
        )
    except Exception:  # noqa: BLE001
        pass  # writer already logs; edit_file must never fail on it
    return result


# --------------------------------------------------------------------------- #
# Post-edit structural guards — shared by every Smith write path
# --------------------------------------------------------------------------- #

def _structural_error(rel: str, content: str) -> str | None:
    """The reason ``content`` must not be written to ``rel``, or None.

    Today this is JSON well-formedness, which covers workflows, contracts
    and the registry — the files whose corruption is silent and total.
    """
    if not rel.lower().endswith(".json"):
        return None
    try:
        json.loads(content)
    except ValueError as exc:
        return (
            f"refusing the edit: it would leave {rel} unparseable as JSON "
            f"({exc}). The file on disk is unchanged. Re-issue the edit with "
            f"balanced braces/brackets and no trailing comma."
        )
    return None


def _run_graph_gate(output_dir: str, rel: str) -> dict | None:
    """Gate + repair the project's workflows after a workflow file changed.

    Returns a summary for the tool result (so the repair is VISIBLE to Smith
    rather than a silent rewrite), or None when the edit did not touch a
    workflow. Never raises: a gate failure must be reported, not allowed to
    swallow an edit that already succeeded.
    """
    norm = rel.replace("\\", "/").lower()
    if not (norm.startswith("workflows/") and norm.endswith(".json")):
        return None
    try:
        from services.workflow_graph_gate import run_workflow_gate
        summary = run_workflow_gate(output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.exception("smith_edit_tools: workflow graph gate failed for %s", rel)
        return {"error": f"graph gate failed after the edit: {exc}"}
    if not isinstance(summary, dict):
        return None
    return {
        "checked": summary.get("checked"),
        "repaired": summary.get("repaired"),
        "warnings": summary.get("warnings"),
        "errors": summary.get("errors"),
    }


# --------------------------------------------------------------------------- #
# verify_promise — level-1 runtime verification
# --------------------------------------------------------------------------- #

def verify_promise(output_dir: str, args: dict) -> dict:
    """Check whether a plain-language claim about a file actually
    holds against the file's current contents. Level 1 (byte / JSON
    inspection) of the runtime-verify story — jsdom-render is a later
    slice.

    Args::

        {"path":  "src/schemas/referrals/new.json",
         "claim": "the password field is removed"}

    Uses the same verb+noun phrase extractor as the coherence gate so
    the vocabulary is consistent. Returns ``{kept, ...}``:

    * ``{kept: True, ...}`` — every strong verb+noun phrase in the
      claim was satisfied by the file. Also returned when the claim
      was too vague to enforce (false-negative bias, matching
      check_patch_coherence — a vague claim isn't evidence of
      failure).
    * ``{kept: False, failures: [{phrase, evidence, ...}], ...}`` —
      one or more promises are broken; ``evidence`` names the
      identifier(s) that still contain the noun for a ``remove``, or
      states "not found" for an ``add``.
    """
    from services.patch_coherence import _extract_phrases

    rel = args.get("path")
    claim = args.get("claim")
    if not isinstance(rel, str) or not rel.strip():
        return {"error": "path required"}
    if not isinstance(claim, str) or not claim.strip():
        return {"error": "claim required"}
    p = _safe_path(output_dir, rel)
    if p is None:
        return {"error": f"invalid or forbidden path: {rel!r}"}
    if not p.exists():
        return {"error": f"file not found: {rel}"}
    if p.is_dir():
        return {"error": f"path is a directory, not a file: {rel}"}
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"read failed: {exc}"}

    phrases = _extract_phrases(claim)
    if not phrases:
        return {
            "kept": True,
            "reason": (
                "claim has no strong verb+noun phrase to enforce "
                "(vague claim — pass-through)"
            ),
        }

    # Prefer structural JSON walk when the file parses; fall back to
    # substring check on non-JSON so .ts/.tsx claims still get a
    # rough answer.
    try:
        data = json.loads(content)
        return _verify_schema(phrases, data)
    except (ValueError, TypeError):
        return _verify_substring(phrases, content)


# --------------------------------------------------------------------------- #
# Internals — schema walk + substring fallback
# --------------------------------------------------------------------------- #

def _verify_schema(phrases: list[tuple[str, str]], data: Any) -> dict:
    """Walk the parsed schema, collect every salient identifier
    string, and check each verb+noun phrase against it."""
    identifiers = _walk_identifiers(data)
    return _score_phrases(phrases, identifiers, mode="schema")


def _verify_substring(phrases: list[tuple[str, str]], content: str) -> dict:
    """Non-JSON files: fall back to normalized substring inspection."""
    return _score_phrases(phrases, [content], mode="substring")


def _score_phrases(
    phrases: list[tuple[str, str]],
    haystack_strings: list[str],
    *,
    mode: str,
) -> dict:
    """Shared verdict logic for schema + substring modes.

    remove : phrase noun MUST NOT appear in any identifier / substring
    add    : phrase noun MUST appear at least once
    rename : phrase noun MUST appear at least once (softer — a rename
             leaves the OLD name gone but the NEW name present, and
             the claim usually names one of the two)
    replace: same as rename
    """
    failures: list[dict] = []
    haystack_norm = [_norm(s) for s in haystack_strings if s]

    for kind, noun in phrases:
        n = _norm(noun)
        if not n:
            continue
        # A "hit" is a bidirectional substring on normalized strings —
        # matches the tolerance the coherence gate uses.
        hits = [
            haystack_strings[i]
            for i, h in enumerate(haystack_norm)
            if h and (n in h or h in n)
        ]
        found = len(hits) > 0
        if kind == "remove" and found:
            failures.append({
                "phrase": f"{kind} {noun}",
                "evidence": (
                    f"still present in {len(hits)} location(s): "
                    f"{list(dict.fromkeys(hits))[:5]}"
                ),
            })
        elif kind in ("add",) and not found:
            failures.append({
                "phrase": f"{kind} {noun}",
                "evidence": f"not found in file ({mode} check)",
            })
        # rename/replace: we cannot cheaply tell "old gone AND new
        # present" from claim text alone. Skip the enforcement rather
        # than false-flag; the pre-apply coherence gate catches the
        # bulk of rename drift already.

    if failures:
        return {"kept": False, "failures": failures,
                "identifiers_scanned": len(haystack_strings)}
    return {"kept": True,
            "reason": f"verified {len(phrases)} phrase(s) via {mode} check",
            "identifiers_scanned": len(haystack_strings)}


def _walk_identifiers(node: Any) -> list[str]:
    """Depth-first traversal collecting every salient identifier
    string in a schema tree. Duplicates are preserved because a
    ``remove`` verdict wants an accurate hit-count for the evidence
    message."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _ID_KEYS and isinstance(v, str) and v:
                out.append(v)
            out.extend(_walk_identifiers(v))
    elif isinstance(node, list):
        for item in node:
            out.extend(_walk_identifiers(item))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
