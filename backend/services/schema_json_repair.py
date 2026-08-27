"""Repair malformed page-schema JSON before it reaches the Next.js build.

The refiner agent edits `src/schemas/**/*.json` with the `Edit` tool (string
splicing), which readily leaves a trailing comma — `},]` / `,}` — that is valid
in JS but NOT in JSON. Next imports these files as JSON, so a single stray comma
fails the whole build ("Cannot parse JSON: Unexpected token ']'"), crashing the
app after an otherwise-successful conversational edit.

This guard parses every schema file; for any that fail, it strips trailing commas
and re-validates. Fixed files are rewritten; still-broken files are logged loudly
(they need a human/agent, but at least the failure is visible, not a silent crash).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ", }" or ",\n]" etc. — a comma immediately before a closing brace/bracket.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def repair_schema_json(output_dir: str) -> dict:
    """Validate + repair every src/schemas/**/*.json. Returns a report dict:
    {"repaired": [rel_paths], "unfixable": [rel_paths]}. Never raises."""
    root = Path(output_dir)
    schemas = root / "src" / "schemas"
    repaired: list[str] = []
    unfixable: list[str] = []
    if not schemas.is_dir():
        return {"repaired": repaired, "unfixable": unfixable}

    for f in schemas.rglob("*.json"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            json.loads(text)
            continue  # already valid
        except json.JSONDecodeError:
            pass
        rel = str(f.relative_to(root))
        fixed = _TRAILING_COMMA.sub(r"\1", text)
        try:
            json.loads(fixed)
        except json.JSONDecodeError as e:
            unfixable.append(rel)
            logger.error("schema_json_repair: %s still invalid after comma-strip: %s", rel, e)
            continue
        try:
            f.write_text(fixed, encoding="utf-8")
            repaired.append(rel)
        except Exception as e:  # noqa: BLE001
            logger.warning("schema_json_repair: could not write %s: %s", rel, e)

    return {"repaired": repaired, "unfixable": unfixable}
