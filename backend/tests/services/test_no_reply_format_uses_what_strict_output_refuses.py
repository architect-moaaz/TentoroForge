"""A reply format sent as strict structured output may not carry the
constraints the API refuses — limits on numbers, string lengths, item
counts. `domain_score`'s 0–10 score and `schedule_change`'s minutes each
had one, and every call was a 400: the domain criterion could never be
scored, and Smith could not set a deadline (m1dck85j, 2026-10-12). Scans
the modules that hold reply formats for any dict that declares one."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "services"
REFUSED = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
           "minLength", "maxLength", "maxItems", "minProperties", "maxProperties"}
SCANNED = [*sorted((ROOT / "blueprint").glob("*.py")), *sorted((ROOT / "smith").glob("*.py")),
           *sorted((ROOT / "smith4").glob("*.py"))]
#: Files whose such keys are not reply formats (validators shown to a page writer).
NOT_REPLY_FORMATS = {"page_planner.py"}


def test_no_reply_format_declares_a_refused_constraint():
    found = []
    for path in SCANNED:
        if path.name in NOT_REPLY_FORMATS:
            continue
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                if "type" in keys and keys & REFUSED:
                    found.append(f"{path.relative_to(ROOT.parent)}:{node.lineno} {sorted(keys & REFUSED)}")
    assert found == [], "\n".join(found)
