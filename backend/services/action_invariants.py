"""ACTION-invariant guard — declared page.actions must land in the schema.

Slice B post-gen backstop. The deterministic detail-page builder
consumes ``page.actions`` (Slice B step 2) — but LLM-authored detail
pages don't necessarily. This pass sweeps the emitted schemas and
inserts any planner-declared action button that's missing.

The invariant: for every page in ``contracts/plan.json`` that declares
``actions[]``, the corresponding schema JSON must contain a Button node
whose props reflect that action (workflow or navigate target). If not,
we synthesize one via
:func:`services.action_authority.derive_button_props` and append it to
the page's header actions row (falling back to the tree root when no
header row exists).

General fix — works for any action target the planner declared. No
per-domain hardcodes. Idempotent — a re-run on a fixed page is a no-op.
"""
from __future__ import annotations

import glob
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Types                                                                        #
# --------------------------------------------------------------------------- #

@dataclass
class ActionInsertRecord:
    """One button we inserted."""
    file: str
    page: str
    label: str
    kind: str
    target: str


@dataclass
class ActionInvariantResult:
    inserted: list[ActionInsertRecord] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def files_changed(self) -> int:
        return len({r.file for r in self.inserted})


# --------------------------------------------------------------------------- #
# Plan reading                                                                 #
# --------------------------------------------------------------------------- #

def _load_plan(output_dir: str) -> Optional[dict]:
    for parts in (
        ("src", "contracts", "plan.json"),
        ("contracts", "plan.json"),
    ):
        p = os.path.join(output_dir, *parts)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as fh:
                    return json.load(fh)
            except (OSError, json.JSONDecodeError):
                return None
    return None


def _iter_pages_with_actions(plan: dict) -> Iterable[dict]:
    """Yield every plan page dict that declares a non-empty ``actions``
    list."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return
    for p in pages:
        if not isinstance(p, dict):
            continue
        actions = p.get("actions")
        if isinstance(actions, list) and actions:
            yield p


# --------------------------------------------------------------------------- #
# Schema reading                                                               #
# --------------------------------------------------------------------------- #

def _iter_schemas(output_dir: str) -> Iterable[tuple[str, dict]]:
    root = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(root):
        return
    for f in sorted(glob.glob(os.path.join(root, "**", "*.json"),
                              recursive=True)):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            yield f, data


def _root_of(schema: dict) -> Any:
    """Return the schema's component tree root. Detail/edit schemas
    typically nest their tree under ``root``; older shapes carry
    ``children`` at the top."""
    if isinstance(schema.get("root"), dict):
        return schema["root"]
    return schema


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)
    elif isinstance(node, list):
        for x in node:
            yield from _walk(x)


# --------------------------------------------------------------------------- #
# Invariant check                                                              #
# --------------------------------------------------------------------------- #

def _button_matches_action(props: dict, action: dict) -> bool:
    """A button carries out the action if its target matches."""
    kind = action.get("kind")
    target = action.get("target")
    if not isinstance(props, dict) or not target:
        return False
    if kind == "workflow":
        return props.get("workflow") == target
    if kind == "navigate":
        for key in ("navigate", "href", "route", "to"):
            if props.get(key) == target:
                return True
        on_click = props.get("onClick")
        if isinstance(on_click, dict):
            for key in ("navigate", "href", "route", "to"):
                if on_click.get(key) == target:
                    return True
    return False


def _schema_has_action(schema: dict, action: dict) -> bool:
    for node in _walk(_root_of(schema)):
        if not isinstance(node, dict):
            continue
        if node.get("type") != "Button":
            continue
        if _button_matches_action(node.get("props") or {}, action):
            return True
    return False


def _find_header_actions_row(root_node: Any) -> Optional[dict]:
    """The deterministic detail-page builder writes header actions as a
    nested Row (siblings: Heading + Row-of-buttons). Return the buttons
    Row so a new declared button lands next to Back/Edit."""
    if not isinstance(root_node, dict):
        return None
    for node in root_node.get("children") or []:
        if not isinstance(node, dict):
            continue
        if node.get("type") not in ("Row", "Toolbar", "Stack"):
            continue
        inner = node.get("children") or []
        if not (len(inner) >= 2 and isinstance(inner[0], dict)
                and inner[0].get("type") == "Heading"):
            continue
        # Look for a Row whose children are all Buttons — the actions row.
        for c in inner:
            if (
                isinstance(c, dict)
                and c.get("type") == "Row"
                and all(
                    isinstance(x, dict) and x.get("type") == "Button"
                    for x in (c.get("children") or [])
                )
            ):
                return c
    return None


def _insert_action_button(schema: dict, action: dict, page_name: str) -> tuple[str, dict]:
    """Insert a Button for the declared action into the schema. Returns
    ``(label, button)`` so the caller can log."""
    from services.action_authority import derive_button_props
    props = derive_button_props(action)
    button = {"type": "Button", "props": props}
    root = _root_of(schema)
    row = _find_header_actions_row(root)
    if row is not None:
        row.setdefault("children", []).append(button)
        return props.get("label") or "(unlabeled)", button

    # No header row — synthesize one at the top of the root's children.
    if isinstance(root, dict):
        children = root.setdefault("children", [])
        if isinstance(children, list):
            new_row = {
                "type": "Row",
                "props": {"justify": "between", "align": "center"},
                "children": [
                    {"type": "Heading", "props": {
                        "content": page_name or props.get("label") or "",
                        "level": 1,
                    }},
                    {"type": "Row", "props": {"gap": "tokens.spacing.2"},
                     "children": [button]},
                ],
            }
            children.insert(0, new_row)
            return props.get("label") or "(unlabeled)", button
    raise ValueError("schema has no writable children list")


# --------------------------------------------------------------------------- #
# Route matching                                                               #
# --------------------------------------------------------------------------- #

def _same_route(a: str, b: str) -> bool:
    """Compare routes ignoring bracket-vs-colon syntax + trailing slash.
    ``/applicants/[id]`` matches ``/applicants/:id`` and
    ``/applicants/[id]/`` alike."""
    import re

    def _norm(s: str) -> str:
        s = (s or "").strip().rstrip("/")
        s = re.sub(r"\[([^\]]+)\]", r":\1", s)
        return s.lower()

    return _norm(a) == _norm(b)


# --------------------------------------------------------------------------- #
# Public entry                                                                 #
# --------------------------------------------------------------------------- #

def ensure_declared_actions_present(
    output_dir: str,
) -> ActionInvariantResult:
    """Sweep every schema and enforce the declared-actions invariant.
    Idempotent + never raises.
    """
    result = ActionInvariantResult()
    plan = _load_plan(output_dir)
    if not plan:
        return result

    # Index schemas by route so we can look up the file for each plan
    # page in O(pages+schemas).
    schemas_by_route: dict[str, list[tuple[str, dict]]] = {}
    for path, schema in _iter_schemas(output_dir):
        route = str(schema.get("route") or "")
        schemas_by_route.setdefault(route, []).append((path, schema))

    for page in _iter_pages_with_actions(plan):
        page_name = str(page.get("name") or "")
        page_route = str(page.get("route") or "")
        raw_actions = page.get("actions") or []

        # Locate the schema file(s) for this page's route. Match either
        # by exact string or normalized bracket-vs-colon.
        matched: list[tuple[str, dict]] = []
        for r, files in schemas_by_route.items():
            if _same_route(r, page_route):
                matched.extend(files)
        if not matched:
            result.skipped.append({
                "page":   page_name,
                "route":  page_route,
                "reason": "no schema matches route",
            })
            continue

        try:
            from services.action_authority import _normalize_actions
        except Exception:  # noqa: BLE001
            return result
        normalized = _normalize_actions(raw_actions)
        if not normalized:
            continue

        for path, schema in matched:
            changed = False
            for action in normalized:
                if _schema_has_action(schema, action):
                    continue
                try:
                    label, _btn = _insert_action_button(
                        schema, action, page_name,
                    )
                except (ValueError, TypeError) as exc:
                    result.skipped.append({
                        "page":   page_name, "file": path,
                        "label":  action.get("label"),
                        "reason": f"insert failed: {exc}",
                    })
                    continue
                result.inserted.append(ActionInsertRecord(
                    file=path, page=page_name, label=label,
                    kind=action.get("kind") or "",
                    target=action.get("target") or "",
                ))
                changed = True
            if changed:
                try:
                    with open(path, "w", encoding="utf-8") as fh:
                        json.dump(schema, fh, indent=2)
                        fh.write("\n")
                except OSError as exc:
                    result.skipped.append({
                        "page":   page_name, "file": path,
                        "reason": f"write failed: {exc.__class__.__name__}",
                    })
                    continue
            else:
                result.already_present.append(path)

    if result.inserted:
        logger.info(
            "action_invariants: inserted %d declared action button(s) across %d file(s) in %s",
            len(result.inserted), result.files_changed, output_dir,
        )
    if result.skipped:
        logger.warning(
            "action_invariants: skipped %d entry(s) in %s (first: %r)",
            len(result.skipped), output_dir, result.skipped[0],
        )
    return result
