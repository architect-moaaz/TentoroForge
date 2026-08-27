"""LangGraph StateGraph spine for the generation pipeline (LG-2 + O1).

Runs the SAME phase functions as the legacy ``_run_relay_pipeline`` relay in
``routers/generate.py``, but as a checkpointed graph:

    bootstrap → maquettes → discovery → foundation → design → contracts
    → schema → workflows → rules → runtime → pages → finish

O1 (single-spine) parity: this covers the relay's DEFAULT path end to end —
plan normalization + archetype stamp + directive parsing + requirement.json,
maquette authoring, domain discovery + design-brief authoring, template
floor + registries, the full design-authority chain (DNA → brief-canonical /
design agent → brand auto-detect → merge precedence → register → token
compile), deterministic-first contracts and schema with LLM fallback and
completeness gates, conditional BusinessLogic, the rules agent, runtime
injection + integrations sync + route prune + CRUD workflows + binding
contract, product brief + nav-flow + shell + per-page schema pipeline +
auth pages + CTA/PD/coverage gates, and the schema-path tail (photo
injection, nav-flow emit, standalone app emitter, npm install, fidelity
scoring, post-generate guard suite, session-context persistence).

Known deltas vs the relay (cosmetic/telemetry only, documented for parity
audits): office-animation events, the progress-ring recalibration events,
chat_flavor interstitials and generation-timing.json are not emitted here.
The legacy LLM/IR frontend paths (SCHEMA_MODE off) and Figma builds are NOT
supported — the router only selects this spine for prompt builds in schema
mode.

What the graph buys over the hand-rolled relay:

  * **Resumable builds** — every node completion is checkpointed to
    ``data/pipeline_checkpoints.sqlite3`` keyed by the project slug
    (``thread_id``). A crashed/killed build relaunched with the same slug
    replays instantly through completed nodes and continues from the first
    unfinished one.
  * **LangSmith tracing** — with ``LANGSMITH_TRACING=true`` the whole build
    is one trace tree: phases → agent turns → token counts.
  * **A declared topology** — the phase order is data (edges), not 2,200
    lines of interleaved control flow.

Selected by default for prompt builds (``FORGE_LANGGRAPH_PIPELINE=0`` opts
back into the legacy relay).

SSE bridge: nodes push the same event dicts the legacy relay yields into an
``asyncio.Queue`` carried in the graph config; ``run_pipeline_graph`` drains
the queue while the graph runs, so callers consume the familiar
``AsyncIterator[dict]`` generator contract unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid as _uuid
from pathlib import Path
from typing import Any, AsyncIterator, TypedDict

logger = logging.getLogger(__name__)

_CHECKPOINT_DB = os.path.join("data", "pipeline_checkpoints.sqlite3")
_SENTINEL = object()


class _CoverageHalt(Exception):
    """Raised by bootstrap when the coverage-verdict gate refuses the brief.
    The refusal SSE event has already been emitted; the driver treats this
    as a clean stop, not an error."""


class PipelineState(TypedDict, total=False):
    output_dir: str
    description: str
    plan: dict
    domain_context: dict | None
    project_id: str | None
    design_spec: dict | None
    design_dna: dict | None
    errors: list[str]
    totals: dict
    quarantine: list[dict]
    ship_verdict: str
    heal_rounds: int


def _emit(config: dict, event: dict) -> None:
    q: asyncio.Queue | None = (config.get("configurable") or {}).get("emit_queue")
    if q is not None:
        q.put_nowait(event)


def _log(config: dict, text: str) -> None:
    from sse_helpers import sse_event
    _emit(config, sse_event("log", {"text": text}))


def _status(config: dict, message: str) -> None:
    from sse_helpers import sse_event
    _emit(config, sse_event("status", {"message": message}))


def _phase(config: dict, name: str, index: int, total: int, status: str) -> None:
    from sse_helpers import sse_event
    _emit(config, sse_event("phase", {
        "name": name, "index": index, "total": total,
        # Only a phase that finished counts as completed.
        "completed": index if status == "done" else index - 1,
        "status": status,
    }))


def with_phase_progress(fn, *, name: str, index: int, total: int):
    """Wrap a spine node so the stream says where the build is.

    Emits a ``phase`` SSE event on entry and on exit:

        {"name": "contracts", "index": 5, "total": 12,
         "completed": 4, "status": "running"|"done"|"failed"}

    ``completed`` is the count a client should render — it stays at
    ``index - 1`` while the phase runs and on failure, so a failed phase is
    never counted as finished. Gate nodes are not wrapped: they are
    sub-steps of the phase they follow, and numbering them would double the
    total the user sees.

    The exception is re-raised after the ``failed`` event — the event is for
    the user, not a substitute for the error.
    """
    from functools import wraps

    @wraps(fn)
    async def _wrapped(state: PipelineState, config: dict):
        _phase(config, name, index, total, "running")
        try:
            result = await fn(state, config)
        except Exception:
            _phase(config, name, index, total, "failed")
            raise
        _phase(config, name, index, total, "done")
        return result

    _wrapped._phase_index = index    # noqa: SLF001 — read by the wiring test
    _wrapped._phase_total = total    # noqa: SLF001
    return _wrapped


def _project_uuid(state: PipelineState):
    pid = state.get("project_id")
    if not pid:
        return None
    try:
        return _uuid.UUID(str(pid))
    except Exception:  # noqa: BLE001
        return None


async def _stream_agent(config: dict, state: PipelineState, label: str,
                        messages: Any, collect: list[str] | None = None) -> dict:
    """Forward one agent's message stream into the SSE queue with the same
    idle-timeout wrapper and agent_result accounting the legacy relay uses.
    Returns the cost/turn/duration deltas for this phase."""
    from services.parallel_runner import stream_with_idle_timeout

    totals = {"cost_usd": 0.0, "num_turns": 0, "duration_ms": 0}
    _status(config, f"{label} running…")
    async for evt in stream_with_idle_timeout(label, state["output_dir"], messages):
        if evt.get("event") == "agent_result":
            try:
                data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else (evt.get("data") or {})
                totals["cost_usd"] += data.get("cost_usd", 0) or 0
                totals["num_turns"] += data.get("num_turns", 0) or 0
                totals["duration_ms"] += data.get("duration_ms", 0) or 0
            except Exception:  # noqa: BLE001
                pass
            continue
        if collect is not None and evt.get("event") in ("log", "message"):
            try:
                data = json.loads(evt["data"]) if isinstance(evt.get("data"), str) else (evt.get("data") or {})
                text = data.get("text", "")
                if text:
                    collect.append(text)
            except Exception:  # noqa: BLE001
                pass
        _emit(config, evt)
    return totals


def _merge_totals(state: PipelineState, delta: dict) -> dict:
    totals = dict(state.get("totals") or {"cost_usd": 0.0, "num_turns": 0, "duration_ms": 0})
    for k in ("cost_usd", "num_turns", "duration_ms"):
        totals[k] = totals.get(k, 0) + (delta.get(k, 0) or 0)
    return totals


# ── nodes ────────────────────────────────────────────────────────────────

async def _node_bootstrap(state: PipelineState, config: dict) -> dict:
    """Plan hygiene + authority artifacts, mirroring the relay's pre-design
    head: normalize → coverage gate → archetype stamp + required pages →
    domain reclass → directive parser → requirement.json → canonicalize +
    persist plan.json → plan-workflow sync."""
    from routers.generate import _ensure_normalized_plan, _sync_workflows_from_plan
    from sse_helpers import sse_event

    out = state["output_dir"]
    description = state.get("description") or ""
    plan = _ensure_normalized_plan(dict(state["plan"]))

    # Ambient session context — same stamp the relay applies (IRF-M5-T2 lite).
    try:
        from services.session_context import from_plan as _sc_from_plan, set_current as _sc_set_current
        _sc_set_current(_sc_from_plan(plan))
    except Exception:  # noqa: BLE001
        pass

    # Coverage-verdict gate — refuse out-of-scope briefs before spending tokens.
    try:
        from services.coverage_verdict_gate import evaluate as _gate_evaluate
        from services.substrate_gap_log import append as _gap_log_append
        _brief_summary = (plan.get("description") or plan.get("brief")
                          or plan.get("prompt") or description or "")[:500]
        _gate = _gate_evaluate(plan, brief_summary=_brief_summary,
                               gen_slug=str(Path(out).name) if out else "")
        if _gate.action == "proceed_and_log_gap":
            if _gate.gap_log_entry is not None:
                _gap_log_append(_gate.gap_log_entry)
        elif _gate.action == "halt":
            _emit(config, sse_event("coverage_verdict", _gate.refusal_payload or {}))
            raise _CoverageHalt()
    except _CoverageHalt:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("[coverage_verdict] gate crashed, proceeding: %s", exc)

    # Archetype stamp (keyword classifier; existing archetype wins).
    try:
        if not (plan.get("archetype") or plan.get("app_archetype")):
            from services.app_design_catalog import classify_app_archetype
            _matched = classify_app_archetype(
                plan.get("description") or plan.get("brief") or plan.get("prompt") or "")
            if _matched:
                plan["archetype"] = _matched
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan] archetype stamp skipped: %s", exc)

    # Archetype-required pages / workflows / columns.
    try:
        from services.archetypes import (ensure_required_columns, ensure_required_pages,
                                         ensure_required_workflows)
        ensure_required_pages(plan)
        ensure_required_workflows(plan)
        ensure_required_columns(plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan] required-pages injection skipped: %s", exc)

    # Domain re-classification (planner enum → 17-bucket keyword).
    try:
        from services.plan_finalize import reclassify_plan_domain
        _before, _after, _changed = reclassify_plan_domain(plan)
        if _changed:
            _log(config, f"[domain] reclassified {_before!r} → {_after!r}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[domain] reclassify skipped: %s", exc)

    # Prompt-directive parser → plan.hints / plan.archetype / plan.brief_hints.
    try:
        from services.plan_directive_parser import enrich_plan_with_directives
        enrich_plan_with_directives(plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan] directive parser skipped: %s", exc)

    # requirement.json — first-class user-requirement artifact.
    try:
        from services.requirement import ensure_requirement
        ensure_requirement(out, plan.get("description") or plan.get("brief") or plan.get("prompt") or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[requirement] persist skipped: %s", exc)

    # Canonicalize + persist the plan as contracts/plan.json (authority).
    try:
        from services.plan_canonicalizer import canonicalize_plan
        plan, _ = canonicalize_plan(plan)
        _contracts_dir = Path(out) / "src" / "contracts"
        _contracts_dir.mkdir(parents=True, exist_ok=True)
        (_contracts_dir / "plan.json").write_text(
            json.dumps(plan, indent=2, default=str), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[plan-persist] skipped: %s", exc)

    # Plan workflows → workflows/*.json (idempotent).
    try:
        _sync_workflows_from_plan(out, plan)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[workflow-sync] skipped: %s", exc)

    return {"plan": plan}


async def _node_maquettes(state: PipelineState, config: dict) -> dict:
    """Dashboard / collection / record maquettes (profile-gated LLM turns)."""
    try:
        from services.plan_finalize import (author_collection_maquettes_if_enabled,
                                            author_dashboard_maquette_if_enabled,
                                            author_record_maquettes_if_enabled,
                                            ensure_composition_reference)
        plan, out = state["plan"], state["output_dir"]
        # Read the designated montage FIRST: all three authors below read the
        # file this writes to learn what their screen kind should carry.
        _ref = await ensure_composition_reference(plan, out, state.get("project_id"))
        if _ref is not None:
            _log(config, f"[montage] composition reference: "
                         f"{', '.join(sorted(_ref.get('screens') or {})) or 'layout only'}")
        _maq = await author_dashboard_maquette_if_enabled(plan, out)
        if _maq is not None:
            _log(config, f"[maquette] wrote {len(_maq.get('kpis') or [])} KPIs, "
                         f"chart={'y' if _maq.get('primary_chart') else 'n'}")
        _col = await author_collection_maquettes_if_enabled(plan, out)
        if _col is not None:
            _log(config, f"[maquette/collection] wrote {len(_col)} collection maquette(s)")
        _rec = await author_record_maquettes_if_enabled(plan, out)
        if _rec is not None:
            _log(config, f"[maquette/record] wrote {len(_rec)} record maquette(s)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[maquette] pass failed: %s", exc)
    return {}


async def _node_discovery(state: PipelineState, config: dict) -> dict:
    """Domain discovery dossier + design-brief authoring. Uses the caller's
    user-approved domain_context when supplied; otherwise runs discovery
    (abort on failure — same contract as the relay)."""
    from agents.domain_agent import persist_discovery, run_domain_discovery
    from routers.generate import _author_and_persist_brief

    out, plan = state["output_dir"], state["plan"]
    domain_ctx = state.get("domain_context")
    if domain_ctx is not None:
        persist_discovery(out, domain_ctx)
        await _author_and_persist_brief(out, domain_ctx, plan, figma_context=None,
                                       project_id=state.get("project_id"))
        _log(config, f"[Discovery] ✓ Using user-approved domain context: "
                     f"{domain_ctx.get('domain', 'Generic')}")
    else:
        _status(config, "Researching domain context...")
        try:
            domain_ctx = await run_domain_discovery(
                state.get("description") or "", plan, enable_web_search=True)
        except Exception as exc:
            _log(config, f"[Discovery] ⚠ FAILED: {exc} — aborting generation")
            raise
        persist_discovery(out, domain_ctx)
        await _author_and_persist_brief(out, domain_ctx, plan, figma_context=None,
                                       project_id=state.get("project_id"))
        _log(config, f"[Discovery] ✓ Domain: {domain_ctx.get('domain', 'Generic')} | "
                     f"{len(domain_ctx.get('designPatterns', []))} pattern(s)")
    return {"domain_context": domain_ctx}


async def _node_foundation(state: PipelineState, config: dict) -> dict:
    """Template floor + reachability + canonical/contract registries +
    fk-semantics + app-design report."""
    import shutil

    from routers.generate import _clean_schemas_dir
    from services.registry import create_registry, save_registry

    out = state["output_dir"]
    plan = state["plan"]

    template_dir = Path(__file__).parent.parent / "templates" / "app-foundation"
    if template_dir.exists():
        dst = Path(out)
        copied = 0
        for src_file in template_dir.rglob("*"):
            if src_file.is_file():
                target = dst / src_file.relative_to(template_dir)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_file, target)
                    copied += 1
        _log(config, f"[Templates] Copied {copied} foundation files (auth, hooks, UI components)")

    try:
        from services.app_design_guardrail import ensure_entity_reachability
        plan, _reach = ensure_entity_reachability(plan)
        if _reach["promoted"]:
            _log(config, f"[Design] promoted orphaned entities to pages: {_reach['promoted']}")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Design] reachability guard skipped: {exc}")

    try:
        from services.resource_registry import build_canonical_registry, write_registry
        write_registry(build_canonical_registry(plan), out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("build_canonical_registry skipped: %s", exc)

    try:
        from services.fk_semantics import emit_fk_semantics
        emit_fk_semantics(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("emit_fk_semantics skipped: %s", exc)

    registry = create_registry(plan)
    save_registry(out, registry)
    _removed = _clean_schemas_dir(out)
    if _removed > 0:
        _log(config, f"[Cleanup] Removed {_removed} stale schema file(s)")
    _log(config, f"[Registry] Initialized: {len(registry['entities'])} entities, "
                 f"{len(registry['api_routes'])} routes")

    try:
        from services.app_design_guardrail import normalize_app_design
        _, _report = normalize_app_design(plan)
        (Path(out) / "app-design-report.json").write_text(json.dumps(_report, indent=2))
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Design] report skipped: {exc}")

    return {"plan": plan}


async def _node_design(state: PipelineState, config: dict) -> dict:
    """The full design-authority chain: DNA → 21st prefetch → brief-canonical
    OR design agent → brand auto-detect → merge-precedence spec resolution →
    template seeding → register → token compile. Faithful port of the relay."""
    from agents.design_agent import extract_design_spec, run_design_agent, save_design_spec
    from config import FIDELITY_MODE_ENABLED
    from services.brief_to_design_spec import brief_to_design_spec
    from services.design_brief_to_prompt import load_brief_from_disk

    out, plan = state["output_dir"], state["plan"]
    description = state.get("description") or ""
    domain_ctx = state.get("domain_context") or {}
    domain_label = domain_ctx.get("domain", "Generic") if isinstance(domain_ctx, dict) else "Generic"

    # ── Design DNA ──
    design_dna: dict | None = None
    dna_brief: str | None = None
    _brief_for_dna = None
    try:
        from services.design_dna import derive_design_dna, prompt_brief
        _plan_domain = str((plan or {}).get("domain") or "").strip()
        if _plan_domain.lower() in ("general", "generic", ""):
            _plan_domain = ""
        _dna_domain = " ".join(x for x in (_plan_domain, str(domain_label or "")) if x).strip() or "general"
        _ctx_parts: list[str] = [str(description or (plan or {}).get("description") or "")]
        if isinstance(domain_ctx, dict):
            _ctx_parts.append(str(domain_ctx.get("description") or ""))
            _ctx_parts.extend(str(a) for a in (domain_ctx.get("domainAliases") or [])[:6])
        _ctx_parts.append(str((plan or {}).get("app_name") or ""))
        _ctx_parts.append(str((plan or {}).get("module_name") or ""))
        _ents = (plan or {}).get("entities")
        if isinstance(_ents, dict):
            _ctx_parts.extend(list(_ents.keys())[:20])
        for _p in ((plan or {}).get("pages") or [])[:26]:
            if isinstance(_p, dict):
                _ctx_parts.append(str(_p.get("name") or _p.get("title") or ""))
        try:
            _brief_for_dna = load_brief_from_disk(out)
        except Exception:  # noqa: BLE001
            _brief_for_dna = None
        design_dna = derive_design_dna(
            project_id=Path(out).name,
            domain=_dna_domain,
            context=" ".join(x for x in _ctx_parts if x)[:2000],
            dossier=domain_ctx if isinstance(domain_ctx, dict) else None,
            brief=_brief_for_dna,
        )
        dna_brief = prompt_brief(design_dna)
        _dna_path = Path(out) / "src" / "contracts" / "design-dna.json"
        _dna_path.parent.mkdir(parents=True, exist_ok=True)
        _dna_path.write_text(json.dumps(design_dna, indent=2))
        _log(config, f"[Design DNA] {design_dna['archetype']} · "
                     f"{design_dna['typography']['pairing']} · primary "
                     f"{design_dna['color']['primary']}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Design DNA] derivation failed")
        _log(config, f"[Design DNA] skipped: {exc}")

    # ── 21st.dev pre-fetch (flag-gated) ──
    try:
        from services import magic_mcp as _magic
        if _magic.is_enabled():
            from services import magic_prefetch as _prefetch
            _early_brief = load_brief_from_disk(out)
            _prefetch_domain = None
            _prefetch_brief_dict = None
            if _early_brief is not None:
                _prefetch_domain = getattr(_early_brief.identity, "domain", None)
                try:
                    _prefetch_brief_dict = json.loads(_early_brief.model_dump_json())
                except Exception:  # noqa: BLE001
                    _prefetch_brief_dict = None
            if not _prefetch_domain:
                _prefetch_domain = (plan or {}).get("domain")
            _refs = await _prefetch.prefetch_references(
                out, domain=_prefetch_domain, brief=_prefetch_brief_dict)
            _log(config, f"[21st] Pre-fetch wrote {len(_refs)} references")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[21st] Pre-fetch skipped: {exc}")

    # ── Brief-canonical branch or design-agent LLM ──
    _canonical = (os.getenv("FORGE_BRIEF_CANONICAL", "0") == "1"
                  and os.getenv("FORGE_LEGACY_DESIGN_AGENT", "0") != "1")
    canonical_brief = load_brief_from_disk(out) if _canonical else None

    totals = dict(state.get("totals") or {})
    collected_design_text: list[str] = []
    figma_screenshots = sorted(str(p) for p in Path(out).glob("reference*.png"))
    if canonical_brief is not None:
        _log(config, f"[Design] Brief-canonical path — no LLM "
                     f"(brand={canonical_brief.palette.brand})")
    else:
        delta = await _stream_agent(
            config, state, "Design",
            run_design_agent(out, plan, domain_context=domain_ctx,
                             figma_screenshots=figma_screenshots or None,
                             dna_brief=dna_brief),
            collect=collected_design_text)
        totals = _merge_totals(state, delta)

    # ── Brand auto-detect from a URL in the brief ──
    brand_derived: dict | None = None
    try:
        import re as _re
        m = _re.search(r"https?://[^\s\")>]+",
                       " ".join([description or "", (plan or {}).get("description") or ""]))
        if m:
            from services.url_brand_scraper import scrape_brand_from_url
            scraped = await asyncio.to_thread(scrape_brand_from_url, m.group(0))
            if scraped and getattr(scraped, "derived", None):
                d = scraped.derived
                brand_derived = {
                    "primary": d.primary, "secondary": d.secondary, "accent": d.accent,
                    "background": d.background, "surface": d.surface,
                    "text": d.text, "border": d.border,
                    "success": d.success, "warning": d.warning, "destructive": d.destructive,
                    "source_url": m.group(0),
                }
                _log(config, f"[Brand] Extracted primary {d.primary} from {m.group(0)}")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Brand] Auto-detect skipped: {exc}")

    # ── Spec resolution (same precedence chain as the relay) ──
    design_spec: dict | None
    if canonical_brief is not None:
        design_spec = brief_to_design_spec(canonical_brief)
        if brand_derived:
            design_spec.setdefault("brand", {})["derived"] = brand_derived
        save_design_spec(out, design_spec, plan=plan)
        _log(config, "[Design] Brief-canonical spec saved")
    else:
        design_spec = extract_design_spec("\n".join(collected_design_text))
        _fallback_brief = load_brief_from_disk(out)
        if design_spec:
            try:
                from services.design_compiler import _merge_spec
                if _fallback_brief is not None:
                    base = brief_to_design_spec(_fallback_brief)
                    _lock_active = bool(getattr(_fallback_brief, "visual_lock", None)
                                        and _fallback_brief.visual_lock.is_active())
                    design_spec = (_merge_spec(design_spec, base) if _lock_active
                                   else _merge_spec(base, design_spec))
                elif design_dna:
                    from services.design_dna import to_design_spec as _dna_spec
                    design_spec = _merge_spec(_dna_spec(design_dna), design_spec)
            except Exception:  # noqa: BLE001
                logger.exception("[Design] merge-base build failed (using raw spec)")
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(out, design_spec, plan=plan)
            _log(config, f"[Design] Design spec saved — theme: "
                         f"{design_spec.get('colorPalette', {}).get('primary', '?')}")
        elif _fallback_brief is not None:
            design_spec = brief_to_design_spec(_fallback_brief)
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(out, design_spec, plan=plan)
            _log(config, "[Design] Agent fence unparseable — using the design brief")
        elif design_dna:
            from services.design_dna import to_design_spec as _dna_spec
            design_spec = _dna_spec(design_dna)
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(out, design_spec, plan=plan)
            _log(config, "[Design] Agent fence unparseable — using the design DNA")
        else:
            from services.industry_design import generate_design_spec_from_industry
            design_spec = generate_design_spec_from_industry(
                domain_label, description, plan, domain_context=domain_ctx)
            if brand_derived:
                design_spec.setdefault("brand", {})["derived"] = brand_derived
            save_design_spec(out, design_spec, plan=plan)
            _log(config, f"[Design] Using industry defaults for {domain_label}")

    # ── User-selected design template wins on visuals ──
    try:
        from services.design_template_store import load_selection
        from services.design_templates import seed_design_spec
        _sel = load_selection(out)
        if _sel:
            design_spec = seed_design_spec(design_spec, _sel)
            save_design_spec(out, design_spec, plan=plan)
            _log(config, f"[Design] Applied selected template: {_sel.get('name')}")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Design] Template seeding skipped: {exc}")

    # ── Register (DNA skin is the single authority; LLM classify fallback) ──
    try:
        from agents.planner import classify_register_llm
        from services.cta_defaults import defaults_for_register
        register = ((design_dna or {}).get("register")
                    or plan.get("register")
                    or await classify_register_llm(description, plan.get("domain", ""), plan))
        if design_spec is not None:
            design_spec["register"] = register
            design_spec["cta_hierarchy"] = defaults_for_register(register)
            save_design_spec(out, design_spec, plan=plan)
            _log(config, f"[Design] Register: {register}")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Design] register classification skipped: {exc}")

    # ── Compile design-spec → tokens.custom.json ──
    if FIDELITY_MODE_ENABLED:
        try:
            from services.design_compiler import compile_to_file
            spec_path = Path(out) / "src" / "contracts" / "design-spec.json"
            if spec_path.exists():
                compile_to_file(json.loads(spec_path.read_text()),
                                str(Path(out) / "src" / "theme" / "tokens.custom.json"))
                _log(config, "[Tokens] ✓ Compiled tokens.custom.json from design-spec")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[Tokens] design_compiler failed")
            _log(config, f"[Tokens] ⚠ Compile failed (non-fatal): {exc}")
    if design_dna is not None:
        try:
            from services.design_compiler import compile_to_file as _ctf
            _spec_path = Path(out) / "src" / "contracts" / "design-spec.json"
            _spec = json.loads(_spec_path.read_text()) if _spec_path.exists() else {}
            _ctf(_spec, str(Path(out) / "src" / "theme" / "tokens.custom.json"), dna=design_dna)
            _log(config, "[Tokens] ✓ DNA-merged tokens.custom.json compiled")
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[Tokens] ⚠ DNA compile failed (non-fatal): {exc}")

    # Make the design identity visible to every downstream page author.
    if design_spec is not None:
        plan["design_spec"] = design_spec
    plan["_output_dir"] = out
    return {"design_spec": design_spec, "design_dna": design_dna,
            "plan": plan, "totals": totals or state.get("totals") or {}}


async def _node_contracts(state: PipelineState, config: dict) -> dict:
    """Deterministic contracts first; LLM agent only fills gaps; completeness
    gate retries once; approval start-bindings patched in."""
    from agents.contract_agent import run_contract_agent
    from services.contract_generator import ensure_approval_bindings, generate_contracts
    from services.phase_gates import check_contract_completeness

    out, plan = state["output_dir"], state["plan"]
    domain_ctx = state.get("domain_context")
    totals = dict(state.get("totals") or {})

    _status(config, "Generating contracts...")
    try:
        _cg = generate_contracts(out, plan)
        _log(config, f"[Contract] deterministic: {len(_cg.get('generated', []))} file(s), "
                     f"{len(_cg.get('errors', []))} error(s)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Contract] deterministic generation failed (falling back to LLM): {exc}")

    if check_contract_completeness(out, plan)["passed"]:
        _log(config, "[Contract] deterministic contracts complete — skipping LLM agent")
    else:
        delta = await _stream_agent(config, state, "Contract",
                                    run_contract_agent(out, plan, domain_context=domain_ctx))
        totals = _merge_totals({"totals": totals}, delta)  # type: ignore[arg-type]

    gate = check_contract_completeness(out, plan)
    if not gate["passed"]:
        _log(config, f"[Contract Gate] {len(gate['missing'])} gaps found — sending back to contract agent")
        try:
            delta = await _stream_agent(config, state, "Contract-Fix",
                                        run_contract_agent(out, plan, domain_context=domain_ctx))
            totals = _merge_totals({"totals": totals}, delta)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[Contract Gate] Fix attempt failed: {exc}")
    else:
        _log(config, "[Contract Gate] ✓ All contracts complete")

    try:
        _eb = ensure_approval_bindings(out, plan)
        if _eb["added"]:
            _log(config, f"[Contract] approval start-bindings: added {_eb['added']} binding(s)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Contract] approval-binding patch skipped: {exc}")

    return {"totals": totals}


async def _node_schema(state: PipelineState, config: dict) -> dict:
    """Deterministic Drizzle schema first; LLM fallback; registry extraction
    + canonical-registry reconcile."""
    from agents.schema_agent import run_schema_agent
    from routers.generate import _schema_files_complete
    from services.registry import load_registry, reconcile_entities, save_registry
    from services.registry_extractor import extract_entities_from_schema
    from services.registry_schema_reconcile import reconcile_registry_to_schema
    from services.schema_builder import build_schema_files

    out, plan = state["output_dir"], state["plan"]
    totals = dict(state.get("totals") or {})

    _status(config, "Building foundation (schema, config, types)...")
    try:
        _sb = build_schema_files(plan, out)
        _log(config, f"[Schema] deterministic: {len(_sb.get('generated', []))} file(s), "
                     f"{len(_sb.get('errors', []))} error(s)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Schema] deterministic generation failed (falling back to LLM): {exc}")

    if _schema_files_complete(out, plan):
        _log(config, "[Schema] deterministic schema complete — skipping LLM agent")
    else:
        delta = await _stream_agent(
            config, state, "Schema",
            run_schema_agent(out, plan, domain_context=state.get("domain_context"),
                             project_short_id=Path(out).name))
        totals = _merge_totals({"totals": totals}, delta)  # type: ignore[arg-type]

    extracted = extract_entities_from_schema(out)
    if extracted:
        registry = load_registry(out)
        registry = reconcile_entities(registry, extracted)
        save_registry(out, registry)
        _log(config, f"[Registry] Updated entities from schema: {len(extracted)} extracted")

    try:
        _rc = reconcile_registry_to_schema(out)
        logger.info("resource-registry reconciled to schema: %d entities, %d columns",
                    _rc["entities_reconciled"], _rc["columns_updated"])
    except Exception:  # noqa: BLE001
        logger.exception("resource-registry schema reconcile failed (non-fatal)")

    try:
        from services.progress_events import iter_entities
        for _rev in iter_entities(out):
            from sse_helpers import sse_event
            _emit(config, sse_event("resource", _rev))
    except Exception:  # noqa: BLE001
        pass

    return {"totals": totals}


async def _node_workflows(state: PipelineState, config: dict) -> dict:
    """Conditional BusinessLogic agent (deterministic-first) + route
    extraction + registry validation. Entity CRUD is served by the Data
    Engine catch-all — no per-entity API agent (same as the relay)."""
    from routers.generate import _deterministic_workflows
    from services.registry import load_registry, merge_section, save_registry
    from services.registry_extractor import extract_routes_from_files
    from services.registry_validator import format_validation_report, validate_registry
    from sse_helpers import sse_event

    out, plan = state["output_dir"], state["plan"]
    totals = dict(state.get("totals") or {})

    if plan.get("workflows") and not _deterministic_workflows():
        from agents.business_logic_agent import run_business_logic_agent
        _status(config, "Generating business logic (domain workflows + services)...")
        delta = await _stream_agent(
            config, state, "BusinessLogic",
            run_business_logic_agent(out, plan, domain_context=state.get("domain_context")))
        totals = _merge_totals({"totals": totals}, delta)  # type: ignore[arg-type]

    registry = load_registry(out)
    extracted = extract_routes_from_files(out)
    if extracted:
        registry = merge_section(registry, "api_routes", extracted)
        save_registry(out, registry)
        _log(config, f"[Registry] Updated routes: {len(extracted)} extracted")

    reg_errors = validate_registry(registry)
    if reg_errors:
        _log(config, f"[Registry] {format_validation_report(reg_errors)}")
        _emit(config, sse_event("registry_validation", {
            "phase": "post_api",
            "errors": [{"section": e.section, "name": e.name, "error": e.error,
                        "suggestion": e.suggestion, "severity": e.severity}
                       for e in reg_errors]}))

    return {"totals": totals}


async def _node_rules(state: PipelineState, config: dict) -> dict:
    """Rules agent — planner prose → structured ProjectRules (+ DB sync)."""
    try:
        from agents.rules_agent import run_rules_agent
        _status(config, "Generating business rules...")
        rules = await run_rules_agent(
            state["output_dir"], state["plan"],
            domain_context=state.get("domain_context"),
            project_id=_project_uuid(state))
        _log(config, f"[Rules] Generated {len(rules)} rule(s) from planner intent")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Rules] agent failed")
        _log(config, f"[Rules] ⚠ Generation failed (non-fatal): {exc}")
    return {}


async def _node_runtime(state: PipelineState, config: dict) -> dict:
    """Auth gate → runtime injection → platform integrations sync → route
    prune → catch-all gate → deterministic CRUD workflows → binding contract."""
    import shutil

    from services.runtime_injector import inject_runtime

    out, plan = state["output_dir"], state["plan"]
    project_uuid = _project_uuid(state)

    # Auth gate — auth is template-owned; re-copy anything missing.
    try:
        from services.phase_gates import check_auth_completeness
        auth_gate = check_auth_completeness(out)
        if not auth_gate["passed"]:
            _log(config, f"[Auth Gate] {len(auth_gate['issues'])} auth issues — re-copying templates")
            template_dir = Path(__file__).parent.parent / "templates" / "app-foundation"
            for auth_file in ["src/auth.ts", "src/middleware.ts",
                              "src/app/api/auth/[...nextauth]/route.ts",
                              "src/app/api/auth/signup/route.ts"]:
                src = template_dir / auth_file
                dst = Path(out) / auth_file
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
        else:
            _log(config, "[Auth Gate] ✓ Auth layer complete")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Auth Gate] check skipped: {exc}")

    try:
        rt = inject_runtime(out,
                            app_name=(plan.get("appName") or plan.get("module_name") or plan.get("name")),
                            domain=plan.get("domain"),
                            project_id=str(project_uuid) if project_uuid else None)
        _log(config, f"[Runtime] Injected Data Engine + Workflow Engine: "
                     f"{len(rt.get('copied', []))} files copied")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Runtime] Injection failed: {exc}")

    # Platform integrations → .env.local (org keys + MCP servers).
    if project_uuid is not None:
        try:
            from database import async_session
            from models.project import Project
            from services.env_writer import write_env_local_from_platform
            async with async_session() as _db:
                _proj = await _db.get(Project, project_uuid)
                if _proj is not None and _proj.org_id is not None:
                    _iw = await write_env_local_from_platform(out, _proj.org_id, _db)
                    _log(config, f"[Integrations] Synced .env.local: "
                                 f"{len(_iw.get('set', []) or [])} key(s), "
                                 f"{_iw.get('mcp_servers', 0)} MCP server(s)")
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[Integrations] Sync skipped: {exc}")

    # Prune artifacts that bypass the engines; keep registry in sync.
    try:
        from services.api_route_prune import prune_entity_crud_routes
        from services.registry import load_registry, merge_section, save_registry
        from services.registry_extractor import extract_routes_from_files
        pruned = prune_entity_crud_routes(out)
        if pruned["deleted"] or pruned["deleted_actions"] or pruned["deleted_services"]:
            _log(config, f"[API] pruned {len(pruned['deleted'])} CRUD route(s), "
                         f"{len(pruned['deleted_actions'])} bypass action-route(s), "
                         f"{len(pruned['deleted_services'])} TS service(s)")
        extracted = extract_routes_from_files(out)
        if extracted:
            registry = load_registry(out)
            registry = merge_section(registry, "api_routes", extracted)
            save_registry(out, registry)
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[API] route prune skipped: {exc}")

    # API gate: the Data Engine catch-all must exist.
    _catch_all = Path(out) / "src" / "app" / "api" / "data" / "[...path]" / "route.ts"
    if _catch_all.exists():
        _log(config, "[API Gate] ✓ Data Engine catch-all present")
    else:
        _log(config, "[API Gate] ⚠ Data Engine catch-all missing — re-injecting runtime")
        try:
            inject_runtime(out,
                           app_name=(plan.get("appName") or plan.get("module_name") or plan.get("name")),
                           domain=plan.get("domain"), project_id=project_uuid)
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[API Gate] catch-all re-injection failed: {exc}")

    # Deterministic CRUD workflows BEFORE binding.
    try:
        from services.crud_workflow_generator import generate_crud_workflows
        from services.registry import load_registry as _load_reg
        _crud_plan = plan if (plan or {}).get("entities") else \
            {"entities": (_load_reg(out) or {}).get("entities") or {}}
        _written = generate_crud_workflows(_crud_plan, out)
        if _written:
            _log(config, f"[CRUD] generated {len(_written)} workflow(s)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[CRUD] generation skipped: {exc}")

    try:
        from services.progress_events import iter_workflows
        from sse_helpers import sse_event
        for _rev in iter_workflows(out):
            _emit(config, sse_event("resource", _rev))
    except Exception:  # noqa: BLE001
        pass

    # Binding contract from reality (real entities + workflows on disk).
    try:
        from services.binding_contract import save_binding_contract
        _bc = save_binding_contract(out)
        _fk_total = sum(len(v.get("fkBindings") or []) for v in _bc.values())
        _log(config, f"[Contract] Derived binding contract for {len(_bc)} entities "
                     f"({_fk_total} FK bindings)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Contract] Binding contract skipped: {exc}")

    return {}


async def _node_pages(state: PipelineState, config: dict) -> dict:
    """Product brief → nav-flow → shell → per-page schema pipeline → auth
    page schemas → CTA / progressive-disclosure / coverage gates."""
    out, plan = state["output_dir"], state["plan"]
    design_spec = state.get("design_spec")
    domain_ctx = state.get("domain_context")

    _status(config, "Generating frontend via schema agent...")

    # Product brief (flag-gated, deterministic).
    _product_brief = None
    try:
        from services.product_brief import (derive_from_plan, is_product_brief_enabled,
                                            save_product_brief)
        if is_product_brief_enabled():
            _brief = None
            try:
                from services.design_brief_to_prompt import load_brief_from_disk
                _brief = load_brief_from_disk(out)
            except Exception:  # noqa: BLE001
                _brief = None
            _product_brief = derive_from_plan(plan, design_brief=_brief)
            save_product_brief(out, _product_brief)
            _log(config, f"[ProductBrief] ✓ {len(_product_brief.personas)} personas → product-brief.json")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[ProductBrief] synthesis failed — SL2 chain will no-op")
        _log(config, f"[ProductBrief] ⚠ synthesis failed: {exc}")

    # Nav-flow + shell.
    _nav_flow: dict | None = None
    try:
        from services.nav_flow_from_plan import nav_flow_from_plan, write_nav_flow
        _nav_flow = nav_flow_from_plan(plan, product_brief=_product_brief)
        write_nav_flow(out, _nav_flow)
        _log(config, f"[NavFlow] ✓ {len(_nav_flow.get('pages', []))} pages → nav-flow.json")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[NavFlow] ⚠ nav-flow build failed: {exc}")

    _shell_pages = [p for p in (_nav_flow or {}).get("pages", []) if p.get("shell")]
    if not _shell_pages:
        _log(config, "[ShellLayout] skipped — no shell:true pages in plan")
    else:
        try:
            from agents.shell_layout_agent import generate_shell_to_file
            from services.runtime_injector import _resolve_app_name
            _brand: dict | None = None
            if design_spec:
                _palette = design_spec.get("colorPalette", {})
                _brand = {
                    "primaryColor": _palette.get("primary"),
                    "secondaryColor": _palette.get("secondary"),
                    "primary": _palette.get("primary"),
                    "secondary": _palette.get("secondary"),
                    "appName": _resolve_app_name(
                        Path(out), plan.get("name") or plan.get("app_name"),
                        plan.get("domain")),
                    "logoUrl": design_spec.get("logoUrl"),
                }
            _shell = await generate_shell_to_file(
                output_dir=out, plan=plan, nav_flow=_nav_flow, brand=_brand,
                domain_context=domain_ctx, design_spec=design_spec)
            _log(config, "[ShellLayout] ✓ shell.json written" if _shell is not None
                 else "[ShellLayout] ⚠ no parseable schema — pages render bare")
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[ShellLayout] ⚠ failed: {exc} — pages will render bare")

    # Per-page schema pipeline, skipping auth routes.
    _auth_routes = {p.get("route") for p in (plan.get("pages") or [])
                    if isinstance(p, dict)
                    and (p.get("type") or "").lower() == "auth" and p.get("route")}
    try:
        from services.schema_pipeline import run_schema_frontend_pipeline
        async for evt in run_schema_frontend_pipeline(
                out, plan, state.get("description") or "",
                domain_context=domain_ctx,
                skip_routes=_auth_routes or None):
            _emit(config, evt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[Pipeline] Schema pipeline failed: %s", exc)
        _log(config, f"[Pipeline] ⚠ Schema pipeline error: {exc}")

    try:
        from services.stage_plan_emitter import record_after
        record_after("page_schema_agent", reason="pipeline run")
    except Exception:  # noqa: BLE001
        pass

    # Real auth-page form schemas.
    try:
        from services.auth_page_schema import emit_auth_page_schemas
        _written = emit_auth_page_schemas(out, plan)
        if _written:
            _log(config, f"[Auth] wrote real form schemas: {sorted(_written)}")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Auth] auth-schema emit skipped: {exc}")

    # Detection-only gates (CTA hierarchy, progressive disclosure, coverage).
    try:
        from services.phase_gates import (check_cta_hierarchy, check_pages_coverage,
                                          check_progressive_disclosure)
        for _name, _fn in (("CTA Gate", check_cta_hierarchy),
                           ("PD Gate", check_progressive_disclosure)):
            try:
                _g = _fn(out, plan)
                if not _g["passed"]:
                    _log(config, f"[{_name}] {len(_g['issues'])} issues — flagging only")
                else:
                    _log(config, f"[{_name}] ✓ passed")
            except Exception as exc:  # noqa: BLE001
                _log(config, f"[{_name}] check failed: {exc}")
        try:
            cov = check_pages_coverage(out, plan)
            if not cov["passed"]:
                _log(config, f"[Coverage Gate] {len(cov['missing'])} page(s) missing schema: "
                             f"{cov['missing']}")
            else:
                _log(config, "[Coverage Gate] ✓ Every plan.pages route has a schema")
        except Exception as exc:  # noqa: BLE001
            _log(config, f"[Coverage Gate] check failed: {exc}")
    except Exception:  # noqa: BLE001
        pass

    return {"plan": plan}


def _shell_menu_size(output_dir: str) -> int:
    """Number of navigable items in shell.json, at any nesting depth."""
    try:
        shell = json.loads((Path(output_dir) / "src" / "schemas" / "shell.json")
                           .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return -1  # unreadable ≠ empty; don't cry wolf
    seen: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key in ("href", "navigate", "route"):
                v = node.get(key) or (node.get("props") or {}).get(key)
                if isinstance(v, str) and v.startswith("/"):
                    seen.add(v)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(shell)
    return len(seen)


def _page_route_count(output_dir: str) -> int:
    sdir = Path(output_dir) / "src" / "schemas"
    if not sdir.is_dir():
        return 0
    return sum(1 for p in sdir.rglob("*.json") if p.name != "shell.json")


async def _node_finish(state: PipelineState, config: dict) -> dict:
    """The schema-path tail: photo injection → nav-flow emit → standalone app
    emitter → npm install → fidelity scoring → post-generate guard suite →
    session persistence → final accounting events."""
    from routers.generate import _run_npm_install, _stream_fidelity_scoring
    from services.post_generate_fixes import apply_post_generate_fixes
    from sse_helpers import sse_event

    out, plan = state["output_dir"], state["plan"]

    try:
        from services.post_emit_photo_injector import inject_photos_into_dir
        spec_path = Path(out) / "src" / "contracts" / "design-spec.json"
        if spec_path.exists():
            entity_photos = (json.loads(spec_path.read_text()).get("entityPhotos") or {})
            if entity_photos:
                n = inject_photos_into_dir(out, entity_photos)
                if n > 0:
                    _log(config, f"[Photos] Injected photo URLs into {n} page schema(s)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Photos] Injection skipped: {exc}")

    try:
        from services.nav_flow_emitter import emit_nav_flow
        emit_nav_flow(out, plan)
        _log(config, "[NavFlow] nav-flow.json written")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[NavFlow] Skipped: {exc}")

    try:
        from services.app_emitter import emit_standalone_app
        emit_standalone_app(output_dir=out, project_short_id=Path(out).name)
        _log(config, "[Emitter] Standalone Next.js app skeleton written")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Emitter] Skipped: {exc}")

    async for evt in _run_npm_install(out):
        _emit(config, evt)

    try:
        async for evt in _stream_fidelity_scoring(out, plan):
            _emit(config, evt)
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Fidelity] Pipeline skipped: {exc}")

    try:
        applied = await asyncio.to_thread(apply_post_generate_fixes, out)
        _log(config, f"[Pipeline] post-generate guards applied ({applied} fix(es))")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Pipeline] post-generate guards skipped: {exc}")

    # SHELL MENU FLOOR. An app with pages and no nav is unusable, and every
    # artifact-level check passes on an empty menu (valid JSON, valid
    # routes) — 5u9du8jt shipped with 28 pages and zero menu items and
    # every gate said warn. Cheap, structural, and loud.
    try:
        from services.shell_menu_sync import sync_shell_menu
        n_items = _shell_menu_size(out)
        if n_items == 0:
            _log(config, "[Shell] menu is EMPTY — re-deriving from nav-flow")
            await asyncio.to_thread(sync_shell_menu, out)
            n_items = _shell_menu_size(out)
        if n_items == 0 and _page_route_count(out) > 1:
            _log(config, "[Shell] ✗ menu still empty after sync — app has no navigation")
            state.setdefault("errors", []).append(
                "shell menu empty: the app has pages but no navigation")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Shell] menu floor skipped: {exc}")

    # CLICK-THROUGH VERIFICATION. The relay path ran this; the spine did
    # not, so flipping the spine to default silently stopped every build
    # from ever being opened and clicked. Artifact gates cannot see a dead
    # filter, an empty menu, or a page replaced by a Redirect — only
    # driving the app can. Fire-and-forget: never blocks the build.
    try:
        from services.self_verify_pass import is_enabled as _sv_on, run_self_verify
        pid = _project_uuid(config, state)
        if _sv_on() and pid is not None:
            _log(config, "[Verify] starting click-through pass")
            asyncio.create_task(run_self_verify(pid, invoked_by="auto_post_gen"))
        elif pid is not None:
            _log(config, "[Verify] skipped (FORGE_SELF_VERIFY off)")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Verify] could not start: {exc}")

    try:
        from services.session_context import current as _sc_current, persist_history
        _ctx = _sc_current()
        if _ctx is not None:
            persist_history(_ctx, out)
    except Exception:  # noqa: BLE001
        pass

    totals = state.get("totals") or {}
    _emit(config, sse_event("agent_result", {
        "num_turns": totals.get("num_turns", 0),
        "cost_usd": totals.get("cost_usd", 0.0),
        "duration_ms": totals.get("duration_ms", 0),
    }))
    return {}


# ── O4: plan-conditional routing ─────────────────────────────────────────
# The graph shape is code; the PLAN picks which edges activate. This is the
# safe form of "planner → task DAG": routing over a fixed node vocabulary,
# never a planner-authored topology.

async def _node_archetype(state: PipelineState, config: dict) -> dict:
    """Archetype-owned page rewrites as a first-class branch — entered only
    when the plan declares an archetype (see _route_after_pages). Idempotent;
    the post-generate suite backstops these same emitters."""
    out = state["output_dir"]
    applied = 0
    try:
        from services.archetype_page_fixes import (
            ensure_results_page_for_visual_product_search,
            rewrite_scan_page_for_visual_product_search)
        applied += rewrite_scan_page_for_visual_product_search(out) or 0
        applied += ensure_results_page_for_visual_product_search(out) or 0
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Archetype] page fixes skipped: {exc}")
    if applied:
        _log(config, f"[Archetype] {state['plan'].get('archetype')}: "
                     f"applied {applied} archetype page fix(es)")
    return {}


def _route_after_pages(state: PipelineState) -> str:
    """Enter the archetype branch only for archetype-stamped plans."""
    return "archetype" if (state.get("plan") or {}).get("archetype") else "pages_gate"


# ── O3: validate→repair→retry gate nodes ─────────────────────────────────

def _make_gate_node(phase: str):
    """A first-class ``<phase>_gate`` node: runs the phase's declared checks
    (services.phase_checks), retries deterministic repairs bounded, and
    quarantines whatever stays broken instead of hard-failing the build.
    A strict check (e.g. FORGE_BINDING_GATE=strict) raises and fails the
    build — same contract the relay's strict binding gate had."""
    async def _gate(state: PipelineState, config: dict) -> dict:
        from services.phase_checks import run_phase_gate, write_quarantine
        results = await asyncio.to_thread(
            run_phase_gate, phase, state["output_dir"], state["plan"])
        quarantine = list(state.get("quarantine") or [])
        for r in results:
            if r["passed"]:
                _log(config, f"[Gate:{phase}] ✓ {r['check']}"
                             + (f" (after {r['attempts']} repair(s))" if r["attempts"] else ""))
            else:
                quarantine.append(r)
                _log(config, f"[Gate:{phase}] ⚠ {r['check']}: "
                             f"{len(r['unresolved'])} unresolved issue(s) quarantined")
        if quarantine:
            write_quarantine(state["output_dir"], quarantine)
        return {"quarantine": quarantine}

    _gate.__name__ = f"_gate_{phase}"
    return _gate


# ── graph assembly ───────────────────────────────────────────────────────

_GATED_PHASES = ("contracts", "schema", "pages", "finish")

_PHASES: list[tuple[str, object]] = [
    ("bootstrap", _node_bootstrap),
    ("maquettes", _node_maquettes),
    ("discovery", _node_discovery),
    ("foundation", _node_foundation),
    ("design", _node_design),
    ("contracts", _node_contracts),
    ("schema", _node_schema),
    ("workflows", _node_workflows),
    ("rules", _node_rules),
    ("runtime", _node_runtime),
    ("pages", _node_pages),
    ("finish", _node_finish),
]

# Every phase is wrapped so the SSE stream carries "N of TOTAL · <name>".
# The total counts phases only — a `<phase>_gate` is a sub-step of the phase
# it follows, so counting gates would show the user twice as many steps as
# there are stages of work.
# +1 for the terminal "ship" node, which is appended below rather than
# listed above only because `_node_ship` is defined further down the module.
# It is a phase the user waits through, so it is counted and numbered.
_PHASE_TOTAL = len(_PHASES) + 1

_NODES = []
for _i, (_name, _fn) in enumerate(_PHASES, start=1):
    _NODES.append((_name, with_phase_progress(
        _fn, name=_name, index=_i, total=_PHASE_TOTAL)))
    if _name in _GATED_PHASES:
        _NODES.append((f"{_name}_gate", _make_gate_node(_name)))


async def _node_ship(state: PipelineState, config: dict) -> dict:
    """V3: the terminal verdict — fold every verification artifact into
    ship-report.json, emit it over SSE, and under FORGE_SHIP_GATE=strict
    fail the build on a blocking verdict."""
    from services.ship_report import build_ship_report
    from sse_helpers import sse_event

    report = await asyncio.to_thread(build_ship_report, state["output_dir"])
    s = report["summary"]
    _log(config, f"[Ship] verdict={report['verdict']} — "
                 f"{s['criticals']} critical, {s['errors']} error(s), "
                 f"{s['warnings']} warning(s) → ship-report.json")
    _emit(config, sse_event("ship_report", report))
    if report["verdict"] == "block" and report["mode"] == "strict":
        raise RuntimeError(
            f"[Ship] FORGE_SHIP_GATE=strict — build blocked: "
            f"{s['criticals']} critical / {s['errors']} error finding(s)")
    return {"ship_verdict": report["verdict"]}


_NODES.append(("ship", with_phase_progress(
    _node_ship, name="ship", index=_PHASE_TOTAL, total=_PHASE_TOTAL)))


# ── Agentic loop: ship → heal → re-verify → ship ─────────────────────────
# The observe→diagnose→repair→re-observe cycle, as a PRE-BUILT graph cycle:
# a non-pass verdict routes into `heal`, which dispatches the deterministic
# repair arsenal against the ship report's findings, then the walk re-enters
# finish_gate → ship for a fresh verdict. Bounded by FORGE_HEAL_ROUNDS
# (default 1; 0 disables). The LLM never chooses the topology — only what
# gets repaired inside the heal node.

def _max_heal_rounds() -> int:
    try:
        return max(0, int(os.environ.get("FORGE_HEAL_ROUNDS", "1")))
    except ValueError:
        return 1


async def _node_heal(state: PipelineState, config: dict) -> dict:
    """The loop's repair arm: read the ship report's findings, run the
    platform heals + the full deterministic guard sweep against them, and
    clear the quarantine so finish_gate re-evaluates from scratch."""
    out = state["output_dir"]
    rounds = int(state.get("heal_rounds") or 0) + 1
    _status(config, f"Heal round {rounds} — dispatching repairs against ship findings…")

    findings: list[dict] = []
    try:
        rep = json.loads((Path(out) / "ship-report.json").read_text(encoding="utf-8"))
        for name, src in (rep.get("sources") or {}).items():
            if src.get("present") and (src.get("criticals", 0) + src.get("errors", 0)) > 0:
                findings.append({"type": f"ship:{name}",
                                 "detail": (src.get("sample") or [""])[0]})
    except Exception:  # noqa: BLE001 — no report → sweep still runs below
        findings = [{"type": "ship:unknown", "detail": "ship report unreadable"}]

    healed = 0
    try:
        from services.platform_heals import apply_platform_heals
        r = await asyncio.to_thread(apply_platform_heals, out)
        if isinstance(r, dict):
            healed += int(r.get("applied", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Heal] platform heals skipped: {exc}")
    try:
        from services.repair_dispatcher import dispatch_repairs
        disp = await asyncio.to_thread(dispatch_repairs, out, findings)
        healed += int(disp.get("fixed", 0) or 0)
        _log(config, f"[Heal] round {rounds}: {disp.get('deterministic_fixed', 0)} "
                     f"guard fix(es), {len(disp.get('unhandled') or [])} unhandled")
    except Exception as exc:  # noqa: BLE001
        _log(config, f"[Heal] repair dispatch skipped: {exc}")

    # Fresh slate for re-verification — stale quarantine must not leak into
    # the next verdict (state AND the on-disk artifact the ship node reads).
    try:
        from services.phase_checks import write_quarantine
        write_quarantine(out, [])
    except Exception:  # noqa: BLE001
        pass
    _log(config, f"[Heal] round {rounds} applied {healed} repair(s) — re-verifying")
    return {"heal_rounds": rounds, "quarantine": []}


def _route_after_ship(state: PipelineState) -> str:
    """pass → end; non-pass → heal, until FORGE_HEAL_ROUNDS is spent."""
    verdict = str(state.get("ship_verdict") or "pass")
    if verdict == "pass":
        return "end"
    if int(state.get("heal_rounds") or 0) >= _max_heal_rounds():
        return "end"
    return "heal"


def _approval_gates() -> list[str]:
    """O2: human-approval gate configuration from FORGE_APPROVAL_GATES.

    * unset / "0" / "off" — no gates (fully autonomous builds, the default)
    * "1" / "on"          — the standard two gates: pause before ``design``
                            (plan + discovery + brief are done — approve the
                            direction before agents spend tokens) and before
                            ``pages`` (the blueprint — schema, contracts,
                            workflows, rules — is done; approve before the
                            frontend is authored)
    * comma-list          — explicit node names, validated against the
                            topology (unknown names are ignored)
    """
    raw = (os.environ.get("FORGE_APPROVAL_GATES") or "").strip().lower()
    if raw in ("", "0", "off", "false", "no"):
        return []
    valid = [n for n, _ in _NODES]
    if raw in ("1", "on", "true", "yes"):
        return [n for n in ("design", "pages") if n in valid]
    return [g.strip() for g in raw.split(",") if g.strip() in valid]


# Fan-out groups: after the key node, the members run CONCURRENTLY and the
# join node starts only when every member has completed (LangGraph barrier
# join via add_edge(list, node)). Members are data-independent by
# construction: maquettes/discovery/foundation only read the plan (design
# is the first consumer of discovery's dossier), and workflows/rules only
# read the emitted schema (runtime is the first consumer of both). Each
# member writes DISTINCT state keys, so the concurrent-superstep merge
# never conflicts. Applied only when all names are present, in order, so
# test-monkeypatched topologies stay purely linear.
_PARALLEL_AFTER: dict[str, tuple[list[str], str]] = {
    "bootstrap": (["maquettes", "discovery", "foundation"], "design"),
    "schema_gate": (["workflows", "rules"], "runtime"),
}


def build_pipeline_graph():
    """Uncompiled StateGraph — callers attach their own checkpointer.

    Spine with two parallel fan-out/join sections (_PARALLEL_AFTER), O4's
    plan-conditional archetype edge, and the ship→heal cycle. When tests
    monkeypatch ``_NODES`` with other names, the graph degrades to purely
    linear (no group/conditional names match)."""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)
    for name, fn in _NODES:
        g.add_node(name, fn)
    order = [n for n, _ in _NODES]

    conditional_after: dict[str, tuple] = {}
    if "pages" in order and "pages_gate" in order:
        g.add_node("archetype", _node_archetype)
        g.add_edge("archetype", "pages_gate")
        conditional_after["pages"] = (_route_after_pages,
                                      ["archetype", "pages_gate"])

    def _group_applies(at: str, idx: int) -> bool:
        members, join = _PARALLEL_AFTER.get(at, ([], ""))
        window = order[idx + 1: idx + 1 + len(members) + 1]
        return bool(members) and window == members + [join]

    g.add_edge(START, order[0])
    i = 0
    while i < len(order) - 1:
        a = order[i]
        if a in conditional_after:
            route_fn, targets = conditional_after[a]
            g.add_conditional_edges(a, route_fn, targets)
            i += 1
        elif _group_applies(a, i):
            members, join = _PARALLEL_AFTER[a]
            for m in members:
                g.add_edge(a, m)
            g.add_edge(members, join)  # barrier join
            i += 1 + len(members)      # resume the walk AT the join node
        else:
            g.add_edge(a, order[i + 1])
            i += 1

    # Agentic ship→heal→re-verify cycle (only in the real topology).
    if "ship" in order and "finish_gate" in order and order[-1] == "ship":
        g.add_node("heal", _node_heal)
        g.add_conditional_edges("ship", _route_after_ship,
                                {"heal": "heal", "end": END})
        g.add_edge("heal", "finish_gate")
    else:
        g.add_edge(order[-1], END)
    return g


async def run_pipeline_graph(
    output_dir: str,
    plan: dict,
    description: str,
    domain_context: dict | None = None,
    project_id: str | None = None,
) -> AsyncIterator[dict]:
    """Drive the graph and yield SSE events — the legacy relay's contract.

    thread_id = the output dir's basename (the project slug), so relaunching
    a crashed build for the same project resumes from its last completed
    phase instead of starting over.
    """
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sse_helpers import sse_event

    os.makedirs(os.path.dirname(_CHECKPOINT_DB) or ".", exist_ok=True)
    queue: asyncio.Queue = asyncio.Queue()
    thread_id = os.path.basename(str(output_dir).rstrip("/")) or "pipeline"

    state: PipelineState = {
        "output_dir": output_dir,
        "description": description,
        "plan": plan,
        "domain_context": domain_context,
        "project_id": project_id,
        "errors": [],
        "totals": {"cost_usd": 0.0, "num_turns": 0, "duration_ms": 0},
    }

    gates = _approval_gates()
    async with AsyncSqliteSaver.from_conn_string(_CHECKPOINT_DB) as saver:
        graph = build_pipeline_graph().compile(
            checkpointer=saver, interrupt_before=gates or None)
        # recursion_limit sized for the 19-node walk plus heal cycles
        # (~3 extra steps per FORGE_HEAL_ROUNDS round).
        config = {"configurable": {"thread_id": thread_id, "emit_queue": queue},
                  "recursion_limit": 40 + 5 * _max_heal_rounds()}

        # Resume semantics: if this thread has an INTERRUPTED checkpoint
        # (crash/kill mid-build → `next` is non-empty), pass None so
        # LangGraph continues from the last completed phase. A fresh build
        # or a prior COMPLETED build passes the new state and starts over.
        graph_input: Any = state
        try:
            existing = await graph.aget_state(config)
            if existing is not None and existing.next:
                graph_input = None
                queue.put_nowait(sse_event("log", {
                    "text": f"[Pipeline] resuming from checkpoint — "
                            f"next phase(s): {', '.join(existing.next)}"}))
        except Exception:  # noqa: BLE001 — unreadable checkpoint → fresh run
            pass

        halted = False

        async def _drive() -> None:
            nonlocal halted
            try:
                async for update in graph.astream(graph_input, config,
                                                  stream_mode="updates"):
                    for node_name in (update or {}):
                        queue.put_nowait(sse_event(
                            "status", {"message": f"phase complete: {node_name}"}))
            except _CoverageHalt:
                halted = True  # refusal event already emitted by bootstrap
            finally:
                queue.put_nowait(_SENTINEL)

        task = asyncio.create_task(_drive())
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
            await task  # surface any graph exception (incl. BillingError)
        finally:
            if not task.done():
                task.cancel()

        if halted:
            return

        # O2: interrupt_before pauses the graph BEFORE a gated node — the
        # stream ends with `next` non-empty. Tell the client a human
        # decision is needed; POST …/pipeline/resume continues from the
        # checkpoint (our resume semantics above handle it: same thread,
        # None input).
        if gates:
            try:
                paused = await graph.aget_state(config)
                if paused is not None and paused.next:
                    yield sse_event("approval_request", {
                        "phase": paused.next[0],
                        "thread_id": thread_id,
                        "gates": gates,
                        "message": f"Build paused before '{paused.next[0]}' — "
                                   f"approval required to continue.",
                    })
                    return
            except Exception:  # noqa: BLE001
                pass

    yield sse_event("log", {"text": "[Pipeline] LangGraph spine complete"})
