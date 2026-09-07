"""Visual QA critic (G1) — an LLM design review over the page-sweep
screenshots.

The sweep (journey_verifier.sweep) captures a full-page screenshot of
every registered route as rendered against real seed data. This critic
sends those screenshots to a vision model with the app's design brief
identity and asks the one question no deterministic guard can answer:
*does this page look finished?* — empty-feeling regions, raw labels
that slipped every guard, overflow/clipping, contrast failures,
off-brief styling.

Findings are structured and validated (same discipline as
plan_coverage_critic: unknown kinds rejected, fields truncated) and
written to ``contracts/visual-qa.json`` so Smith and the verify report
can surface them. This is a *reporting* pass — repairs stay with the
deterministic seams the findings point at.

Gate: ``FORGE_VISUAL_QA`` via flag_profile (binary — FORGE_QUALITY=full
turns it on). Model: ``FORGE_VISUAL_QA_MODEL`` (Haiku default — cheap,
vision-capable). Screenshots capped at ``_MAX_PAGES`` to bound cost.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_PAGES = 6
_VALID_KINDS = {
    "empty_area", "raw_label", "overflow", "contrast",
    "misalignment", "off_brief", "broken_render",
}
_VALID_SEVERITIES = {"error", "warn", "info"}


def is_visual_qa_enabled() -> bool:
    try:
        from services.flag_profile import is_on
        return is_on("FORGE_VISUAL_QA", default=False)
    except Exception:  # noqa: BLE001
        v = (os.environ.get("FORGE_VISUAL_QA") or "").strip().lower()
        return v in ("1", "true", "yes", "on")


# ── input assembly ──────────────────────────────────────────────────

def _brief_identity(root: Path) -> dict:
    """The slice of the design brief the critic judges against."""
    try:
        brief = json.loads((root / "contracts" / "brief.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for key in ("identity", "signature_moves"):
        if isinstance(brief, dict) and brief.get(key) is not None:
            out[key] = brief[key]
    return out


def _sweep_pages(root: Path) -> list[dict]:
    """[{route, screenshot_path}] from sweep results, capped, landing
    first (it carries the most first-impression weight)."""
    try:
        data = json.loads(
            (root / "journeys" / "sweep-results.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    pages = []
    for r in data.get("results") or []:
        if not isinstance(r, dict) or r.get("status") != "ok":
            continue
        shot = r.get("screenshot")
        if shot and Path(shot).is_file():
            pages.append({"route": str(r.get("route")), "screenshot": shot})
    pages.sort(key=lambda p: (p["route"] != "/", p["route"]))
    return pages[:_MAX_PAGES]


def _validate_finding(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    route = str(raw.get("route") or "").strip()
    note = str(raw.get("note") or "").strip()
    severity = str(raw.get("severity") or "warn").strip()
    if kind not in _VALID_KINDS or not route or not note:
        return None
    if severity not in _VALID_SEVERITIES:
        severity = "warn"
    return {"kind": kind, "route": route[:120], "severity": severity,
            "note": note[:400]}


_PROMPT = """\
You are a design QA reviewer for a generated business web app.
Design brief identity (judge against this, not personal taste):
{identity}

For each screenshot (labeled by route), report ONLY concrete visible
defects — things a user would notice as unfinished or broken:
- empty_area: a large region that renders blank or a container with no content
- raw_label: machine text shown to the user (snake_case, camelCase, ids, "{{{{...}}}}")
- overflow: clipped/overlapping/overflowing content
- contrast: text that fails readability against its background
- misalignment: obviously broken layout (not taste — broken)
- off_brief: styling that contradicts the brief identity above
- broken_render: error text, stack traces, missing images

Return STRICT JSON: {{"findings": [{{"route": "...", "kind": "...",
"severity": "error|warn|info", "note": "..."}}]}}. An empty findings
list is a valid and common answer — do NOT invent issues.
"""


async def critique_screenshots(output_dir: str | Path) -> dict:
    """Run the critic. Returns the report dict (also written to
    contracts/visual-qa.json). Never raises."""
    root = Path(output_dir)
    pages = _sweep_pages(root)
    report: dict = {"pages_reviewed": [p["route"] for p in pages],
                    "findings": []}
    if not pages:
        return report

    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            # Still fall through to the report write below — an empty
            # report with `skipped` beats a silently absent file.
            raise RuntimeError("no ANTHROPIC_API_KEY")
        client = llm_client.AsyncAnthropic(api_key=api_key)

        content: list[dict] = []
        for p in pages:
            data = base64.standard_b64encode(
                Path(p["screenshot"]).read_bytes()).decode()
            content.append({"type": "text", "text": f"Route: {p['route']}"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/png", "data": data}})

        identity = json.dumps(_brief_identity(root), ensure_ascii=False)[:2000]
        resp = await client.messages.create(
            model=os.getenv("FORGE_VISUAL_QA_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=2048,
            system=_PROMPT.format(identity=identity or "{}"),
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", text, re.DOTALL)
        raw = json.loads(m.group(0)) if m else {}
        findings = [f for f in map(_validate_finding, raw.get("findings") or [])
                    if f is not None]
        report["findings"] = findings
    except Exception as exc:  # noqa: BLE001
        logger.warning("[visual-qa] critic failed: %s", exc)
        report["error"] = str(exc)[:300]

    try:
        out = root / "contracts" / "visual-qa.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[visual-qa] could not write report: %s", exc)
    if report["findings"]:
        logger.warning("[visual-qa] %d visual defect(s) — see visual-qa.json",
                       len(report["findings"]))
    return report


__all__ = ["critique_screenshots", "is_visual_qa_enabled"]
