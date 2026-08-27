"""LLM-driven page-schema editor — the replacement for JSON-Patch edit_page.

Why this exists (see checkpoint 'dday'): the old edit_page emitted a
JSON-Patch that a deterministic ``apply_semantic_field_types`` pass would
then overrule — e.g. any FK-named column got forced back to Select even
when the user explicitly asked for FileUpload. That "authority" was
appropriate for first-pass generation (an untrusted LLM produced the
whole thing); it's wrong for user-directed edits (the user's intent IS
the authority).

Contract:
  smart_edit_page(*, output_dir, target_path, intent, query_fn=None) → dict

  Loads the current page schema, the app-map skeleton, and the component
  registry, then calls one LLM turn asking for a complete new schema.
  Validates structurally (JSON parses, has a ``root``, every component
  type exists in the registry). Writes atomically. Does NOT run the
  post-generate opinion guards. Returns::

      {applied: bool, edited_paths: [str], diff_summary: str,
       reason: str (when applied=False), model: str}

Inputs the LLM sees, in order:
  1. The user's intent verbatim ("make CV Upload a FileUpload").
  2. The current page schema on disk (so it produces a coherent DIFF).
  3. The app-map skeleton (entities, routes, workflows — for context).
  4. The full component-contracts registry (so it can pick real
     components and set real props).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


QueryFn = Callable[[str, str], str]
"""LLM boundary — (system_prompt, user_prompt) → assistant text (JSON).

Tests inject a canned fn; prod supplies a real Anthropic Messages call.
Kept dead simple: one-shot, no tool use, output must be a JSON blob."""


_REGISTRY_CONTRACTS_PATH = (
    Path(__file__).resolve().parents[2]
    / "packages" / "registry" / "dist" / "component-contracts.json"
)

# Renderer built-ins — layout primitives + a couple of bare typography
# nodes. These are valid ``type`` values that don't appear in the
# component-contracts.json because they live in the runtime shell, not
# the library. Same list ``schema_prompt._registered_components`` adds
# on top of the registry.
_RENDERER_PRIMITIVES = frozenset({
    "Box", "Text", "Image", "Container", "Row", "Stack", "Grid", "Spacer",
    # Schema structural / control-flow nodes — defined in packages/schema,
    # not the library contracts (which only carry visual components). Any
    # page with a list (Repeat) or branch (Conditional) was rejected
    # wholesale as "unknown component type" without these.
    "Repeat", "Conditional", "DataBoundary", "Slot", "PageOutlet",
    "OverlayCard", "Custom",
})


def smart_edit_page(
    *,
    output_dir: str,
    target_path: str,
    intent: str,
    query_fn: Optional[QueryFn] = None,
) -> dict:
    """Edit ``target_path`` under ``output_dir`` per ``intent``.

    See the module docstring for the design contract. This function is
    the single entry point Smith's ``edit_page`` tool calls."""
    root = Path(output_dir)
    schema_file = root / target_path
    if not schema_file.exists():
        return _fail(f"target page not found: {target_path!r}", model=None)

    if not callable(query_fn):
        return _fail("no LLM boundary wired (query_fn=None)", model=None)

    try:
        current_schema = json.loads(schema_file.read_text())
    except Exception as exc:  # noqa: BLE001
        return _fail(f"target page has invalid JSON: {exc}", model=None)

    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        intent=intent,
        target_path=target_path,
        current_schema=current_schema,
        output_dir=str(root),
    )

    try:
        raw = query_fn(system_prompt, user_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm_edit: query_fn crashed")
        return _fail(f"LLM boundary crashed: {type(exc).__name__}: {exc}",
                     model=None)

    parsed = _parse_json(raw)
    if parsed is None:
        return _fail("LLM output was not valid JSON", model=None)

    # Rewrite common LLM-shorthand types the registry rejects (``email``,
    # ``phone``, ``password``, ``date``, …) into their real component form
    # BEFORE validation. Without this the LLM would loop retrying the same
    # invented type — which is exactly what happened on the Add Candidate
    # form: 3 identical `edit_page` failures on ``"unknown component type:
    # 'email'"`` before Smith fell out to the canned "couldn't pin that
    # down" reply. Cheap deterministic hop, saves the round-trip.
    _remap_shorthand_types(parsed)

    reason = _structural_validation_error(parsed)
    if reason:
        return _fail(reason, model=None)

    # No-op detection. If the LLM returned an object structurally identical
    # to the current schema, no field was actually removed/added/changed —
    # even though the call didn't error. Without this, Smith reads
    # ``applied: True`` and reports "Done! I removed X" to the user when in
    # reality X is still on the page. (Reported as B-015: tester asks to
    # remove Department + Role; Smith says "removed" but the fields remain.)
    if parsed == current_schema:
        return {
            "applied": False,
            "reason": (
                "the requested change produced no diff — the intent may not "
                "match this page (wrong path?), or the LLM couldn't identify "
                "what to change. Do NOT tell the user the change was made."
            ),
            "edited_paths": [],
            "diff_summary": {"unchanged": True},
            "model": "canned" if query_fn.__name__ == "_stub" else "anthropic",
        }

    # Atomic write — same-file replace via a temp file so a crashed
    # process can't leave a half-written schema on disk.
    tmp = schema_file.with_suffix(schema_file.suffix + ".tmp")
    tmp.write_text(json.dumps(parsed, indent=2))
    os.replace(tmp, schema_file)

    # Concrete change-list — Smith's answer terminal reads this to know
    # what CAN be claimed. Bare-metal truth: only entries that appear
    # here actually exist in the new file. Anything Smith describes
    # beyond this list is fabrication.
    changes = compute_change_list(current_schema, parsed)

    return {
        "applied": True,
        "edited_paths": [target_path],
        "diff_summary": _diff_summary(current_schema, parsed),
        "changes": changes,
        "changes_summary": summarize_change_list(changes),
        "model": "canned" if query_fn.__name__ == "_stub" else "anthropic",
    }


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

def _build_system_prompt() -> str:
    """Static — cached by the model. Rules the LLM must follow every turn."""
    return (
        "You are a page-schema surgeon for a UI runtime.\n\n"
        "You receive the user's INTENT, the CURRENT page schema, the APP "
        "MAP (entities/pages/workflows for context), and the COMPONENT "
        "REGISTRY (every component's prop schema).\n\n"
        "Output ONE JSON object: the complete NEW schema for this page.\n"
        "Do not output prose. Do not output markdown fences. Do not "
        "output a diff or a JSON-Patch. Output the FULL new schema, "
        "top-level fields intact ({schemaVersion, id, route, layout, "
        "root, ...}), so the runtime can load it verbatim.\n\n"
        "Hard rules:\n"
        "  • Every component's ``type`` MUST exist in the COMPONENT "
        "REGISTRY. If a component type isn't in the registry, do not "
        "use it — pick the closest registered equivalent.\n"
        "  • Preserve unrelated top-level fields (id, route, layout, "
        "schemaVersion). Only modify what the INTENT asks for.\n"
        "  • If the intent is ambiguous, apply the most conservative "
        "reading and mention no ambiguity in the output (there is no "
        "prose channel).\n\n"
        "CONTROL-TYPE PRIORITY — user words beat semantic inference.\n"
        "When the INTENT explicitly names a component type (e.g. "
        "'change X to FileUpload', 'make Y a Combobox'), you MUST use "
        "that exact type in your output. Do NOT substitute a "
        "semantically-inferred alternative just because it seems more "
        "'correct' — the user knows the domain and downstream "
        "concerns (like workflow input shapes) will be handled by "
        "coordinated edits outside your scope. Trust the user's words.\n\n"
        "EXAMPLE — do this:\n"
        "  Intent: 'Change the cvUploadId field from a Select to a FileUpload'\n"
        "  Current node: {\"type\":\"Select\", \"props\":{\"name\":\"cvUploadId\", "
        "\"optionsFrom\":{\"source\":\"cvUploads\",\"value\":\"id\",\"label\":\"id\"}}}\n"
        "  CORRECT output: {\"type\":\"FileUpload\", \"props\":{\"name\":\"cvUploadId\", "
        "\"label\":\"CV Upload\", \"accept\":\".pdf,.doc,.docx\", \"validators\":{\"required\":true}}}\n"
        "  WRONG output: preserving the Select because 'FileUpload can't "
        "produce a uuid the workflow expects'. That workflow-side change "
        "is not your problem — emit exactly what the user asked for.\n"
    )


def _build_user_prompt(
    *,
    intent: str,
    target_path: str,
    current_schema: dict,
    output_dir: str,
) -> str:
    """Bundle the four inputs into one message. Order matters: intent
    first (so the model latches on to the task), then current schema,
    then app-map, then registry (biggest block, model reads it last)."""
    parts: list[str] = []
    parts.append(f"## USER INTENT\n{intent}\n")
    parts.append(f"## TARGET PAGE\npath: {target_path}\n")

    parts.append(
        "## CURRENT SCHEMA (edit this — output the complete NEW version)\n"
        + "```json\n"
        + json.dumps(current_schema, indent=2)
        + "\n```\n"
    )

    app_map_block = _app_map_block(output_dir)
    if app_map_block:
        parts.append("## APP MAP (for context)\n" + app_map_block + "\n")

    registry_block = _component_registry_block()
    if registry_block:
        parts.append(
            "## COMPONENT REGISTRY (only these components exist — pick from these)\n"
            + registry_block + "\n"
        )

    coord = _coordination_note(intent, current_schema)
    if coord:
        parts.append(coord)

    stateful = _stateful_single_page_note(intent, current_schema)
    if stateful:
        parts.append(stateful)

    parts.append(
        "Now output the complete NEW schema as a single JSON object. "
        "No prose, no fences."
    )
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Coordination-note detection
# --------------------------------------------------------------------------- #

# Controls that produce a raw value (URL, file, text) rather than a foreign-key
# uuid. Naming any of these in the intent, when the target page has FK-valued
# fields (Select with optionsFrom), triggers the coordination note.
_NON_FK_CONTROLS = (
    "FileUpload", "CameraCapture", "Scanner", "Signature",
    "AudioRecorder", "Combobox", "InputOTP", "Rating", "ColorPicker",
    "RichTextEditor", "QRCode",
)


def _coordination_note(intent: str, current_schema: dict) -> str:
    """Return a coordination-note block for the LLM prompt when the intent
    is asking to switch an FK-valued field to a non-FK control (e.g. the
    ``cvUploadId → FileUpload`` pattern). Empty string when not applicable.

    The block tells the LLM: 'yes I know a FileUpload doesn't produce a
    uuid the workflow expects — that workflow-side change is out of your
    scope. Emit the FileUpload anyway.' Without this note the LLM
    conservatively preserves the Select and reports success."""
    controls_named = [c for c in _NON_FK_CONTROLS if c.lower() in intent.lower()]
    if not controls_named:
        return ""

    fk_fields = _collect_fk_fields(current_schema.get("root"))
    if not fk_fields:
        return ""

    workflow = _find_form_workflow(current_schema.get("root"))

    lines: list[str] = [
        "## COORDINATION NOTE (system-detected: FK ↔ non-FK control change)",
        "",
        (
            "The intent names one of "
            f"[{', '.join(controls_named)}] — controls that produce a "
            "raw value (URL, file, text, etc.), not a foreign-key uuid."
        ),
        "",
        "This page has FK-valued fields (rendered today as Select with "
        "``optionsFrom``):",
    ]
    for f in fk_fields:
        lines.append(
            f"  • name={f['name']!r}  current type={f['current_type']!r}  "
            f"FK source={f['source']!r}"
        )

    if workflow:
        lines.append("")
        lines.append(
            f"The page's Form submits to workflow ``{workflow}``, which "
            "currently expects the FK field(s) above to carry an id."
        )

    lines.append("")
    lines.append(
        "IF the intent asks to change one of these FK fields to the "
        "non-FK control it names: do it. Emit the requested control. "
        "The workflow layer will be updated separately to accept the "
        "new value shape (e.g. by creating the referenced record from "
        "the uploaded file first and passing the returned id "
        "downstream). That coordinated workflow change is out of your "
        "scope — do NOT preserve the Select because 'the workflow "
        "expects an id'. Trust the user's words; the platform handles "
        "the coordination."
    )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Stateful single-page detection — user asks Smith to keep results inline
# --------------------------------------------------------------------------- #

# Phrases that signal "one page, multiple states, no navigation". The user's
# scan-and-compare mockup would typically be described with one of these.
# Case-insensitive substring match. Ordered rough-descending by specificity.
_STATEFUL_SINGLE_PAGE_INTENTS = (
    "single-page flow",
    "single page flow",
    "stay on the same page",
    "stay on this page",
    "stay on the page",
    "stay on the scan",
    "stay on the current page",
    "stay on the",  # widest — catches "stay on the results page", etc.
    "keep it on the same page",
    "keep the results on the same page",
    "show the results inline",
    "show results inline",
    "show results here",
    "show the progress inline",
    "show progress inline",
    "one page with",
    "one page not multiple",
    "show a loading state",
    "show a spinner",
    "show a scanning state",
    "show the scanning",
    "poll",
    "auto-refresh",
    "auto refresh",
    "no navigation",
    "don't navigate",
    "do not navigate",
    "same route",
    "conditional",  # user names the primitive directly
    "state machine",
)


def _stateful_single_page_note(intent: str, current_schema: dict) -> str:
    """Emit a coordination note when the intent implies the stateful
    single-page pattern (Conditional root + top-level poll).

    Empty string when the intent doesn't match, OR when the page already
    uses the pattern (no need to prescribe what's already in place).

    The block references the canonical example schema at
    ``backend/services/schema_examples/stateful_scan_page.json`` and the
    contract at ``docs/superpowers/patterns/stateful-single-page.md`` so
    the LLM can copy the exact shape.
    """
    lower = intent.lower()
    matched = [p for p in _STATEFUL_SINGLE_PAGE_INTENTS if p in lower]
    if not matched:
        return ""

    # Skip when the schema already IS a stateful single-page (has top-level
    # `poll` and a Conditional root) — Smith should refine, not re-prescribe.
    if isinstance(current_schema.get("poll"), dict):
        root_type = str((current_schema.get("root") or {}).get("type") or "").lower()
        if root_type == "conditional":
            return ""

    lines: list[str] = [
        "## COORDINATION NOTE (system-detected: stateful single-page pattern)",
        "",
        (
            "The intent contains phrasing that signals a stateful single-page "
            "flow — the user wants ONE route rendering DIFFERENT content based "
            "on a live entity's status, no navigation between states. Detected "
            f"phrases: {matched[:3]}."
        ),
        "",
        "The runtime supports this pattern directly. The correct shape:",
        "",
        "1. Add a top-level `poll` block to the page schema:",
        "   ```json",
        '   "poll": {',
        '     "interval": 2500,',
        '     "stopWhen": "scan.status IN (\'completed\',\'failed\')"',
        "   }",
        "   ```",
        "   The runtime\'s AutoRefresh wrapper reads this and re-runs the RSC",
        "   path every `interval` ms, stopping when `stopWhen` evaluates true.",
        "",
        "2. Replace the current root with a `Conditional` node whose branches",
        "   are the states the workflow transitions through. Typical shape:",
        "   ```json",
        '   {"type": "Conditional", "branches": [',
        '     {"if": "!scan",                       "node": /* initial form */},',
        '     {"if": "scan.status === \'processing\'", "node": /* Progress + Spinner */},',
        '     {"if": "scan.status === \'completed\'",  "node": /* results */},',
        '     {"if": "scan.status === \'failed\'",     "node": /* error banner */}',
        "   ]}",
        "   ```",
        "",
        "3. Ensure the page has a dataSource for the polled entity. If not",
        "   present, add one — typically `{name: \"scan\", entity: \"Scan\", ",
        "   op: \"latestForUser\"}` to fetch the caller's most recent record.",
        "",
        "SUPPORTED `stopWhen` GRAMMAR (client-side evaluator — nothing else):",
        "  • strict/loose equality:  `scan.status === 'completed'`",
        "  • IN list:                `scan.status IN ('completed','failed')`",
        "  • IS (NOT) NULL:          `scan.result IS NOT NULL`",
        "  • negation:               `!scan`",
        "",
        "CANONICAL REFERENCE (copy this shape verbatim, adapt the entity name):",
        "  backend/services/schema_examples/stateful_scan_page.json",
        "",
        "FULL CONTRACT:",
        "  docs/superpowers/patterns/stateful-single-page.md",
        "",
        "DO NOT: create a separate route for each state. DO NOT: keep the",
        "existing button-navigates-to-another-page structure. The whole point",
        "is that navigation goes away.",
    ]
    return "\n".join(lines)


def _collect_fk_fields(node: Any) -> list[dict]:
    """Walk the schema, return every field node whose props carry an
    ``optionsFrom`` — the shape of an FK dropdown."""
    out: list[dict] = []
    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            p = n.get("props") or {}
            of = p.get("optionsFrom")
            if isinstance(of, dict) and of.get("source"):
                out.append({
                    "name":         p.get("name") or "?",
                    "current_type": n.get("type") or "?",
                    "source":       of.get("source"),
                })
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)
    _walk(node)
    return out


def _find_form_workflow(node: Any) -> str | None:
    """First ``Form`` node's ``props.workflow`` — the form's submit target."""
    result: list[str] = []
    def _walk(n: Any) -> None:
        if result:
            return
        if isinstance(n, dict):
            if n.get("type") == "Form":
                w = (n.get("props") or {}).get("workflow")
                if isinstance(w, str) and w:
                    result.append(w)
                    return
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)
    _walk(node)
    return result[0] if result else None


def _app_map_block(output_dir: str) -> str:
    """Reuse the AM-4 skeleton — no dedicated fetch."""
    try:
        from services.app_map import get_app_map
        from services.app_map_render import render_app_map_skeleton
        return render_app_map_skeleton(get_app_map(output_dir))
    except Exception:  # noqa: BLE001
        logger.exception("llm_edit: could not build app-map for prompt")
        return ""


def _component_registry_block() -> str:
    """Load the compiled component-contracts.json — 98 components, ~48 KB.

    The LLM sees the raw JSON. That's expensive (~12 KTok) but prompt
    caching amortizes it, and giving the LLM the FULL prop schema is the
    only way to avoid it inventing props that don't exist."""
    try:
        return _REGISTRY_CONTRACTS_PATH.read_text()
    except Exception:  # noqa: BLE001
        logger.exception("llm_edit: registry contracts missing at %s",
                         _REGISTRY_CONTRACTS_PATH)
        return ""


# --------------------------------------------------------------------------- #
# Response parsing + validation
# --------------------------------------------------------------------------- #

def _parse_json(raw: str) -> Optional[dict]:
    """Extract a JSON object from the LLM's response.

    Tolerates a leading/trailing markdown fence in case the model ignores
    the 'no fences' rule — the applier is the last mile so it should be
    a bit forgiving."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    txt = raw.strip()
    if txt.startswith("```"):
        # Strip a ```json ... ``` fence.
        txt = txt.split("\n", 1)[-1]
        if txt.endswith("```"):
            txt = txt[: -3]
        txt = txt.strip()
    try:
        obj = json.loads(txt)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


_SHORTHAND_TYPE_REMAP: dict[str, tuple[str, dict]] = {
    # LLM shortcuts that map cleanly to a real component + extra props.
    # Case-insensitive lookup; only fires when the shorthand isn't itself
    # a real component name (we don't want to reroute a legit ``Input`` node).
    "email":    ("Input",       {"type": "email"}),
    "phone":    ("Input",       {"type": "tel"}),
    "tel":      ("Input",       {"type": "tel"}),
    "url":      ("Input",       {"type": "url"}),
    "password": ("Input",       {"type": "password"}),
    "number":   ("NumberInput", {}),
    "int":      ("NumberInput", {}),
    "integer":  ("NumberInput", {}),
    "date":     ("DatePicker",  {}),
    "datetime": ("DatePicker",  {}),
    "boolean":  ("Switch",      {}),
    "bool":     ("Switch",      {}),
    "checkbox": ("Switch",      {}),
    "toggle":   ("Switch",      {}),
    "file":     ("FileUpload",  {}),
    "upload":   ("FileUpload",  {}),
    # capitalization variants a lower-case-only match would miss are handled
    # by the lower() lookup in _remap_shorthand_types.
}


def _remap_shorthand_types(schema: Any) -> None:
    """Walk the schema in place and rewrite shorthand component types like
    ``"email"`` or ``"date"`` into their real form (``Input`` + ``{type:
    email}`` / ``DatePicker``). LLMs consistently invent these — without
    the remap they hit the registry validator and Smith retries the same
    wrong output until the iteration cap forces a canned fallback."""
    registry = _load_registry_names()

    def _walk(node: Any) -> None:
        # Only descend through known schema-tree fields (``root``, ``children``).
        # We do NOT recurse into ``props`` — a component's props may contain
        # a legitimate ``type`` (e.g. an Input's HTML type=email) that would
        # look like another component node and get re-remapped forever.
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, str) and t not in registry:
                hit = _SHORTHAND_TYPE_REMAP.get(t.lower())
                if hit:
                    real, extra = hit
                    node["type"] = real
                    if extra:
                        props = node.setdefault("props", {})
                        if isinstance(props, dict):
                            for k, v in extra.items():
                                props.setdefault(k, v)
            for key in ("root", "children"):
                v = node.get(key)
                if v is not None:
                    _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(schema)


def _structural_validation_error(schema: dict) -> str:
    """Return a human-readable reason if the schema isn't structurally
    valid, else empty string. This is DELIBERATELY narrow: JSON parses,
    has a ``root``, every component type exists in the registry. No
    semantic 'authority' checks — those are what the LLM is authoritative
    over now.

    Error messages are PRESCRIPTIVE: they say what the LLM should do,
    not just what's wrong. A bare "unknown component type" left Smith
    retrying the same invented name; adding a "did you mean X?"
    fuzzy-match suggestion lets the LLM self-heal on the next call."""
    if "root" not in schema:
        return (
            "response missing top-level 'root' key. Return the ENTIRE "
            "page schema shaped as {schemaVersion, id, route, title, "
            "root: {...}} — the root is the component tree."
        )

    registry = _load_registry_names()
    unknowns: list[str] = []
    _walk_types(schema.get("root"), registry, unknowns)
    if unknowns:
        first = unknowns[0]
        return _unknown_type_hint(first, registry)

    return ""


def _unknown_type_hint(unknown: str, registry: set[str]) -> str:
    """Prescriptive error for an invented component type — includes the
    closest registered names and, when the unknown is a common HTML-input
    shorthand, the exact real-form recipe (e.g. ``Input`` + ``props.type
    = 'email'``). The LLM should never have to guess twice."""
    hint_bits: list[str] = [f"unknown component type: {unknown!r} (not in the component registry)"]

    # A common shorthand slipped past the remap somehow — spell out the fix.
    hit = _SHORTHAND_TYPE_REMAP.get(unknown.lower())
    if hit:
        real, extra = hit
        if extra:
            extras_str = ", ".join(f"{k}={v!r}" for k, v in extra.items())
            hint_bits.append(
                f"Use {real!r} with props.{extras_str} instead of a bare "
                f"{unknown!r} component."
            )
        else:
            hint_bits.append(f"Use {real!r} instead of a bare {unknown!r} component.")
        return " ".join(hint_bits)

    # Fuzzy match against the registry — three closest names.
    import difflib
    close = difflib.get_close_matches(unknown, sorted(registry), n=3, cutoff=0.55)
    if close:
        hint_bits.append(
            f"Did you mean {', '.join(repr(c) for c in close)}? "
            f"Use one of those component names verbatim."
        )
    else:
        # Nothing close — surface a hand-picked slice so the LLM can
        # pick something rather than reinvent.
        common = [c for c in ("Input", "Select", "Textarea", "Button",
                              "Form", "Card", "Stack", "Row", "Grid",
                              "Table", "Chart") if c in registry][:8]
        if common:
            hint_bits.append(
                f"Common components available: {', '.join(common)}. "
                f"Only names in the component registry render."
            )
    return " ".join(hint_bits)


def _load_registry_names() -> set[str]:
    """Names the runtime will accept: registered library components +
    renderer built-in layout primitives."""
    names: set[str] = set(_RENDERER_PRIMITIVES)
    try:
        d = json.loads(_REGISTRY_CONTRACTS_PATH.read_text())
        if isinstance(d, dict):
            names |= set(d.keys())
    except Exception:  # noqa: BLE001
        pass
    return names


def _walk_types(node: Any, registry: set[str], out: list[str]) -> None:
    # Only descend through schema-tree fields (``root``, ``children``) — a
    # component's props may legitimately carry a ``type`` (e.g. Input's
    # HTML ``type="email"``) that would otherwise be misread as an unknown
    # component and reject the whole write.
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and registry and t not in registry:
            out.append(t)
        for key in ("root", "children"):
            v = node.get(key)
            if v is not None:
                _walk_types(v, registry, out)
    elif isinstance(node, list):
        for v in node:
            _walk_types(v, registry, out)


# --------------------------------------------------------------------------- #
# Result helpers
# --------------------------------------------------------------------------- #

def _fail(reason: str, *, model: Optional[str]) -> dict:
    return {
        "applied":      False,
        "edited_paths": [],
        "reason":       reason,
        "model":        model,
    }


def _diff_summary(pre: dict, post: dict) -> str:
    """Cheap human-readable summary — not a diff, just a count of nodes
    with a note about what changed. Enough for a chat bubble; not for
    a code review."""
    def _node_count(n) -> int:
        if isinstance(n, dict):
            k = 1 if "type" in n else 0
            return k + sum(_node_count(v) for v in n.values())
        if isinstance(n, list):
            return sum(_node_count(v) for v in n)
        return 0
    return (
        f"nodes: {_node_count(pre)} → {_node_count(post)}"
    )


# --------------------------------------------------------------------------- #
# Concrete change-list                                                         #
# --------------------------------------------------------------------------- #
# The whole-schema replace path returns ``applied: True`` on ANY diff, which
# leaves Smith free to compose a "Done! I fixed 1, 2, 3, 4, 5" reply even
# when only 2 of the 5 claimed edits actually appear in the new schema
# (fabrication seen live on the recruitment app). ``compute_change_list``
# turns the pre/post schemas into a structured list of concrete facts —
# nothing invented, only what the diff proves. Smith's answer terminal
# then rejects claims that exceed this list.


# JSON pointer-ish path segments used in the change-list ``at`` field.
# Kept as simple strings so the LLM can pattern-match them without a
# custom parser — e.g. "root.children[0].props.content".
def _path_join(parent: str, key) -> str:
    if isinstance(key, int):
        return f"{parent}[{key}]"
    if not parent:
        return str(key)
    return f"{parent}.{key}"


# Text-shaped prop keys the layman cares about. When one of these
# changes, we emit a "text-changed" entry instead of a generic replace,
# so Smith's summary reads naturally.
_TEXT_PROP_KEYS = frozenset({
    "content", "title", "label", "heading", "text", "placeholder",
    "helperText", "description", "buttonLabel", "submitLabel",
    "navigate", "name", "route",
})


def compute_change_list(pre, post, path: str = "") -> list[dict]:
    """Walk pre/post JSON in lockstep, emit a flat list of concrete
    change facts.

    Change shapes (``kind`` is required, other keys vary):
      • ``{"kind": "text-changed", "at": <path>, "from": <str>, "to": <str>}``
        — a text-shaped prop swapped values. Human-readable summary.
      • ``{"kind": "added", "at": <path>, "value": <json>}`` — a new
        key/value or new list element that didn't exist before.
      • ``{"kind": "removed", "at": <path>, "value": <json>}`` — a key
        or list element that no longer exists.
      • ``{"kind": "value-changed", "at": <path>, "from": <json>,
        "to": <json>}`` — non-text scalar or shape change.

    Total entry count is capped at 60 to keep the tool return compact
    for the LLM. If a huge structural rewrite happens, we return a
    truncated list with a final ``{"kind": "truncated", ...}`` marker so
    Smith knows not to enumerate every change.
    """
    out: list[dict] = []
    _MAX = 60

    def _walk(a, b, at: str) -> None:
        if len(out) >= _MAX:
            return
        # Same type or both none — recurse
        if type(a) is type(b) or (a is None and b is None):
            pass
        else:
            # Type mismatch — treat as value change
            out.append({
                "kind": "value-changed", "at": at, "from": a, "to": b,
            })
            return

        if isinstance(a, dict):
            keys_a = set(a.keys())
            keys_b = set(b.keys())
            for k in sorted(keys_b - keys_a):
                out.append({
                    "kind": "added", "at": _path_join(at, k), "value": b[k],
                })
                if len(out) >= _MAX:
                    return
            for k in sorted(keys_a - keys_b):
                out.append({
                    "kind": "removed", "at": _path_join(at, k), "value": a[k],
                })
                if len(out) >= _MAX:
                    return
            for k in sorted(keys_a & keys_b):
                _walk(a[k], b[k], _path_join(at, k))
        elif isinstance(a, list):
            # Diff by index. A shift-add/remove will show up as
            # value-changed at multiple indices — good enough for the
            # layman summary (they don't care about LCS optimality).
            for i in range(max(len(a), len(b))):
                if i >= len(a):
                    out.append({
                        "kind": "added", "at": f"{at}[{i}]", "value": b[i],
                    })
                elif i >= len(b):
                    out.append({
                        "kind": "removed", "at": f"{at}[{i}]", "value": a[i],
                    })
                else:
                    _walk(a[i], b[i], f"{at}[{i}]")
                if len(out) >= _MAX:
                    return
        else:
            # Scalar leaf
            if a == b:
                return
            # Detect the "text-changed" shape when the parent key looks
            # like a text-shaped prop. Path tail — everything after the
            # last "." — is what we check.
            tail = at.rsplit(".", 1)[-1]
            tail = tail.split("[", 1)[0]
            if (
                tail in _TEXT_PROP_KEYS
                and isinstance(a, str) and isinstance(b, str)
            ):
                out.append({
                    "kind": "text-changed", "at": at,
                    "from": a, "to": b,
                })
            else:
                out.append({
                    "kind": "value-changed", "at": at, "from": a, "to": b,
                })

    _walk(pre, post, path or "")

    if len(out) >= _MAX:
        out.append({
            "kind": "truncated",
            "note": (
                f"more than {_MAX} concrete changes — schema was heavily "
                "rewritten. Summarize at a high level; do NOT enumerate."
            ),
        })
    return out


def summarize_change_list(changes: list[dict]) -> str:
    """Human-readable one-liner from the change-list, e.g.
    ``'2 text changes, 1 addition, 1 removal'``. Used in trace summaries
    so the SSE chip and log line stay compact."""
    if not changes:
        return "no changes"
    by_kind: dict[str, int] = {}
    for c in changes:
        by_kind[c.get("kind", "?")] = by_kind.get(c.get("kind", "?"), 0) + 1
    parts = []
    labels = {
        "text-changed": "text change",
        "added": "addition",
        "removed": "removal",
        "value-changed": "value change",
        "truncated": "(truncated)",
    }
    for kind, count in by_kind.items():
        label = labels.get(kind, kind)
        parts.append(f"{count} {label}" + ("s" if count != 1 and not label.startswith("(") else ""))
    return ", ".join(parts)
