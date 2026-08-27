"""Post-generate pass: auto-wire orphan workflows to natural launcher forms.

Slice D of the Feature-Authoring Roadmap (bridge before Slice A ships).

Runs LAST in ``apply_post_generate_fixes`` — after workflow_launch_forms
has synthesized launcher forms for workflows whose plan declared a
trigger-inputs shape. This pass mops up the residual orphans that
workflow_launch_forms skipped (entity=None workflows, complex-input
workflows, non-CRUD domain workflows) by finding an existing UNWIRED
form whose fields cover the workflow's required inputs, then delegating
to :func:`services.wire_form_workflow.wire_form_to_workflow`.

Safety invariants
-----------------
- Never overwrite an existing ``Form.props.workflow`` binding. The
  candidate set is UNWIRED forms only.
- Never wire below the HIGH_CONFIDENCE threshold — a weak match may
  produce a broken submit.
- Any workflow the pass can't wire is reported in ``unresolved`` so the
  operator sees the gap (matches Slice A's "hard fail on orphan" goal
  as a bridge — for now we WARN, later we'll FAIL).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

class WirePassResult(TypedDict):
    wired:      list[dict]   # [{workflow, page_route, score}]
    unresolved: list[dict]   # [{workflow, reason, candidates?}]


# Fraction of required workflow inputs that must be sourced from a form
# before we auto-wire it. 1.0 = every required input has a form field OR
# a route param. Lower thresholds risk shipping a form that dispatches
# with missing data.
HIGH_CONFIDENCE = 1.0


# Trigger types a Form-submit dispatch can legitimately fire.
#
# "manual" family — the user clicks something. This is the obvious case:
# a manual/button/user_input trigger IS a form-submit trigger; wiring it
# to a Form is exactly the intended shape.
#
# ``api_event`` — a Form POSTing to ``/api/workflows/<name>/execute`` IS
# the api_event source. The runtime's ``triggerWorkflow(name, input)``
# is trigger-type-agnostic, so the workflow just needs an event name;
# the Form supplies the payload. Without this, workflows like
# ``ScanProductWorkflow`` (trigger.type=api_event, event=scan_submitted)
# are treated as orphans that can never be wired, leaving stateful pages
# like ``/scan`` with a Form that dispatches nothing — the "Status:
# pending — auto-refreshes forever" symptom.
#
# Deliberately EXCLUDED: ``db_change`` / ``schedule`` / ``cron`` /
# ``timer`` / ``webhook``. Those fire without a user; wiring one to a
# form would misrepresent the dispatch model. See
# ``workflow_trigger_button_guard._EVENT_TRIGGERS`` for the neutralize-
# button peer.
_ACCEPTED_TRIGGER_TYPES = frozenset({
    "", "manual", "manual_start", "manualstart", "button", "form",
    "user", "user_input", "userinput", "api_event", "apievent",
})


def _extract_trigger_type(wf: dict) -> str:
    """Pull the trigger type from a workflow doc, tolerating shape variants.

    Mirrors :func:`services.workflow_trigger_button_guard._extract_trigger_type`
    so the two peers agree on what a workflow's trigger type IS.
    """
    if not isinstance(wf, dict):
        return ""
    defn = wf.get("definition") if isinstance(wf.get("definition"), dict) else wf
    trig = defn.get("trigger") if isinstance(defn.get("trigger"), dict) else None
    if isinstance(trig, dict) and trig.get("type"):
        return str(trig["type"]).strip().lower()
    for key in ("triggerType", "trigger_type"):
        if defn.get(key):
            return str(defn[key]).strip().lower()
        if wf.get(key):
            return str(wf[key]).strip().lower()
    if isinstance(trig, str):
        return trig.strip().lower()
    return ""


def _trigger_type_accepted(trigger_type: str) -> bool:
    """True when a Form-submit dispatch can legitimately fire this trigger.

    The empty string counts as accepted (unspecified trigger — legacy
    behaviour is to treat it as manual). Anything not in
    :data:`_ACCEPTED_TRIGGER_TYPES` is rejected as event-only.
    """
    t = (trigger_type or "").strip().lower().replace("-", "_")
    if t in _ACCEPTED_TRIGGER_TYPES:
        return True
    # Also accept the canonicalized (alnum-only) form so ``api-event``,
    # ``API_EVENT`` etc all land in the accepted set.
    canon = "".join(c for c in t if c.isalnum())
    return canon in {"".join(c for c in x if c.isalnum()) for x in _ACCEPTED_TRIGGER_TYPES}


# --------------------------------------------------------------------------- #
# Public entry
# --------------------------------------------------------------------------- #

def wire_orphan_workflows(output_dir: str) -> WirePassResult:
    """Auto-wire every orphan workflow to its natural launcher form.

    Called from :func:`services.post_generate_fixes.apply_post_generate_fixes`
    as the final workflow-wiring pass. Returns a summary the caller can
    log / surface via SSE.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return {"wired": [], "unresolved": []}

    orphans = _find_orphan_workflows(str(out))
    if not orphans:
        return {"wired": [], "unresolved": []}

    unwired_forms = _index_unwired_forms(str(out))

    from services.wire_form_workflow import wire_form_to_workflow

    wired: list[dict] = []
    unresolved: list[dict] = []
    # Track which forms have been claimed during this pass so we don't
    # wire two orphans to the same form (last one would clobber).
    claimed_routes: set[str] = set()

    # Decision-ledger hooks (REL-S1) — every pick this pass makes is
    # recorded so ambiguous ones surface as chips. Import lazy so the
    # ledger is a soft dep — a broken import here must not break wiring.
    try:
        from services import decision_ledger as _dl
    except Exception:  # noqa: BLE001
        _dl = None  # type: ignore[assignment]

    for wf in orphans:
        # (REL-S1-T4) — bindings feedback loop: if a prior run recorded a
        # user-confirmed pick for this workflow, take it instead of
        # re-running the fuzzy scorer. The binding auto-invalidates if the
        # target page no longer exists (loop below checks presence).
        if _dl:
            confirmed = _dl.resolve_binding(
                str(out),
                kind=_dl.KIND_BUTTON_TARGET,
                scope=f"workflow:{wf['name']}",
                identity=wf["name"],
            )
            if confirmed:
                target_route = confirmed[len("page:"):] if confirmed.startswith("page:") else confirmed
                bound_form = next(
                    (f for f in unwired_forms
                     if f["route"] == target_route and f["route"] not in claimed_routes),
                    None,
                )
                if bound_form is not None:
                    # Bypass the fuzzy scorer — user already told us the answer.
                    fuzzy_map = _build_fuzzy_field_map(
                        bound_form.get("fields") or set(),
                        wf.get("processVariables") or [],
                    )
                    result = wire_form_to_workflow(
                        str(out),
                        page_route=bound_form["route"],
                        workflow_name=wf["name"],
                        field_map=fuzzy_map or None,
                        git=False,
                    )
                    if result.get("applied"):
                        wired.append({
                            "workflow": wf["name"],
                            "page_route": bound_form["route"],
                            "score": 1.0,  # confirmed = maximum confidence
                            "source": "binding",
                        })
                        claimed_routes.add(bound_form["route"])
                        continue
                # Binding pointed at a route that no longer exists / is already
                # claimed → fall through to normal scoring; the stale binding
                # will get overwritten by the fresh pick.

        candidates = [
            (form, _score_form_for_workflow(form, wf))
            for form in unwired_forms
            if form["route"] not in claimed_routes
        ]
        # Sort by score desc; skip zero-score noise.
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        candidates = [(f, s) for f, s in candidates if s > 0]

        if not candidates or candidates[0][1] < HIGH_CONFIDENCE:
            unresolved.append({
                "workflow": wf["name"],
                "reason":   "no_matching_form" if not candidates
                            else "below_confidence_threshold",
                "candidates": [
                    {"page_route": f["route"], "score": s}
                    for f, s in candidates[:3]
                ] if candidates else [],
            })
            # Ledger row for the unresolved-with-candidates case: the
            # user can still confirm one of the runners-up via chip.
            # Score below HIGH_CONFIDENCE → band=low, so it surfaces.
            if _dl and candidates:
                top_form, top_score = candidates[0]
                _dl.record_pick(
                    str(out),
                    kind=_dl.KIND_BUTTON_TARGET,
                    scope=f"workflow:{wf['name']}",
                    identity=wf["name"],
                    target_picked=f"page:{top_form['route']}",
                    confidence=float(top_score),
                    source_emitter="orphan_wiring_pass",
                    alternatives=[
                        _dl.make_alternative(
                            target=f"page:{f['route']}",
                            score=float(s),
                            reason="unwired form fuzzy-match candidate",
                        )
                        for f, s in candidates[1:3]
                    ],
                    reason=(
                        f"no form scored ≥{HIGH_CONFIDENCE} — top {top_score:.2f} "
                        "unresolved until user confirms"
                    ),
                )
            continue

        best_form, best_score = candidates[0]
        # Build an explicit field_map covering both identity + fuzzy
        # pairs so wire_form_to_workflow's resolver treats a
        # snake_case-vs-camelCase pairing as intentional (not an
        # accidental identity mismatch). Empty map is fine — the
        # resolver falls back to identity-name matching.
        fuzzy_map = _build_fuzzy_field_map(
            best_form.get("fields") or set(),
            wf.get("processVariables") or [],
        )
        result = wire_form_to_workflow(
            str(out),
            page_route=best_form["route"],
            workflow_name=wf["name"],
            field_map=fuzzy_map or None,
            git=False,  # post-gen pass runs inside the outer commit
        )
        if result.get("applied"):
            wired.append({
                "workflow":   wf["name"],
                "page_route": best_form["route"],
                "score":      best_score,
            })
            claimed_routes.add(best_form["route"])
            # Ledger row for successful wire — records the pick AND every
            # runner-up we saw. High confidence (score ≥ HIGH_CONFIDENCE
            # = 1.0) means the chip UI keeps this silent; we still write
            # it so audits can see the full picture per generation.
            if _dl:
                _dl.record_pick(
                    str(out),
                    kind=_dl.KIND_BUTTON_TARGET,
                    scope=f"workflow:{wf['name']}",
                    identity=wf["name"],
                    target_picked=f"page:{best_form['route']}",
                    confidence=float(best_score),
                    source_emitter="orphan_wiring_pass",
                    alternatives=[
                        _dl.make_alternative(
                            target=f"page:{f['route']}",
                            score=float(s),
                            reason="fuzzy runner-up",
                        )
                        for f, s in candidates[1:3]
                    ],
                    reason=f"fuzzy match score {best_score:.2f}",
                )
        else:
            unresolved.append({
                "workflow": wf["name"],
                "reason":   f"wire_seam_failed:{result.get('error')}",
                "candidates": [{
                    "page_route": best_form["route"], "score": best_score,
                }],
            })

    logger.info(
        "[orphan-wiring] pass complete — wired=%d, unresolved=%d, in %s",
        len(wired), len(unresolved), out,
    )
    return {"wired": wired, "unresolved": unresolved}


# --------------------------------------------------------------------------- #
# Helpers — orphan detection
# --------------------------------------------------------------------------- #

def _find_orphan_workflows(output_dir: str) -> list[dict]:
    """Every workflow file whose name is NOT the target of any
    ``Form.props.workflow`` on any page schema.

    Returns each orphan as ``{name, path, processVariables}`` so the
    matcher can score without re-reading."""
    out = Path(output_dir)
    wf_dir = out / "workflows"
    if not wf_dir.is_dir():
        return []

    # Collect every wired workflow name from Form.props.workflow across
    # all page schemas.
    wired_names: set[str] = set()
    schemas_dir = out / "src" / "schemas"
    if schemas_dir.is_dir():
        for sp in schemas_dir.rglob("*.json"):
            try:
                doc = json.loads(sp.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            for wf_name in _all_form_workflow_props(doc):
                wired_names.add(wf_name)
                wired_names.add(wf_name.lower())
                wired_names.add(wf_name.upper())

    orphans: list[dict] = []
    for wf_path in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = wf.get("name") or wf_path.stem
        if not isinstance(name, str):
            continue
        # Case-insensitive orphan check — wired_names includes lower/upper
        # variants so "parsecvworkflow.json" with name "ParseCVWorkflow"
        # matches Form.props.workflow="ParseCVWorkflow".
        if name in wired_names or name.lower() in wired_names:
            continue
        # Trigger-type gate. Only form-dispatchable workflows are eligible
        # orphans — a workflow whose trigger is ``db_change`` / ``schedule``
        # / ``timer`` / ``webhook`` runs autonomously and MUST NOT be
        # wired to a form-submit. ``api_event`` (new — VPS-M) is a valid
        # form target: the Form's POST /api/workflows/<name>/execute IS
        # the event source, so a workflow whose trigger.type=api_event
        # (e.g. ScanProductWorkflow, event=scan_submitted) now gets
        # picked up here instead of being silently left an orphan.
        trigger_type = _extract_trigger_type(wf)
        if not _trigger_type_accepted(trigger_type):
            logger.debug(
                "[orphan-wiring] skipping event-only workflow %s (trigger=%r) — "
                "form-submit is not a valid dispatch source for this trigger.",
                name, trigger_type,
            )
            continue
        orphans.append({
            "name": name,
            "path": str(wf_path.relative_to(out)),
            "processVariables": wf.get("processVariables") or [],
        })
    return orphans


def _all_form_workflow_props(node: Any) -> list[str]:
    """Collect ``Form.props.workflow`` values (recursive walk)."""
    out: list[str] = []
    if isinstance(node, dict):
        c = node.get("component") or node.get("type") or ""
        if c == "Form":
            wf = (node.get("props") or {}).get("workflow")
            if isinstance(wf, str) and wf.strip():
                out.append(wf.strip())
        for v in node.values():
            if isinstance(v, (dict, list)):
                out.extend(_all_form_workflow_props(v))
    elif isinstance(node, list):
        for item in node:
            out.extend(_all_form_workflow_props(item))
    return out


# --------------------------------------------------------------------------- #
# Helpers — unwired form index
# --------------------------------------------------------------------------- #

_FIELD_COMPONENTS = frozenset({
    "Input", "Textarea", "Select", "Checkbox", "Switch", "RadioGroup",
    "DatePicker", "TimePicker", "FileUpload", "NumberInput", "Slider",
    "Combobox", "MaskedInput", "Rating", "InputOTP", "ColorPicker",
    "RichTextEditor", "KeyValueInput", "Cascader", "Transfer", "Tree",
})


def _index_unwired_forms(output_dir: str) -> list[dict]:
    """Every page schema that contains a Form with NO ``props.workflow``
    already set. Returns ``[{route, fields}]`` — fields is the set of
    named field-component ``props.name`` values inside the Form.

    Deliberately excludes wired forms so the orphan matcher never picks
    a form that's already claimed by another workflow."""
    out = Path(output_dir)
    schemas_dir = out / "src" / "schemas"
    if not schemas_dir.is_dir():
        return []
    unwired: list[dict] = []
    for sp in sorted(schemas_dir.rglob("*.json")):
        if sp.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            doc = json.loads(sp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        form_node = _find_first_form(doc.get("root"))
        if form_node is None:
            continue
        props = form_node.get("props") or {}
        if isinstance(props, dict) and props.get("workflow"):
            continue  # already wired — off-limits
        fields = _collect_form_field_names(form_node)
        if not fields:
            continue
        unwired.append({
            "route": doc.get("route") or "",
            "fields": fields,
        })
    return unwired


def _find_first_form(node: Any) -> dict | None:
    if isinstance(node, dict):
        c = node.get("component") or node.get("type") or ""
        if c == "Form":
            return node
        for v in node.values():
            if isinstance(v, (dict, list)):
                found = _find_first_form(v)
                if found is not None:
                    return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first_form(item)
            if found is not None:
                return found
    return None


def _collect_form_field_names(form_node: dict) -> set[str]:
    out: set[str] = set()

    def walk(n: Any) -> None:
        if isinstance(n, dict):
            c = n.get("component") or n.get("type") or ""
            if c in _FIELD_COMPONENTS:
                name = (n.get("props") or {}).get("name")
                if isinstance(name, str) and name:
                    out.add(name)
            for v in n.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    for v in form_node.values():
        if isinstance(v, (dict, list)):
            walk(v)
    return out


# --------------------------------------------------------------------------- #
# Helpers — scoring
# --------------------------------------------------------------------------- #

def _canonicalize_field_name(name: object) -> str:
    """Canonical form for fuzzy name matching.

    Folds ``firstName`` / ``first_name`` / ``first-name`` / ``FIRST_NAME``
    / ``first name`` into the same key by lowercasing and stripping
    every non-alphanumeric character. Non-string / empty inputs return
    ``""`` — callers filter those out.

    The LLM often emits form fields in ``snake_case`` while emitting the
    same conceptual workflow inputs in ``camelCase``. Without a
    canonicalizer, orphan_wiring_pass sees them as different names and
    leaves the wiring undone. With one, the pipeline auto-pairs them
    and emits an explicit ``field_map`` so the mirror captures the
    non-identity mapping.
    """
    if not isinstance(name, str) or not name:
        return ""
    return "".join(c.lower() for c in name if c.isalnum())


def _build_fuzzy_field_map(
    form_fields: set[str] | list[str],
    workflow_inputs: list[dict],
) -> dict[str, str]:
    """Pair each form field with a workflow input whose canonical name
    matches. Returns ``{form_field: workflow_input}`` — identity pairs
    included so callers can pass one field_map covering both fuzzy and
    exact matches.

    Deterministic: when two workflow inputs canonicalize the same, the
    first one in the list wins. Downstream sees the same result on
    every run.
    """
    if not isinstance(workflow_inputs, list):
        return {}
    canon_to_input: dict[str, str] = {}
    for inp in workflow_inputs:
        if not isinstance(inp, dict):
            continue
        n = inp.get("name")
        c = _canonicalize_field_name(n)
        if not c or c in canon_to_input:
            continue
        canon_to_input[c] = str(n)

    out: dict[str, str] = {}
    for ff in form_fields:
        c = _canonicalize_field_name(ff)
        if not c:
            continue
        target = canon_to_input.get(c)
        if target:
            out[str(ff)] = target
    return out


def _score_form_for_workflow(form: dict, workflow: dict) -> float:
    """Fraction of the workflow's REQUIRED inputs the form can source.

    Numerator: required inputs whose canonicalized name matches a
    canonicalized form field OR a route param on the form's page.
    Denominator: total required inputs (0.0 when the workflow has none —
    a workflow with no inputs is trivially matched by any form).
    """
    inputs = workflow.get("processVariables") or []
    if not isinstance(inputs, list) or not inputs:
        # No inputs = 1.0 iff form has any fields (still a plausible
        # launcher); 0.0 otherwise so we don't wire empty forms.
        return 1.0 if form.get("fields") else 0.0
    required = [i for i in inputs
                if isinstance(i, dict) and i.get("required") and i.get("name")]
    if not required:
        return 1.0 if form.get("fields") else 0.0
    form_fields = form.get("fields") or set()
    route = form.get("route") or ""
    # Route params satisfy source=route inputs of the same name.
    import re
    route_params = {m.group(1) or m.group(2)
                    for m in re.finditer(r"\[([^\]]+)\]|:([a-zA-Z_][a-zA-Z0-9_]*)", route)}
    # Canonicalized sets for fuzzy comparison.
    canon_form = {_canonicalize_field_name(f) for f in form_fields}
    canon_form.discard("")
    canon_route = {_canonicalize_field_name(p) for p in route_params}
    canon_route.discard("")
    covered = 0
    for inp in required:
        name = inp["name"]
        c = _canonicalize_field_name(name)
        if not c:
            continue
        if c in canon_form or c in canon_route:
            covered += 1
    return covered / len(required)
