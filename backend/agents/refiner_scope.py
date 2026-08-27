"""Refiner scoping preflight — cheap 1-turn LLM call that resolves an
open-ended user instruction into `{intent, files_to_read, files_to_edit}`
before the real refiner starts.

Why: run_refiner used to burn 5-10 turns just exploring the tree before
its first edit. On a 30-turn cap, a scoping-then-editing loop with one
failed build easily ran out of turns. Pre-scoping lets us:

  1. Pre-read the identified files and inject them into the refiner's
     first-turn prompt — the refiner starts already knowing the code.
  2. Bound the working set so the refiner doesn't touch files outside
     scope (kept as guidance, not enforcement).

Fail-open: any error returns None and the caller falls back to the
old unscoped flow.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import AssistantMessage, TextBlock

logger = logging.getLogger(__name__)


# Hard caps on scope size. Prevent a preflight that says "read every file"
# from ballooning the refiner's context window (which would negate the
# scoping benefit entirely).
_MAX_FILES_TO_READ = 8
_MAX_FILES_TO_EDIT = 6
_MAX_BYTES_PER_FILE = 12_000  # ~200 lines of typical TSX


_SCOPE_SYSTEM_PROMPT = """You are a scoping assistant. Given a user
instruction and an app model summary, return STRICT JSON identifying
which files the refiner should read (for context) and which it should
edit (to make the change). Do not output anything except the JSON.

Rules:
- files_to_read: files the refiner needs to UNDERSTAND before editing.
  Include the files_to_edit here too — the refiner needs to read what
  it edits. Keep the total small (≤8).
- files_to_edit: files that will actually be modified. Keep small (≤6).
- Prefer specific file paths from the app model over guesses.
- If unsure, err toward FEWER files, not more.

Output shape (STRICT):
{
  "intent": "one short sentence — what the user wants",
  "files_to_read": ["src/schemas/home.json", "src/db/schema/user.ts"],
  "files_to_edit": ["src/schemas/home.json"],
  "notes": "optional — any coordination that matters"
}
"""


async def scope_refiner_task(
    output_dir: str,
    instruction: str,
) -> dict[str, Any] | None:
    """Ask the model for a compact scope. Returns None on any failure so
    the caller falls back to the unscoped refiner flow.
    """
    os.environ.pop("CLAUDECODE", None)

    app_model = _read_app_model_summary(output_dir)
    if not app_model:
        return None

    user_prompt = (
        f"## Instruction\n{instruction.strip()}\n\n"
        f"## App model (files, entities, routes)\n{app_model}\n\n"
        "Return the scoping JSON now. JSON only, no prose."
    )

    options = ClaudeAgentOptions(
        system_prompt=_SCOPE_SYSTEM_PROMPT,
        allowed_tools=[],  # no tools; the app model is enough context
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=1,
        model="claude-sonnet-4-6",
    )

    text_out = ""
    try:
        async for msg in query(prompt=user_prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in getattr(msg, "content", []) or []:
                    if isinstance(block, TextBlock):
                        text_out += block.text
    except Exception as exc:  # noqa: BLE001 — never block refine on scoping
        logger.warning("[refiner_scope] LLM call failed: %s", exc)
        return None

    scope = _parse_scope_json(text_out)
    if scope is None:
        logger.warning("[refiner_scope] no valid JSON in scope response")
        return None

    # Clamp to caps so a runaway scope can't poison the refiner context.
    scope["files_to_read"] = _clamp_list(scope.get("files_to_read", []), _MAX_FILES_TO_READ)
    scope["files_to_edit"] = _clamp_list(scope.get("files_to_edit", []), _MAX_FILES_TO_EDIT)
    scope.setdefault("intent", instruction.strip()[:200])
    scope.setdefault("notes", "")
    return scope


def render_prescoped_files_block(output_dir: str, scope: dict[str, Any]) -> str:
    """Render `files_to_read` as a ready-to-inject prompt block. Missing
    files are silently skipped — the refiner can still Read them.
    """
    root = Path(output_dir)
    files = scope.get("files_to_read") or []
    if not files:
        return ""

    chunks: list[str] = []
    for rel in files:
        rel_path = str(rel).lstrip("/")
        if ".." in rel_path.split("/"):
            continue  # path traversal guard
        full = root / rel_path
        if not full.exists() or not full.is_file():
            continue
        try:
            data = full.read_bytes()[:_MAX_BYTES_PER_FILE]
            text = data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        # Language hint for the fenced block
        ext = full.suffix.lstrip(".")
        lang = {"tsx": "tsx", "ts": "ts", "json": "json", "js": "js"}.get(ext, "")
        chunks.append(f"### {rel_path}\n```{lang}\n{text}\n```")

    if not chunks:
        return ""

    header = (
        "## Pre-loaded files (already read; do not re-Read unless the file changed)\n"
        "These are the files the scoping pass identified. Start from these — "
        "you should not need to Read them again unless you're checking a change.\n\n"
    )
    return header + "\n\n".join(chunks) + "\n\n"


# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def _read_app_model_summary(output_dir: str, max_bytes: int = 20_000) -> str:
    """Return a size-bounded slice of app-model.json — enough for the
    scoping LLM to see routes/entities/files without blowing the prompt."""
    p = Path(output_dir) / "app-model.json"
    if not p.exists():
        return ""
    try:
        raw = p.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_scope_json(text: str) -> dict[str, Any] | None:
    """Extract the first JSON object from a possibly-noisy response."""
    if not text or not text.strip():
        return None
    # Try direct parse first
    try:
        obj = json.loads(text.strip())
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Fall back to greedy first-brace-to-last-brace
    m = _JSON_OBJ_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _clamp_list(value: Any, cap: int) -> list[str]:
    """Coerce to a list of strings, dedupe, clamp to `cap`."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        s = str(item).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= cap:
            break
    return out
