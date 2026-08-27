# backend/scripts/seed_reference_bank.py
"""Reference bank seeder — generate, render, score, and curate exemplar
schemas for (domain, page_type) cells. Runs against the live render-service
(port 6502) and Anthropic API.

Usage:
  python -m scripts.seed_reference_bank \\
      --domain healthcare --page-type list --target-count 2 \\
      --max-attempts 10 --seeder-version v1

Run this once per cell. Outputs land in backend/reference_pages/<domain>/<page_type>/.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic

from services.vision_evaluator import EvaluatorContext, evaluate_page


_REPO_ROOT = Path(__file__).resolve().parents[2]
_BANK_ROOT = _REPO_ROOT / "backend" / "reference_pages"
_RENDER_SERVICE = os.getenv("RENDER_SERVICE_URL", "http://localhost:6502")
_OUTPUT_ROOT = _REPO_ROOT / "output"
_SEEDER_MODEL = os.getenv("SEEDER_MODEL", "claude-sonnet-4-5-20250929")


# Per-domain entity bank — what entities the LLM should design pages around
# for each domain. Used to make the brief realistic.
_DOMAIN_ENTITIES: dict[str, list[str]] = {
    "general":     ["User", "Item", "Project", "Task", "Note"],
    "healthcare":  ["Patient", "Appointment", "Provider", "Visit", "Prescription"],
    "fintech":     ["Account", "Transaction", "Customer", "Portfolio", "Position"],
    "hr":          ["Employee", "TimeOff", "Role", "Performance", "Department"],
}


_PAGE_TYPE_BRIEFS: dict[str, str] = {
    "list":      "an index/list page for browsing many records, with sorting and filters",
    "detail":    "a record-detail page showing one item's full information",
    "form":      "a create/edit form for a single record with proper validation feedback",
    "dashboard": "an overview dashboard with KPI tiles, recent activity, and at-a-glance status",
    "settings":  "a settings or profile page with grouped configuration controls",
}


_REGISTER_DESCRIPTIONS: dict[str, str] = {
    "workday": "corporate enterprise — dense data tables, navy primary, structured grays, status pills heavy, density.compact, elevation.bordered, radius.sharp",
    "linear":  "monochrome neutral, single accent, mono numerics, density.compact, elevation.flat, radius.sharp (4px)",
    "stripe":  "two-tone with gradient hero, structured cards, density.comfortable, elevation.layered, radius.soft",
    "notion":  "soft grays, density.spacious, elevation.flat, radius.round (12px), generous line-height, content-first",
    "figma":   "vibrant, friendly numerics, density.comfortable, elevation.floating, radius.round, playful",
    "default": "neutral shadcn-default visual register",
}


def _build_seeder_prompt(register: str, domain: str, page_type: str) -> str:
    entities = _DOMAIN_ENTITIES.get(domain, _DOMAIN_ENTITIES["general"])
    brief = _PAGE_TYPE_BRIEFS.get(page_type, "a generic page")
    register_desc = _REGISTER_DESCRIPTIONS.get(register, "neutral visual register")
    return f"""You are designing a top-tier exemplar Page schema for the Tentoroforge platform reference bank.

VISUAL REGISTER: {register} — {register_desc}
DOMAIN: {domain}
PAGE TYPE: {page_type}
PAGE BRIEF: {brief}
LIKELY ENTITIES IN THIS DOMAIN: {", ".join(entities)}

CANONICAL SHAPE (use EXACTLY these key names — no abbreviations)
{{
  "schemaVersion": "2",
  "id": "ref/candidate",
  "route": "/{page_type}",
  "layout": "default",
  "meta": {{ "title": "<domain-specific title>" }},
  "dataSources": [
    {{ "name": "items", "entity": "<EntityName>", "op": "list" }}
  ],
  "root": {{
    "id": "root",
    "type": "Container",
    "props": {{ "maxWidth": "lg" }},
    "children": [
      {{ "id": "hero", "type": "Hero", "props": {{ "headline": "...", "layout": "centered" }} }},
      {{ "id": "stats", "type": "Grid", "props": {{ "columns": 4 }}, "children": [ ... ] }}
    ]
  }}
}}

KEY-NAME CONTRACT — FAILURE TO COMPLY MAKES THE OUTPUT UNUSABLE
- Top-level: `schemaVersion`, `id`, `route`, `layout`, `meta`, `dataSources`, `root` — full spelling.
- Each node: `id` (string), `type` (literal component name like "Hero"), `props` (object),
  `children` (array of nodes — only for container components like Stack/Row/Grid/Container/
  Section/Card/Hero/Repeat/Form/AccordionPanel/etc.).
- DO NOT use abbreviated keys like `v`, `c`, `t`, `p`, `ch`.
- Every node MUST have a unique `id` and a `type`.

ALLOWED COMPONENT TYPES (case-sensitive, use one of these for `type`):
  Layout:        Container, Stack, Row, Grid, Section, Split, Sidebar, Cluster
  Display:       Hero, Card, MetricTile, FeatureCard, Heading, Avatar, Badge,
                 KeyValueList, Skeleton, Divider, Breadcrumb, Alert, EmptyState
  Forms:         Form, Input, Select, Textarea, Checkbox, DatePicker
  Data:          Table, DataGrid, Chart, Sparkline, Timeline, Repeat
  Navigation:    Tabs, TabPanel, Accordion, AccordionPanel, NavLink
  Interactive:   Button, Link, IconButton
  Tier 2:        ApprovalStepper, PersonCard, FilterBar, CommandPalette,
                 ActivityFeed, EmptyStateRich, DateRangePicker, MultiSelect,
                 AppShell, InspectorPanel, TabPanelWithDeepLink
  Motion:        FadeIn, Stagger
  Primitive:     Box, Text, Image

CONTENT REQUIREMENTS
- The page must look like a senior product designer specialising in {domain} built it.
- Use real domain vocabulary (no Lorem ipsum, no "Item 1 / Item 2").
- Information density: matched to the page type — sparse for forms, denser for lists/dashboards.
- Component coherence: every component should feel like it's from the same design system.
- The visual register ({register}) must show through component choice and token usage.
- Bind dynamic content via Mustache: `{{{{user.name}}}}`, `{{{{item.status}}}}`, etc.
- meta.title should be domain-specific.

OUTPUT
Emit ONLY the JSON. No prose, no markdown fences, no commentary."""


async def _generate_candidate(register: str, domain: str, page_type: str) -> dict:
    client = AsyncAnthropic()
    prompt = _build_seeder_prompt(register, domain, page_type)
    msg = await client.messages.create(
        model=_SEEDER_MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    # Strip code fences if any
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0]
        if text.startswith("json\n"):
            text = text[5:]
    schema = json.loads(text)
    # Run the same prop-shape normaliser the main generation pipeline applies
    # in feature_slice_schema_agent — without this, LLM-emitted v1-style props
    # (Heading.size/.color/.text, Button.content, Link.href, etc.) cause every
    # component to render as `⚠ invalid props` in the scaffold, dragging the
    # vision-evaluator score below the 8.0 keep-threshold every time.
    from services.schema_normalizer import normalize_v2_schema
    return normalize_v2_schema(schema)


def _write_temp_project(schema: dict, register: str = "default") -> tuple[str, Path]:
    """Write the candidate schema into a temp project shell so the scaffold
    can render it. Returns (short_id, path).

    Defensively normalises the schema BEFORE writing so common LLM-emission
    drift (missing `schemaVersion`, missing `id`, abbreviated keys) doesn't
    produce a blank render.

    Also stamps the project with a minimal `design-spec.json` (carrying the
    target register), an empty `tokens.custom.json`, and a stub `app-model.json`
    so the scaffold's loaders find the artifacts they expect rather than
    falling through every path to defaults.
    """
    schema = _normalise_candidate_schema(schema)

    short_id = f"seed-{uuid.uuid4().hex[:8]}"
    proj_dir = _OUTPUT_ROOT / short_id
    schemas_dir = proj_dir / "src" / "schemas" / "ref"
    contracts_dir = proj_dir / "src" / "contracts"
    theme_dir = proj_dir / "src" / "theme"
    for d in (schemas_dir, contracts_dir, theme_dir):
        d.mkdir(parents=True, exist_ok=True)

    (schemas_dir / "candidate.json").write_text(json.dumps(schema))

    # Minimal design-spec — the only field the scaffold reads is `register`,
    # but we include a couple of extras so any future probe doesn't crash.
    (contracts_dir / "design-spec.json").write_text(json.dumps({
        "register": register,
        "domain": "general",
        "colorPalette": {"primary": "#1e40af"},
    }, indent=2))

    # Empty token-overrides — the renderer's `compileTokens` falls back to
    # defaults when no overrides are present, which is exactly what we want
    # for an exemplar (use the design system's stock register tokens).
    (theme_dir / "tokens.custom.json").write_text("{}")

    # Stub app-model so any registry-aware loader doesn't 404.
    (contracts_dir / "app-model.json").write_text(json.dumps({
        "entities": {},
        "domain": "general",
    }, indent=2))

    return short_id, proj_dir


# Common LLM-abbreviation → canonical key mappings. The seeder prompt instructs
# the model to use full names, but a defensive normaliser catches drift so a
# single bad attempt doesn't burn the whole cell budget.
_KEY_ALIASES = {
    "v": "schemaVersion",
    "t": "type",
    "c": "type",      # some models prefer `c` for component
    "p": "props",
    "ch": "children",
    "s": "style",
    "k": "id",
}


def _normalise_candidate_schema(schema: dict) -> dict:
    """Walk the schema tree and rewrite abbreviated keys to canonical names.
    Also defensively sets `schemaVersion: "2"` and a fallback `id` if missing
    on the root or on any node.

    Returns the same dict, mutated in place (acceptable for this script — we
    discard the input afterwards)."""
    # Top-level fixups
    if "v" in schema and "schemaVersion" not in schema:
        schema["schemaVersion"] = str(schema.pop("v"))
    schema.setdefault("schemaVersion", "2")
    schema.setdefault("id", "ref/candidate")
    schema.setdefault("route", "/ref/candidate")
    schema.setdefault("layout", "default")
    schema.setdefault("meta", {})
    schema.setdefault("dataSources", [])

    def walk(node):
        if not isinstance(node, dict):
            return node
        for short, full in _KEY_ALIASES.items():
            if short in node and full not in node:
                node[full] = node.pop(short)
        # Recurse into children + props
        if isinstance(node.get("children"), list):
            node["children"] = [walk(c) for c in node["children"]]
        return node

    if isinstance(schema.get("root"), dict):
        schema["root"] = walk(schema["root"])
        schema["root"].setdefault("id", "root")
    return schema


async def _render_and_score(short_id: str, domain: str, page_type: str) -> tuple[bytes, float, dict]:
    """Render the candidate via render-service, then score via vision evaluator.
    Returns (png_bytes, composite_score, full_critique_dict)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(f"{_RENDER_SERVICE}/render", json={
            "projectId": short_id, "pageRoute": "/ref/candidate", "viewport": "desktop",
        })
    if r.status_code != 200:
        raise RuntimeError(f"render failed: {r.status_code} {r.text}")
    body = r.json()
    png = base64.b64decode(body["pngBase64"])
    a11y = body.get("accessibilityTree", "")

    ctx = EvaluatorContext(
        domain=domain, app_name="Reference exemplar",
        description=f"Exemplar {page_type} page for {domain}",
        tone="professional", route="/ref/candidate",
        page_type=page_type, page_role=f"reference exemplar — {page_type}",
        iteration=0, max_iter=1,
    )
    critique = await evaluate_page(png_bytes=png, a11y_tree=a11y, ctx=ctx)
    return png, critique.compositeScore, critique.model_dump(by_alias=True)


def _persist_exemplar(*, register: str, domain: str, page_type: str, idx: int, schema: dict, score: float, critique: dict, png: bytes, seeder_version: str) -> None:
    cell = _BANK_ROOT / register / domain / page_type
    cell.mkdir(parents=True, exist_ok=True)
    stem = f"exemplar_{idx:02d}"
    (cell / f"{stem}.json").write_text(json.dumps(schema, indent=2))
    (cell / f"{stem}.meta.json").write_text(json.dumps({
        "score": score, "scored_at": datetime.now(timezone.utc).isoformat(),
        "model_used": _SEEDER_MODEL, "seeder_version": seeder_version,
        "critique_summary": {"strengths": critique.get("strengths", []),
                             "topIssues": critique.get("topIssues", [])},
    }, indent=2))
    (cell / f"{stem}.png").write_bytes(png)


async def seed_cell(*, register: str = "default", domain: str, page_type: str, target_count: int, max_attempts: int, seeder_version: str) -> int:
    print(f"\n=== seeding {register}/{domain}/{page_type} (target={target_count}, max_attempts={max_attempts}) ===")
    kept = 0
    attempts = 0
    while kept < target_count and attempts < max_attempts:
        attempts += 1
        print(f"  attempt {attempts}/{max_attempts}", end=" ... ", flush=True)
        try:
            schema = await _generate_candidate(register, domain, page_type)
        except Exception as e:
            print(f"GEN FAILED: {e}")
            continue

        short_id, proj_dir = _write_temp_project(schema, register=register)
        try:
            png, score, critique = await _render_and_score(short_id, domain, page_type)
        except Exception as e:
            print(f"RENDER/SCORE FAILED: {e}")
            shutil.rmtree(proj_dir, ignore_errors=True)
            continue

        has_high_severity = any(i.get("severity") == "high" for i in critique.get("topIssues", []))
        if score >= 8.0 and not has_high_severity:
            kept += 1
            _persist_exemplar(register=register, domain=domain, page_type=page_type, idx=kept,
                              schema=schema, score=score, critique=critique, png=png,
                              seeder_version=seeder_version)
            print(f"KEPT (score {score:.1f}, kept {kept}/{target_count})")
        else:
            print(f"REJECTED (score {score:.1f}, high_sev={has_high_severity})")
        shutil.rmtree(proj_dir, ignore_errors=True)

    print(f"  done — kept {kept}/{target_count} after {attempts} attempts")
    return kept


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", default="default",
                    choices=list(_REGISTER_DESCRIPTIONS.keys()))
    ap.add_argument("--domain", required=True, choices=list(_DOMAIN_ENTITIES.keys()))
    ap.add_argument("--page-type", required=True, choices=list(_PAGE_TYPE_BRIEFS.keys()))
    ap.add_argument("--target-count", type=int, default=2)
    ap.add_argument("--max-attempts", type=int, default=10)
    ap.add_argument("--seeder-version", default="v1")
    return ap.parse_args()


async def _main() -> int:
    args = _parse_args()
    kept = await seed_cell(
        register=args.register,
        domain=args.domain, page_type=args.page_type,
        target_count=args.target_count, max_attempts=args.max_attempts,
        seeder_version=args.seeder_version,
    )
    return 0 if kept >= args.target_count else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
