"""Normalize LLM-authored schema expressions to the engine's feel-lite dialect.

The page agent frequently writes JavaScript-style conditionals that feel-lite can't
parse and that crash the renderer:
  * `"condition": "..."` instead of the schema's `when` prop.
  * `===` / `!==` (JS strict equality) instead of feel-lite `=` / `!=`
    -> "Unexpected token: Eq" ParseError, the node fails to render.

This rewrites them deterministically: rename `condition`->`when`, and convert the
JS operators inside expression-bearing props and `{{ }}` interpolations.
"""
from __future__ import annotations

# Props whose value is a feel-lite expression (not free text).
_EXPR_PROPS = (
    "when", "condition", "visibleWhen", "hiddenWhen",
    "disabledWhen", "showWhen", "enabledWhen",
)


def _feelify(v: str) -> str:
    return v.replace("===", "=").replace("!==", "!=")


def normalize_expressions(schema: dict) -> tuple[dict, dict]:
    report = {"fixed": 0}

    def walk(node):
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict):
                # `condition` -> `when` (the schema's recognized prop)
                if "condition" in props and "when" not in props:
                    props["when"] = props.pop("condition")
                    report["fixed"] += 1
                for k, val in list(props.items()):
                    if isinstance(val, str) and ("===" in val or "!==" in val):
                        # Only touch expression props or interpolations, never free text.
                        if k in _EXPR_PROPS or "{{" in val:
                            props[k] = _feelify(val)
                            report["fixed"] += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(schema.get("root") or schema)
    return schema, report
