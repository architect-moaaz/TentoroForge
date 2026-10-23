"""What a person can choose on a phone screen's parts, and the ready parts they can add.

The choices are read from the kit's own types (`static/kit-schema.mjs` asks the TypeScript compiler), so a pick list is exactly the
words the kit accepts and never a list kept by hand. A change that picks one of those words cannot break a type, which is what lets
it be saved without the compiler. The parts to add are a short, fixed list of snippets that need no data; each is checked against
the real compiler by the tests, and only exactly these are accepted as an addition.

When the phone's toolchain is not on this machine there is no schema: the pick lists are empty, and the screen says so."""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from services.react_editor.phone_palette import CONTAINERS, PALETTE, palette_entry_for  # noqa: F401 - re-exported

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "kit-schema.mjs"
_CACHE_DIR = Path(__file__).resolve().parents[2] / ".forge" / "kit-schema"
_MEMORY: dict[str, dict[str, Any]] = {}

#: A pick list longer than this (the icon names) is sent once, apart, not repeated in every part that has one.
_BIG = 60

#: Settings that carry the screen's own logic (a spinner while a workflow runs, a button that is off until a field is filled): a
#: person does not choose these, the screen's code does.
LOGIC_PROPS = frozenset({"loading", "disabled", "refreshing", "required"})


def _kit_dir(root: Path) -> Path:
    from services.blueprint.native_projection import TEMPLATE_DIR, native_root
    own = native_root(root) / "src" / "ui"
    return own if (own / "index.ts").is_file() else Path(TEMPLATE_DIR) / "src" / "ui"


def _fingerprint(kit: Path) -> str:
    h = hashlib.sha1(SCRIPT.read_bytes())
    for f in sorted(kit.rglob("*.ts*")):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def _toolchain() -> Path | None:
    from services.blueprint import native_engineer
    tool = native_engineer.toolchain_dir()
    return tool if (tool / "node_modules" / "typescript" / "lib" / "typescript.js").is_file() else None


def _read(kit: Path, tool: Path, project: Path) -> dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        return {"ok": False, "error": "Node.js is not installed on this machine."}
    proc = subprocess.run([node, str(SCRIPT), str(kit), str(tool), str(project)], capture_output=True, text=True,
                          encoding="utf-8", timeout=180)
    out = (proc.stdout or "").strip()
    try:
        return json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": (proc.stderr or "").strip()[:300]}
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "error": (proc.stderr or out or "no answer").strip()[:300]}


def full(root: Path) -> dict[str, Any]:
    """`{"ok": True, "components": {Name: {"props": {prop: {kind, values?}}}}}`, or `{"ok": False, "error": ...}`."""
    kit = _kit_dir(root)
    key = _fingerprint(kit)
    if key in _MEMORY:
        return _MEMORY[key]
    cached = _CACHE_DIR / f"{key}.json"
    if cached.is_file():
        try:
            _MEMORY[key] = json.loads(cached.read_text(encoding="utf-8"))
            return _MEMORY[key]
        except (OSError, json.JSONDecodeError):
            pass
    tool = _toolchain()
    if tool is None:
        return {"ok": False, "error": "The phone's checker is not installed on this machine, so the choices a part has cannot be read."}
    result = _read(kit, tool, root / "native")
    if result.get("ok"):
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(result), encoding="utf-8")
        _MEMORY[key] = result
    else:
        logger.warning("[react_editor.phone_kit] the kit's choices were not read: %s", result.get("error"))
    return result


def for_browser(root: Path) -> dict[str, Any]:
    """What the panel needs: the choices of each part, long lists apart, and the parts that can be added."""
    schema = full(root)
    if not schema.get("ok"):
        return {"ok": False, "error": schema.get("error"), "components": {}, "lists": {}, "palette": PALETTE,
                "containers": sorted(CONTAINERS)}
    lists: dict[str, list[str]] = {}
    components: dict[str, Any] = {}
    for name, comp in schema["components"].items():
        props: dict[str, Any] = {}
        for prop, spec in comp["props"].items():
            if spec["kind"] not in ("enum", "boolean") or prop in LOGIC_PROPS:
                continue
            spec = dict(spec)
            values = spec.get("values") or []
            if len(values) > _BIG:
                list_id = hashlib.sha1("|".join(values).encode()).hexdigest()[:8]
                lists[list_id] = values
                spec["values"], spec["list"] = [], list_id
            props[prop] = spec
        if props:
            components[name] = {"props": props}
    return {"ok": True, "components": components, "lists": lists, "palette": PALETTE, "containers": sorted(CONTAINERS)}


def allows(root: Path, component: str, prop: str, value: Any) -> bool:
    """Is this value one the kit accepts for this setting? `value` is the op's: {"kind": "string", "value": ...}, {"kind": "true"},
    or None, which takes the setting away (so the part falls back to its own default) and is only for a setting that is optional."""
    spec = ((full(root).get("components") or {}).get(component) or {}).get("props", {}).get(prop)
    if not spec or prop in LOGIC_PROPS:
        return False
    if value is None:
        return bool(spec.get("optional"))
    if spec["kind"] == "boolean":
        return (value or {}).get("kind") == "true"
    if spec["kind"] == "enum" and (value or {}).get("kind") == "string":
        return (value or {}).get("value") in (spec.get("values") or [])
    return False
