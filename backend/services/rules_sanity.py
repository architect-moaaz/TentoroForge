"""Rules sanity — deactivate self-clobbering computed rules.

The planner sometimes authors a computed rule whose ``field_name`` is the
SAME field its expression reads, with string-literal results::

    field_name: confidenceScore
    expression: if confidenceScore >= 0.85 then "high" else ... "low"

At runtime that writes "low" INTO the numeric score before validation
runs, so the companion range rule ("between 0 and 1") rejects every
insert — the atb0m97x upload class. The tier belongs in a separate
field; since no such column exists, the only safe deterministic repair
is to deactivate the rule and report it.

A computed self-target is fine when the expression stays type-stable
(e.g. ``price * quantity`` into ``total`` doesn't read total). We only
deactivate when the expression BOTH reads its own target and yields
string literals — the provably destructive shape.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STRING_LITERAL_RE = re.compile(r'"[^"]*"|\'[^\']*\'')


def _is_self_clobbering(rule: dict) -> bool:
    if rule.get("rule_type") != "computed" or rule.get("is_active") is False:
        return False
    field = rule.get("field_name")
    expr = (rule.get("config") or {}).get("expression")
    if not isinstance(field, str) or not isinstance(expr, str):
        return False
    reads_self = re.search(rf"\b{re.escape(field)}\b", expr) is not None
    yields_string = _STRING_LITERAL_RE.search(expr) is not None
    return reads_self and yields_string


def sanitize_rules(output_dir: str | Path) -> dict:
    """Deactivate self-clobbering computed rules.

    The runtime's loadRules reads the app-root ``rules/`` dir FIRST and
    ``src/rules/`` only as a fallback (Vercel tracing) — both copies must
    be sanitized or the runtime keeps executing the broken rule from
    whichever copy it loads.
    """
    root = Path(output_dir)
    report: dict[str, Any] = {"deactivated": [], "summary": {"deactivated": 0}}
    for path in (root / "rules" / "index.json",
                 root / "src" / "rules" / "index.json"):
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        rules = doc if isinstance(doc, list) else doc.get("rules")
        if not isinstance(rules, list):
            continue

        dirty = False
        for rule in rules:
            if isinstance(rule, dict) and _is_self_clobbering(rule):
                rule["is_active"] = False
                rule["_deactivated_reason"] = (
                    "computed rule reads and overwrites its own field with "
                    "string literals — would corrupt the column and fail "
                    "companion validation on every write")
                if rule.get("name") not in report["deactivated"]:
                    report["deactivated"].append(rule.get("name"))
                dirty = True

        if dirty:
            path.write_text(json.dumps(doc, indent=2) + "\n",
                            encoding="utf-8")
    report["summary"]["deactivated"] = len(report["deactivated"])
    return report
