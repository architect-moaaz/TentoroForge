"""wizard_page_pass — Spec E Wave 3 (advanced UX patterns).

When the planner declares ``page.wizard`` on a page, this deterministic
post-gen pass collapses the workflow's trigger inputs into a single
``Wizard`` library component in the emitted page schema.

Flag-gated on ``FORGE_E_PATTERNS`` — no-op unless the operator opts
in. Additive + idempotent: safe to re-run.

Design notes
------------
* We read the planner's declaration off the page schema itself:
  ``page.wizard.steps[*].{id,title,fields[],nextIf?}``. This mirrors
  the sanitiser in ``agents.planner._sanitize_page_wave3_ux``.
* We do NOT re-derive the workflow bindings — the planner is the
  source of truth here. The pass swaps the page's existing form-shape
  root for a single ``Wizard`` node with the step defs inlined.
* Field control kinds default to ``text``. When the schema already
  ships a matching form field with a richer ``kind`` (select /
  textarea / date / …) we copy that hint over so the Wizard doesn't
  regress to plain inputs.
* Never touches a page that already contains a Wizard node — that's
  the idempotency contract.

See :mod:`services.reorder_column_pass` for the shape this follows.
"""
from __future__ import annotations

import glob
import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def is_enabled() -> bool:
    """FORGE_E_PATTERNS truthy — the spec's opt-in flag."""
    return os.getenv("FORGE_E_PATTERNS", "0").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _iter_nodes(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_nodes(v)


def _has_wizard(schema: dict) -> bool:
    for n in _iter_nodes(schema):
        if isinstance(n, dict) and n.get("type") == "Wizard":
            return True
    return False


def _existing_field_kinds(schema: dict) -> dict[str, str]:
    """Harvest {name: kind} from any Form/Input/Select/… fields the
    schema already emits, so the Wizard reuses matching control types.
    """
    kinds: dict[str, str] = {}
    for n in _iter_nodes(schema):
        if not isinstance(n, dict):
            continue
        # Form's declarative-mode fields[]
        if n.get("type") == "Form":
            props = n.get("props") or {}
            for f in (props.get("fields") or []):
                if isinstance(f, dict) and isinstance(f.get("name"), str):
                    k = f.get("kind")
                    if isinstance(k, str):
                        kinds.setdefault(f["name"], k)
        # Standalone input-shaped nodes
        tp = n.get("type")
        props = n.get("props") if isinstance(n.get("props"), dict) else {}
        name = props.get("name") if isinstance(props.get("name"), str) else None
        if not name:
            continue
        if tp == "Select":
            kinds.setdefault(name, "select")
        elif tp == "Textarea":
            kinds.setdefault(name, "textarea")
        elif tp == "DatePicker":
            kinds.setdefault(name, "date")
        elif tp == "NumberInput":
            kinds.setdefault(name, "number")
        elif tp == "Checkbox":
            kinds.setdefault(name, "checkbox")
    return kinds


def _humanize(name: str) -> str:
    s = name.replace("_", " ").replace("-", " ")
    out = []
    for i, ch in enumerate(s):
        if ch.isupper() and i and s[i - 1].islower():
            out.append(" ")
        out.append(ch)
    label = "".join(out).strip()
    return label[:1].upper() + label[1:] if label else name


# Field kinds the Wizard schema accepts (WizardField.kind). Anything else
# degrades to "text" rather than failing validation and dropping the page.
_WIZARD_KINDS = {"text", "email", "number", "textarea",
                 "select", "checkbox", "date", "radio"}


def derive_steps_from_fields(fields, per_step: int = 3) -> list[dict]:
    """Split a flat field list into Wizard steps.

    The planner authors ``archetype: "wizard"`` but not ``wizard.steps``,
    so a page can be *declared* a wizard with no step structure. Rather
    than drop the declaration, chunk the fields it already carries.

    Returns ``[]`` when there is nothing to step through — fewer than two
    fields makes a worse wizard than a form, and an empty Wizard would be
    a regression, not a feature. The caller then leaves the form alone.
    """
    items = [f for f in (fields or []) if isinstance(f, dict) and f.get("name")]
    if len(items) < 2:
        return []
    steps: list[dict] = []
    for i in range(0, len(items), max(1, per_step)):
        chunk = items[i:i + max(1, per_step)]
        n = len(steps) + 1
        steps.append({
            "id": f"step-{n}",
            "title": f"Step {n}",
            "fields": [
                {
                    "name":  str(f.get("name")),
                    "label": str(f.get("label") or _humanize(str(f.get("name")))),
                    "kind":  (f.get("kind") if f.get("kind") in _WIZARD_KINDS else "text"),
                    **({"required": True} if f.get("required") else {}),
                }
                for f in chunk
            ],
        })
    return steps


def _build_wizard_node(
    wizard_decl: dict,
    field_kinds: dict[str, str],
    submit_workflow: str | None,
) -> dict:
    steps_out = []
    for s in wizard_decl.get("steps", []):
        fields_out = []
        for fname in s.get("fields", []):
            kind = field_kinds.get(fname, "text")
            # Wizard field kinds are a strict subset — coerce unknown
            # values to text so the schema round-trips cleanly.
            if kind not in ("text", "email", "number", "textarea", "select",
                            "checkbox", "date", "radio"):
                kind = "text"
            fields_out.append({
                "name": fname,
                "label": _humanize(fname),
                "kind": kind,
            })
        step_entry = {
            "id": s.get("id") or "step",
            "title": s.get("title") or "Step",
            "fields": fields_out,
        }
        if isinstance(s.get("nextIf"), str) and s["nextIf"]:
            step_entry["nextIf"] = s["nextIf"]
        steps_out.append(step_entry)

    props: dict[str, Any] = {"steps": steps_out}
    if submit_workflow:
        props["onComplete"] = submit_workflow
    return {"type": "Wizard", "props": props}


def _wrap_root(root: Any, wizard_node: dict) -> Any:
    """Return a new root that hoists the Wizard to the top of children.

    We prefer to sit *inside* an existing container (Stack/Section) so
    layout tokens stay intact; when the root itself is a plain
    dict-shape we return the Wizard node directly.
    """
    if isinstance(root, dict) and isinstance(root.get("children"), list):
        # Drop any existing Form so we don't render duplicate inputs.
        pruned = [c for c in root["children"]
                  if not (isinstance(c, dict) and c.get("type") == "Form")]
        return {**root, "children": [wizard_node, *pruned]}
    return wizard_node


def _apply_to_schema_file(
    schema_path: Path,
    workflows: dict[str, str],
) -> bool:
    try:
        raw = schema_path.read_text(encoding="utf-8")
        schema = json.loads(raw)
    except Exception:
        return False
    if not isinstance(schema, dict):
        return False
    if _has_wizard(schema):
        return False  # idempotent

    wizard = schema.get("wizard")
    if not (isinstance(wizard, dict) and isinstance(wizard.get("steps"), list) and wizard["steps"]):
        return False

    # Pick a submit workflow: explicit page.workflow, else infer from
    # a form_submit action, else leave empty (Wizard just collects
    # values and dispatches nothing).
    submit_wf = None
    actions = schema.get("actions")
    if isinstance(actions, list):
        for a in actions:
            if isinstance(a, dict) and a.get("kind") == "form_submit":
                wf = a.get("workflow")
                if isinstance(wf, str) and wf.strip():
                    submit_wf = wf.strip()
                    break
    if not submit_wf and isinstance(schema.get("workflow"), str):
        submit_wf = schema["workflow"]
    if not submit_wf:
        # Fallback: unique workflow whose name matches the page entity
        entity = schema.get("entity")
        if isinstance(entity, str):
            for wf_name in workflows:
                if entity.lower() in wf_name.lower():
                    submit_wf = wf_name
                    break

    field_kinds = _existing_field_kinds(schema)
    wizard_node = _build_wizard_node(wizard, field_kinds, submit_wf)

    root = schema.get("root")
    if root is not None:
        schema["root"] = _wrap_root(root, wizard_node)
    else:
        # Top-level shape: {"components": [...]} or a bare tree.
        if isinstance(schema.get("components"), list):
            components = schema["components"]
            components.insert(0, wizard_node)
        else:
            schema.setdefault("nodes", []).insert(0, wizard_node) if isinstance(
                schema.get("nodes"), list
            ) else schema.__setitem__("root", wizard_node)

    schema.setdefault("_wave3", {})["wizard_applied"] = True
    try:
        schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def _load_workflow_names(root: Path) -> dict[str, str]:
    """Return a name→name map of known workflows (used for weak
    inference of the submit workflow when the page didn't declare one).
    """
    names: dict[str, str] = {}
    for fp in glob.glob(str(root / "src" / "workflows" / "**" / "*.json"), recursive=True):
        try:
            data = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        n = data.get("name") if isinstance(data, dict) else None
        if isinstance(n, str) and n.strip():
            names[n.strip()] = n.strip()
    return names


def run(output_dir: str) -> dict[str, Any]:
    """Apply Wizard collapse to every page schema declaring ``page.wizard``."""
    report: dict[str, Any] = {
        "enabled": is_enabled(),
        "pages_touched": [],
    }
    if not is_enabled():
        return report

    root = Path(output_dir)
    if not root.exists():
        return report
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return report

    workflows = _load_workflow_names(root)
    for fp in schemas_dir.glob("**/*.json"):
        if _apply_to_schema_file(fp, workflows):
            report["pages_touched"].append(str(fp.relative_to(root)))

    if report["pages_touched"]:
        logger.info(
            "wizard_page_pass: applied to %d page(s): %s",
            len(report["pages_touched"]), report["pages_touched"],
        )
    return report
