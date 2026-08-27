"""Tool primitives for _tool_app_modifier.

Sandboxed Read / Bash / Edit / Write + a structured RegistryPatch.
Every tool is scoped to the target project's output_dir. Nothing here
touches the platform code, the DB, or the network. If a tool is asked
to do anything outside the sandbox it returns a failure result — it
never raises so the ReAct loop can surface it to the LLM.

Contract for every tool:
  * Returns dict {ok: bool, ...}. Never raises on user error.
  * Reads/writes UTF-8 unless the caller says otherwise.
  * Absolute paths outside ``output_dir`` are rejected.
"""
from __future__ import annotations

import json
import logging
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Path safety
# --------------------------------------------------------------------------- #

def _resolve_inside(output_dir: str, path: str) -> Path | None:
    """Resolve ``path`` under ``output_dir`` or return None when it
    would escape the sandbox."""
    try:
        root = Path(output_dir).resolve()
        # Allow both absolute-within-root and relative-to-root
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (root / p).resolve()
        # Must be under root
        try:
            resolved.relative_to(root)
        except ValueError:
            return None
        return resolved
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #

_MAX_READ_BYTES = 200_000
_MAX_READ_LINES = 2_000


def read_tool(
    output_dir: str, path: str,
    *, offset: int = 0, limit: int | None = None,
) -> dict:
    """Read a file under ``output_dir``. Returns lines (numbered) plus
    a truncation flag. Bounded at 200KB / 2000 lines to keep the loop
    honest."""
    p = _resolve_inside(output_dir, path)
    if p is None:
        return {"ok": False, "error": f"path outside sandbox: {path!r}"}
    if not p.exists():
        return {"ok": False, "error": f"file not found: {path!r}"}
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {path!r}"}
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"read failed: {exc}"}
    if len(raw) > _MAX_READ_BYTES:
        raw = raw[:_MAX_READ_BYTES]
        truncated = True
    else:
        truncated = False
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        text = raw.decode("latin-1", errors="replace")
    lines = text.split("\n")
    total_lines = len(lines)
    if limit is None:
        limit = _MAX_READ_LINES
    view = lines[offset: offset + limit]
    if offset + len(view) < total_lines:
        truncated = True
    numbered = "\n".join(
        f"{offset + i + 1:6d}  {ln}" for i, ln in enumerate(view)
    )
    return {
        "ok": True,
        "content": numbered,
        "lines": total_lines,
        "shown": len(view),
        "offset": offset,
        "truncated": truncated,
    }


# --------------------------------------------------------------------------- #
# Bash (allowlisted, sandboxed)
# --------------------------------------------------------------------------- #

_BASH_ALLOWLIST = {
    # inspection
    "grep", "rg", "find", "cat", "head", "tail", "wc", "ls", "test",
    "diff", "git",
    # data
    "jq",
    # python one-liners for validation
    "python3", "python",
    # misc
    "true", "false", "echo",
}

_BASH_TIMEOUT_S = 15
_BASH_OUTPUT_CAP = 20_000


def bash_tool(
    output_dir: str, command: str,
    *, cwd: str | None = None,
) -> dict:
    """Run a shell command scoped to ``output_dir``. First token must
    be in the allowlist. ``cwd`` (if given) must resolve inside
    ``output_dir`` or the repo root's ``packages/`` (read-only reference).
    Timeout + output cap enforced."""
    if not command or not isinstance(command, str):
        return {"ok": False, "error": "empty command"}
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {"ok": False, "error": f"unparseable command: {exc}"}
    if not parts:
        return {"ok": False, "error": "empty command after parse"}
    head = parts[0].split("/")[-1]  # allow /usr/bin/grep
    if head not in _BASH_ALLOWLIST:
        return {
            "ok": False,
            "error": f"command {head!r} not in allowlist: "
                     f"{sorted(_BASH_ALLOWLIST)}",
        }

    # git subcommand allowlist — read-only inspection only.
    if head == "git":
        _GIT_SUB_OK = {"status", "diff", "log", "show", "ls-files"}
        sub = parts[1] if len(parts) > 1 else ""
        if sub not in _GIT_SUB_OK:
            return {
                "ok": False,
                "error": f"git subcommand {sub!r} not allowed; "
                         f"read-only allowed: {sorted(_GIT_SUB_OK)}",
            }

    root = Path(output_dir).resolve()
    if cwd:
        cwd_p = _resolve_inside(output_dir, cwd) or _resolve_reference(cwd)
        if cwd_p is None:
            return {"ok": False, "error": f"cwd outside sandbox: {cwd!r}"}
        cwd_run = str(cwd_p)
    else:
        cwd_run = str(root)

    t0 = time.monotonic()
    try:
        r = subprocess.run(
            parts, cwd=cwd_run, capture_output=True, text=True,
            timeout=_BASH_TIMEOUT_S, env={
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                "LANG": "C.UTF-8"},
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {_BASH_TIMEOUT_S}s"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"exec failed: {exc}"}
    elapsed = time.monotonic() - t0

    stdout = (r.stdout or "")[:_BASH_OUTPUT_CAP]
    stderr = (r.stderr or "")[:_BASH_OUTPUT_CAP]
    truncated = (
        len(r.stdout or "") > _BASH_OUTPUT_CAP
        or len(r.stderr or "") > _BASH_OUTPUT_CAP
    )
    return {
        "ok": True,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": r.returncode,
        "elapsed_s": round(elapsed, 2),
        "truncated": truncated,
    }


def _resolve_reference(path: str) -> Path | None:
    """Allow read-only reference lookups under repo-root/packages/."""
    try:
        p = Path(path).resolve()
        # Walk up from this file to find repo root (has ``packages/``)
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "packages").is_dir():
                pkgs = (parent / "packages").resolve()
                try:
                    p.relative_to(pkgs)
                    return p
                except ValueError:
                    return None
    except Exception:  # noqa: BLE001
        pass
    return None


# --------------------------------------------------------------------------- #
# Edit — exact-string replace, unique or replace_all
# --------------------------------------------------------------------------- #

def edit_tool(
    output_dir: str, path: str, old_string: str, new_string: str,
    *, replace_all: bool = False,
) -> dict:
    """Exact-string replace inside a file under ``output_dir``.
    Refuses ambiguous matches unless ``replace_all=True``. Atomic
    write via ``.tmp`` + rename."""
    p = _resolve_inside(output_dir, path)
    if p is None:
        return {"ok": False, "error": f"path outside sandbox: {path!r}"}
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"file not found: {path!r}"}
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        return {"ok": False, "error": "old_string and new_string must be strings"}
    if not old_string:
        return {"ok": False, "error": "old_string cannot be empty"}
    try:
        current = p.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"read failed: {exc}"}

    matches = current.count(old_string)
    if matches == 0:
        return {"ok": False, "error": "old_string not found"}
    if matches > 1 and not replace_all:
        return {
            "ok": False,
            "error": f"ambiguous — {matches} matches; pass replace_all=True "
                     "or lengthen the old_string anchor",
        }
    if replace_all:
        updated = current.replace(old_string, new_string)
        replaced = matches
    else:
        updated = current.replace(old_string, new_string, 1)
        replaced = 1

    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(updated, encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        return {"ok": False, "error": f"write failed: {exc}"}
    return {"ok": True, "matches_replaced": replaced, "new_size": len(updated)}


# --------------------------------------------------------------------------- #
# Write — refuses existing path
# --------------------------------------------------------------------------- #

def write_tool(output_dir: str, path: str, content: str) -> dict:
    """Create a new file. Refuses if the path already exists — the
    agent must think about overwriting deliberately (via edit_tool)."""
    p = _resolve_inside(output_dir, path)
    if p is None:
        return {"ok": False, "error": f"path outside sandbox: {path!r}"}
    if p.exists():
        return {
            "ok": False,
            "error": f"path exists — use edit_tool to modify: {path!r}",
        }
    if not isinstance(content, str):
        return {"ok": False, "error": "content must be a string"}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"write failed: {exc}"}
    return {"ok": True, "path": str(p.relative_to(Path(output_dir).resolve())),
            "size": len(content)}


# --------------------------------------------------------------------------- #
# RegistryPatch — structured mutations to registry / plan / contracts
# --------------------------------------------------------------------------- #

_KIND_TO_LOCATIONS = {
    # kind → (registry_key, plan_key or None, contracts_key or None)
    "entity":     ("entities",      "data_models", None),
    "page":       ("pages",         "pages",       None),
    "workflow":   ("workflows",     "workflows",   None),
    "dataSource": ("dataSources",   None,          None),
    "action":     (None,            None,          "actions"),
}


def _find_by_key(items: list, key: str, value: Any) -> int:
    for i, e in enumerate(items or []):
        if isinstance(e, dict) and e.get(key) == value:
            return i
    return -1


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def registry_patch_tool(
    output_dir: str, kind: str, op: str, entry: dict,
) -> dict:
    """Structured update to registry.json + plan.json + contracts/*.

    Args:
      kind: "entity" | "page" | "workflow" | "dataSource" | "action"
      op:   "add" | "remove" | "update"
      entry: JSON shape appropriate to kind. Must have a stable key —
             ``name`` for entities/workflows/dataSources/actions, ``route``
             for pages.

    Returns {ok, files_touched, delta}. The tool updates every
    representation that carries this kind (registry, plan, contracts)
    keeping them in sync.
    """
    if kind not in _KIND_TO_LOCATIONS:
        return {"ok": False, "error": f"unknown kind: {kind!r}"}
    if op not in ("add", "remove", "update"):
        return {"ok": False, "error": f"unknown op: {op!r}"}
    if not isinstance(entry, dict):
        return {"ok": False, "error": "entry must be a dict"}

    key_field = "route" if kind == "page" else "name"
    if not entry.get(key_field):
        return {
            "ok": False,
            "error": f"entry missing required key {key_field!r} for kind {kind!r}",
        }

    root = Path(output_dir).resolve()
    registry_key, plan_key, contracts_key = _KIND_TO_LOCATIONS[kind]

    files_touched: list[dict] = []

    # ── registry.json + contracts/resource-registry.json ────────────
    if registry_key:
        for reg_path in (
            root / "registry.json",
            root / "contracts" / "resource-registry.json",
        ):
            reg = _load_json(reg_path)
            if reg is None:
                continue
            section = reg.get(registry_key)
            if isinstance(section, dict):
                # dict-shape (registry.json's entities)
                name = entry[key_field]
                if op == "add" or op == "update":
                    section[name] = entry
                elif op == "remove":
                    section.pop(name, None)
                reg[registry_key] = section
            else:
                if not isinstance(section, list):
                    section = []
                idx = _find_by_key(section, key_field, entry[key_field])
                if op == "add":
                    if idx == -1:
                        section.append(entry)
                elif op == "update":
                    if idx >= 0:
                        section[idx] = entry
                    else:
                        section.append(entry)
                elif op == "remove":
                    if idx >= 0:
                        section.pop(idx)
                reg[registry_key] = section
            _save_json(reg_path, reg)
            files_touched.append({"path": str(reg_path.relative_to(root)),
                                  "action": "modified"})

    # ── plan.json (only for structural adds) ────────────────────────
    if plan_key and op != "update":
        plan_path = root / "plan.json"
        plan = _load_json(plan_path)
        if plan is not None:
            section = plan.get(plan_key) or []
            if not isinstance(section, list):
                section = []
            idx = _find_by_key(section, key_field, entry[key_field])
            if op == "add" and idx == -1:
                section.append(entry)
            elif op == "remove" and idx >= 0:
                section.pop(idx)
            plan[plan_key] = section
            _save_json(plan_path, plan)
            files_touched.append({"path": "plan.json", "action": "modified"})

    # ── contracts/*.json ────────────────────────────────────────────
    if contracts_key:
        contract_path = root / "contracts" / "action-contract.json"
        contract = _load_json(contract_path) or {}
        section = contract.get(contracts_key) or []
        if not isinstance(section, list):
            section = []
        idx = _find_by_key(section, key_field, entry[key_field])
        if op == "add" and idx == -1:
            section.append(entry)
        elif op == "update" and idx >= 0:
            section[idx] = entry
        elif op == "remove" and idx >= 0:
            section.pop(idx)
        contract[contracts_key] = section
        _save_json(contract_path, contract)
        files_touched.append({"path": "contracts/action-contract.json",
                              "action": "modified"})

    return {"ok": True, "files_touched": files_touched,
            "delta": {"kind": kind, "op": op, "key": entry[key_field]}}


# --------------------------------------------------------------------------- #
# Public catalog for the agent's tool palette
# --------------------------------------------------------------------------- #

TOOL_CATALOG: list[dict] = [
    {"name": "Read",
     "signature": "Read(path, offset?, limit?) -> {ok, content, lines, truncated}",
     "desc": "Read a file under the project's output_dir. Returns "
             "line-numbered content; capped at 200KB / 2000 lines."},
    {"name": "Bash",
     "signature": "Bash(command, cwd?) -> {ok, stdout, stderr, exit_code}",
     "desc": "Run a shell command scoped to the project. Allowlist: "
             "grep, rg, find, cat, head, tail, wc, jq, python3, ls, test, "
             "diff, git status/diff/log/show/ls-files. Timeout 15s."},
    {"name": "Edit",
     "signature": "Edit(path, old_string, new_string, replace_all?) -> {ok, matches_replaced}",
     "desc": "Exact-string replace in a file. old_string must be "
             "unique unless replace_all=True. Atomic write."},
    {"name": "Write",
     "signature": "Write(path, content) -> {ok, path, size}",
     "desc": "Create a new file. Refuses if the path already exists — "
             "use Edit to modify existing files."},
    {"name": "RegistryPatch",
     "signature": "RegistryPatch(kind, op, entry) -> {ok, files_touched, delta}",
     "desc": "Structured update to registry.json + plan.json + "
             "contracts/. kind: entity|page|workflow|dataSource|action. "
             "op: add|remove|update. Keeps every representation in sync."},
]


HANDLERS = {
    "Read":          lambda output_dir, args: read_tool(
        output_dir, args.get("path", ""),
        offset=int(args.get("offset", 0)),
        limit=args.get("limit"),
    ),
    "Bash":          lambda output_dir, args: bash_tool(
        output_dir, args.get("command", ""), cwd=args.get("cwd"),
    ),
    "Edit":          lambda output_dir, args: edit_tool(
        output_dir, args.get("path", ""),
        args.get("old_string", ""), args.get("new_string", ""),
        replace_all=bool(args.get("replace_all", False)),
    ),
    "Write":         lambda output_dir, args: write_tool(
        output_dir, args.get("path", ""), args.get("content", ""),
    ),
    "RegistryPatch": lambda output_dir, args: registry_patch_tool(
        output_dir, args.get("kind", ""), args.get("op", ""),
        args.get("entry") or {},
    ),
}
