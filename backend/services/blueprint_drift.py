"""Blueprint drift detector.

Someone edits a schema file by hand, a contract, a workflow — any
mutation that bypasses the four wire-in seams (post_generate_fixes,
schema_edit router, atomic_apply, smith_edit_tools) leaves the
on-disk ``BLUEPRINT.md`` stale. Drift catches that: we rebuild the
blueprint in-memory (without writing) and diff against what's on
disk. Anything different is drift.

Not the same as coverage:

* Coverage answers "does the blueprint mention every artifact?"
* Drift answers  "would rebuilding produce a different blueprint?"

Both are needed. An app can have 100% coverage AND drift (Smith
tweaked a page, blueprint wasn't rebuilt) — the coverage list will
still name everything because the OLD blueprint mentions the old
version of the page. Drift is what catches the change.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# The always-changing header timestamp + the "Written by" annotation
# aren't meaningful signals of drift — they change on every build. We
# also normalize the "Log: N entries" counter, which grows on every
# writer call independent of actual content.
_HEADER_LINE_RE = re.compile(r"^_Last built:.*_$", re.MULTILINE)
_SECTION_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def check_drift(output_dir: str | Path) -> dict:
    """Diff the on-disk ``BLUEPRINT.md`` against a fresh in-memory rebuild.

    Returns::

        {
          "stale":                   bool,     # True if content differs
          "on_disk_ts":              str|None, # timestamp parsed from header
          "on_disk_source":          str|None, # "Written by:" annotation
          "freshly_built_matches":   bool,     # !stale (kept for clarity)
          "diff_summary":            str,      # short human-readable summary
          "changed_sections":        [str],    # section titles that differ
          "on_disk_bytes":           int,
          "fresh_bytes":             int,
          "missing":                 bool,     # blueprint doesn't exist
        }
    """
    root = Path(output_dir)
    result: dict[str, Any] = {
        "stale": False,
        "on_disk_ts": None,
        "on_disk_source": None,
        "freshly_built_matches": True,
        "diff_summary": "",
        "changed_sections": [],
        "on_disk_bytes": 0,
        "fresh_bytes": 0,
        "missing": False,
    }
    if not root.is_dir():
        result["missing"] = True
        result["stale"] = True
        result["freshly_built_matches"] = False
        result["diff_summary"] = f"output_dir does not exist: {root}"
        return result

    on_disk_path = root / "BLUEPRINT.md"
    if not on_disk_path.is_file():
        result["missing"] = True
        result["stale"] = True
        result["freshly_built_matches"] = False
        result["diff_summary"] = "no BLUEPRINT.md on disk — rebuild needed"
        return result

    try:
        on_disk = on_disk_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("blueprint_drift: cannot read %s: %r", on_disk_path, exc)
        result["missing"] = True
        result["stale"] = True
        result["freshly_built_matches"] = False
        result["diff_summary"] = f"unreadable BLUEPRINT.md: {exc}"
        return result

    # Rebuild — do NOT pass mutation_source so the diff isn't skewed by
    # a different annotation label.
    try:
        from services.blueprint_builder import build_blueprint  # noqa: PLC0415
        fresh = build_blueprint(root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("blueprint_drift: build failed: %r", exc)
        result["stale"] = True
        result["freshly_built_matches"] = False
        result["diff_summary"] = f"rebuild failed: {exc}"
        return result

    result["on_disk_bytes"] = len(on_disk.encode("utf-8"))
    result["fresh_bytes"] = len(fresh.encode("utf-8"))

    # Extract the header metadata from what's on disk so callers can see
    # when it was last written + by whom.
    header_ts, header_src = _parse_header(on_disk)
    result["on_disk_ts"] = header_ts
    result["on_disk_source"] = header_src

    on_norm = _canonical(on_disk)
    fresh_norm = _canonical(fresh)
    stale = on_norm != fresh_norm
    result["stale"] = stale
    result["freshly_built_matches"] = not stale

    if not stale:
        result["diff_summary"] = "blueprint is up-to-date"
        return result

    changed = _changed_sections(on_norm, fresh_norm)
    result["changed_sections"] = changed
    delta = result["fresh_bytes"] - result["on_disk_bytes"]
    sign = "+" if delta >= 0 else ""
    result["diff_summary"] = (
        f"blueprint is stale — {len(changed)} section(s) would change; "
        f"body size delta {sign}{delta} bytes"
    )
    return result


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _canonical(text: str) -> str:
    """Strip the always-changing header line so drift compares BODIES,
    not timestamps."""
    return _HEADER_LINE_RE.sub("", text or "").strip()


def _parse_header(text: str) -> tuple[str | None, str | None]:
    """Extract the ``_Last built: TS · … · Written by: SRC · …_`` fields.

    Returns (timestamp, source) — either may be None if the line is
    malformed (older blueprint format, hand-edited header, etc.)."""
    m = _HEADER_LINE_RE.search(text or "")
    if not m:
        return None, None
    line = m.group(0)
    ts_m = re.search(r"Last built:\s*([^·_]+?)\s*(?:·|_)", line)
    src_m = re.search(r"Written by:\s*([^·_]+?)\s*(?:·|_)", line)
    ts = ts_m.group(1).strip() if ts_m else None
    src = src_m.group(1).strip() if src_m else None
    return ts, src


def _changed_sections(on_disk: str, fresh: str) -> list[str]:
    """Return the section titles (``##`` / ``###``) whose body differs
    between the two texts. Preserves declaration order."""
    on_map = _sections_by_title(on_disk)
    fresh_map = _sections_by_title(fresh)
    titles: list[str] = []
    seen: set[str] = set()
    for title in list(fresh_map.keys()) + list(on_map.keys()):
        if title in seen:
            continue
        seen.add(title)
        if on_map.get(title) != fresh_map.get(title):
            titles.append(title)
    return titles


def _sections_by_title(text: str) -> dict[str, str]:
    """Split a Markdown doc into {section title → body}. A section runs
    from one ``##`` / ``###`` heading up to the next heading of the same
    or higher level. Unheaded content lives under the empty title
    ``""``."""
    sections: dict[str, str] = {}
    current_title = ""
    current_body: list[str] = []
    for line in (text or "").splitlines():
        m = _SECTION_HEADER_RE.match(line)
        if m and len(m.group(1)) <= 3:
            # Flush the previous section.
            sections[current_title] = "\n".join(current_body).strip()
            current_title = m.group(2).strip()
            current_body = []
            continue
        current_body.append(line)
    sections[current_title] = "\n".join(current_body).strip()
    return sections


# --------------------------------------------------------------------------- #
# Convenience — used by self_verify_pass
# --------------------------------------------------------------------------- #

def format_drift_warning(drift: dict) -> str:
    """Compact single-line warning suitable for an SSE event or log."""
    if not drift.get("stale"):
        return ""
    parts: list[str] = ["blueprint drift detected"]
    ts = drift.get("on_disk_ts")
    if ts:
        parts.append(f"on-disk built at {ts}")
    changed = drift.get("changed_sections") or []
    if changed:
        parts.append(f"changed sections: {', '.join(changed[:5])}")
    return " — ".join(parts)
