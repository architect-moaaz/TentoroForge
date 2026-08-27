"""Smith's cross-turn memory — the 'context engine' for the conversational
build/fix assistant.

Two layers per project, both read from ``conversations``:

1. **Verbatim window** — the last N user+assistant turns, rendered as short
   ``role (HH:MM): text`` lines. Enough for "the Schedule button" → "yes fix
   it" → "still broken" to flow within a single Smith invocation.
2. **Rolling state** — a compact deterministic summary of what Smith has DONE
   and what's still outstanding, derived from the Conversation metadata_
   (applied commits, pending fixes, recent intents). No LLM in this path —
   the summary is a bulleted "facts on the ground" list, cheap to rebuild
   every turn, immune to summarizer drift.

Together they render into a single ``<smith-memory>`` prompt block that
sits alongside the recall dossier (from ``services.app_recall``) in the
Smith agent's initial user message.

Design notes
------------
The memory has NO opinions — it just surfaces facts from the DB. Smith's
reasoning is where interpretation happens. Keeping the two separated lets
each be tested/replaced independently.

The verbatim window is bounded (SMITH_MEMORY_VERBATIM_N) to protect input
tokens. Older turns are represented only by the rolling state.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #

SMITH_MEMORY_VERBATIM_N = 3
"""How many trailing user+assistant turn PAIRS to keep verbatim. Older
material only appears via the rolling state facts."""

_VERBATIM_CLIP = 1200
"""Per-turn character cap for the verbatim rendering.

Sized so a full Smith turn — a plan proposal + a follow-up question ("would
you like me to also X, or Y?") — fits without truncation. The critical
failure mode 320 caused: Smith proposes ``do A, or B?`` in ~700 chars, gets
clipped at 320 losing the offer, and on the user's short "yes, B" reply
Smith has no context for what B was and asks them to repeat themselves."""

_STATE_ROW_CLIP = 200
"""Per-row character cap for a rolling-state line."""

_STATE_MAX_ROWS = 8
"""Rolling-state keeps at most this many facts. Newer wins."""


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class MemoryTurn:
    """One user or assistant turn, normalized for verbatim rendering."""

    role: str  # "user" | "assistant"
    content: str
    created_at: Optional[datetime] = None
    intent: Optional[str] = None   # metadata.intent (FIX / PLAN / …)
    pending_fix: bool = False      # metadata.pending_fix present
    applied: bool = False          # metadata.fixApplied True OR commit_hash present
    apply_resolved: Optional[bool] = None
    """When ``applied`` is True: did the verify pass clean? None when unknown
    (older turns without verify metadata). False means the apply left issues
    the user may want Smith to continue investigating."""
    apply_remaining: int = 0
    """Count of unresolved issues left by an applied fix (from verify.remaining)."""
    edited_paths: list[str] = field(default_factory=list)
    """Files this assistant turn wrote/changed (from metadata.edited_paths).

    CTX-1: used by :func:`derive_last_touched` so the next Smith turn can
    build a resource-registry slice for the most recently touched page —
    generic follow-ups like "the button doesn't work" then land on the
    same artifact instead of triggering an ask-user punt."""


@dataclass
class SmithMemory:
    """Full memory bundle for one project turn."""

    verbatim: list[MemoryTurn] = field(default_factory=list)
    state_lines: list[str] = field(default_factory=list)
    resource_slice: str = ""
    """Optional resource-registry slice for the last-touched page (CTX-1).

    Rendered as its own ``## Last-touched context`` section inside the
    memory block so Smith can debug a follow-up without re-hunting for the
    artifact it just modified."""
    proof_summary: str = ""
    """Optional summary of the app's proof_report.json findings.

    Read from ``contracts/proof_report.json`` (written by the pipeline's
    proof_pass). Rendered under its own header so Smith can proactively
    surface things like "your `/scans/[id]/prices` page has an orphan
    binding — want me to fix it?" without the user having to know or ask
    about the report file.
    """
    blueprint: str = ""
    """The app's ``BLUEPRINT.md`` — the human-readable, always-current
    snapshot of the whole app (data model, pages, workflows, forms,
    design, actors). Rendered as its own header at the top of the memory
    block so Smith gets the app-map view before any turn context.

    When present, this REPLACES the older JSON-blueprint context slice
    (Smith no longer needs both — one comprehensive doc beats two
    partial ones). Absent for pre-blueprint projects; the JSON
    context slice remains the fallback in those cases."""
    session_context_block: str = ""
    """IRF-M5-T3 — pre-rendered substrate context (Shape primitives +
    recent verify_history + recent edit_history). Populated by
    ``read_smith_memory`` when the pipeline persisted a
    ``session_history.json`` alongside the generated app. Empty for
    pre-substrate projects; the rest of the memory renders identically."""
    requirement_block: str = ""
    """Slice 2 of requirement-as-central-piece — pre-rendered block
    describing the ORIGINAL USER REQUIREMENT (prompt + parsed directives
    + amendment history). Loaded from ``src/contracts/requirement.json``.
    Rendered at the TOP of the memory (above the blueprint) so every
    Smith turn stays grounded in what the user actually asked for —
    the source of authority the whole app is a derivation of."""

    def is_empty(self) -> bool:
        return not (
            self.verbatim or self.state_lines or self.resource_slice
            or self.proof_summary or self.blueprint
            or self.session_context_block or self.requirement_block
        )

    def to_prompt_block(self) -> str:
        return build_memory_block(
            self.verbatim, self.state_lines,
            resource_slice=self.resource_slice,
            proof_summary=self.proof_summary,
            blueprint=self.blueprint,
            session_context_block=self.session_context_block,
            requirement_block=self.requirement_block,
        )


# --------------------------------------------------------------------------- #
# Pure builders  (no DB — safe to unit-test)
# --------------------------------------------------------------------------- #

def build_memory_block(
    verbatim: Iterable[MemoryTurn],
    state_lines: Iterable[str],
    *,
    resource_slice: str = "",
    proof_summary: str = "",
    blueprint: str = "",
    session_context_block: str = "",
    requirement_block: str = "",
) -> str:
    """Render the memory as a single prompt block. Pure — no side effects.

    Empty state lines OR empty verbatim are represented as a short "no history"
    line so the model sees a stable structure and doesn't hallucinate history.

    ``resource_slice`` (CTX-1) is a pre-rendered block describing the focal
    entity + FK-neighbors + workflows for the page Smith most recently
    touched. Rendered under its own header so Smith can debug a follow-up
    like "the button isn't working" without re-hunting for the artifact.

    ``blueprint`` is the app's ``BLUEPRINT.md`` text — when present, it
    goes FIRST so Smith reads the full app snapshot before conversation
    context. Rendered inside a fenced ``## App blueprint`` block."""
    v = list(verbatim)
    s = list(state_lines)
    slice_str = (resource_slice or "").strip()
    ps_early = (proof_summary or "").strip()
    bp_early = (blueprint or "").strip()
    sc_early = (session_context_block or "").strip()
    rq_early = (requirement_block or "").strip()

    if not v and not s and not slice_str and not ps_early and not bp_early \
       and not sc_early and not rq_early:
        return "<smith-memory>\nNo prior conversation state.\n</smith-memory>"

    lines: list[str] = ["<smith-memory>"]

    # Requirement — the AUTHORITY. Sits above the blueprint because when
    # the blueprint disagrees with the requirement, the requirement wins
    # (the blueprint is a snapshot of what shipped, the requirement is
    # what the user asked for).
    if rq_early:
        lines.append("## User requirement (authority — the app must reflect this)")
        lines.append("")
        lines.append(
            "**This is what the user asked for.** Every edit MUST preserve "
            "the requirement's directives (KPIs, preset, filters, gauges, "
            "drill-downs). When a follow-up would drop or contradict a "
            "listed directive, refuse and ask the user first. Amendments "
            "override earlier directives; the most recent amendment wins."
        )
        lines.append("")
        lines.append(rq_early)
        lines.append("")

    if bp_early:
        lines.append("## App blueprint (authoritative — always current)")
        lines.append("")
        lines.append(
            "**This document is the source of truth for this app.** Every "
            "structural question about entities, pages, workflows, forms, "
            "navigation, or design MUST consult this blueprint first. If a "
            "downstream file (a schema JSON, a drizzle table, a workflow "
            "file) contradicts the blueprint, the blueprint is what the "
            "user + platform believe the app to be — reconcile the file to "
            "match, don't the other way around. When answering, cite the "
            "blueprint section you consulted."
        )
        lines.append("")
        lines.append(bp_early)
        lines.append("")

    lines.append("## State (facts on the ground, newest first)")
    if s:
        for row in s:
            lines.append(f"- {_clip(row, _STATE_ROW_CLIP)}")
    else:
        lines.append("- (nothing applied or pending yet)")

    lines.append("")
    lines.append(f"## Recent turns (last {len(v)}, oldest first)")
    if v:
        for t in v:
            ts = t.created_at.strftime("%H:%M") if t.created_at else "??:??"
            tags = []
            if t.intent:
                tags.append(t.intent)
            if t.pending_fix:
                tags.append("pending_fix")
            if t.applied:
                tags.append("applied")
            tag_str = f" [{' '.join(tags)}]" if tags else ""
            lines.append(
                f"- {t.role} ({ts}){tag_str}: {_clip(t.content, _VERBATIM_CLIP)}"
            )
    else:
        lines.append("- (no prior turns)")

    if slice_str:
        lines.append("")
        lines.append("## Last-touched context")
        lines.append(slice_str)

    ps = (proof_summary or "").strip()
    if ps:
        lines.append("")
        lines.append("## App proof report")
        lines.append(ps)

    # IRF-M5-T3: substrate view (shape summary + recent verify/edit history).
    # Rendered when the caller supplied a pre-computed block via
    # ``render_session_context_block``. Kept as a pass-through so
    # build_memory_block stays pure — file I/O for the block is the
    # caller's job.
    sc_block = (session_context_block or "").strip()
    if sc_block:
        lines.append("")
        lines.append("## Substrate context")
        lines.append(sc_block)

    lines.append("</smith-memory>")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# IRF-M5-T3 — SessionContext view helper
# --------------------------------------------------------------------------- #

_SC_VERIFY_MAX = 5
_SC_EDIT_MAX = 5


def render_session_context_block(ctx: Any) -> str:
    """Render a compact prompt block summarising the SessionContext.

    Sections:
    - App shape primitives (layout/nav/data/auth) — 4 lines max
    - Recent verify_history (top 5) — stage, check, passed, first finding
    - Recent edit_history (top 5) — stage, intent, files_touched

    Empty string when ctx is None or carries no substrate data.
    Accepts ``Any`` (not a strict type) so callers can pass either a
    ``SessionContext`` or a raw persisted-history dict — the renderer
    duck-types on both shapes."""
    if ctx is None:
        return ""

    shape = _sc_getattr(ctx, "shape_profile", {}) or {}
    verify = _sc_getattr(ctx, "verify_history", []) or []
    edits = _sc_getattr(ctx, "edit_history", []) or []

    lines: list[str] = []

    if isinstance(shape, dict) and shape:
        row_bits: list[str] = []
        for slice_name, keys in (
            ("layout", ("shell", "hero", "primaryInteraction", "density")),
            ("nav", ("menu", "back")),
            ("data", ("readShape", "denormalization")),
            ("auth", ("surface", "gating")),
            ("workflows", ("executionMode",)),
        ):
            slice_val = shape.get(slice_name)
            if not isinstance(slice_val, dict):
                continue
            picked = [f"{k}=`{slice_val[k]}`" for k in keys if slice_val.get(k)]
            if picked:
                row_bits.append(f"{slice_name}({', '.join(picked)})")
        if row_bits:
            lines.append("**Shape:** " + " · ".join(row_bits))

    if verify:
        lines.append("")
        lines.append(f"**Recent verify ({min(len(verify), _SC_VERIFY_MAX)} of {len(verify)}):**")
        for v in verify[:_SC_VERIFY_MAX]:
            stage = _sc_getattr(v, "stage", "?")
            check = _sc_getattr(v, "check", "?")
            passed = _sc_getattr(v, "passed", None)
            findings = _sc_getattr(v, "findings", []) or []
            mark = "✓" if passed is True else ("✗" if passed is False else "?")
            head = f"- {mark} {stage} · {check}"
            if findings and passed is False:
                first = findings[0]
                rule = first.get("rule") if isinstance(first, dict) else None
                msg = first.get("message") if isinstance(first, dict) else None
                if rule:
                    head += f" — {rule}"
                elif msg:
                    head += f" — {_clip(msg, 80)}"
            lines.append(head)

    if edits:
        lines.append("")
        lines.append(f"**Recent edits ({min(len(edits), _SC_EDIT_MAX)} of {len(edits)}):**")
        for e in edits[:_SC_EDIT_MAX]:
            stage = _sc_getattr(e, "stage", "?")
            intent = _sc_getattr(e, "intent", "?")
            files = _sc_getattr(e, "files_touched", []) or []
            files_str = ", ".join(files[:3]) + ("..." if len(files) > 3 else "")
            lines.append(f"- {stage}: {intent}" + (f" [{files_str}]" if files_str else ""))

    return "\n".join(lines)


def _sc_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Duck-type accessor — works on both dataclasses and dicts."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# --------------------------------------------------------------------------- #
# Proof-report summary  (PIPELINE Phase 5 UX bridge)
# --------------------------------------------------------------------------- #

def load_blueprint(output_dir: str) -> str | None:
    """Read ``<output_dir>/BLUEPRINT.md`` — the authoritative app snapshot
    the pipeline writes after every mutation. Returns None when absent
    (pre-blueprint project or writer disabled); callers fall back to the
    older JSON-blueprint context slice in that case.

    Content is soft-capped so a very large blueprint (an ATS with 200
    pages, a marketplace with 60 workflows) doesn't blow Smith's input
    token budget. Everything past the cap is elided with a marker so
    Smith reads the omission rather than misreading a truncated section.
    """
    if not output_dir:
        return None
    from pathlib import Path as _Path
    p = _Path(output_dir) / "BLUEPRINT.md"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    CAP = 40_000  # ~10K tokens — a full ATS-scale blueprint fits comfortably
    if len(text) > CAP:
        text = text[:CAP - 80].rstrip() + \
               "\n\n_… blueprint truncated to fit Smith's context budget._"
    return text or None


def build_proof_summary(output_dir: str, *, max_errors: int = 5, max_warnings: int = 3) -> str:
    """Compose Smith's view of the app's proof_report.json.

    Reads ``<output_dir>/contracts/proof_report.json`` (written by
    services.proof_pass) and returns a compact markdown block Smith can
    use to proactively surface structural problems. Empty string when
    the report is missing, malformed, or reports pass=True with no
    findings — nothing to say.

    Shape:
        Status: FAILED (3 errors, 12 warnings)
        Errors (top 5):
        - [orphan-navigate] Button navigate="/settings" targets a page not in the manifest.  (src/schemas/scan.json)
        - [undefined-ref] "{{status}}" references a variable no workflow node declares.  (workflows/ScanProduct.json)
        - ...
        Warnings (top 3):
        - [empty-page] Page has no data-bearing components (only chrome).  (src/schemas/dashboard.json)

    Smith's system prompt instructs it to mention these proactively when
    the user reports a symptom that matches ("scan is stuck" → mention
    the workflow undefined-ref finding).
    """
    import json as _json
    from pathlib import Path as _Path

    if not output_dir:
        return ""
    report_path = _Path(output_dir) / "contracts" / "proof_report.json"
    if not report_path.exists():
        return ""
    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    passed = bool(data.get("passed", False))
    err_n = int(data.get("error_count") or 0)
    warn_n = int(data.get("warning_count") or 0)
    findings = data.get("findings") or []
    if not isinstance(findings, list):
        findings = []

    # Nothing useful to say when the app is clean.
    if passed and err_n == 0 and warn_n == 0:
        return ""

    errs = [f for f in findings if isinstance(f, dict) and f.get("severity") == "error"]
    warns = [f for f in findings if isinstance(f, dict) and f.get("severity") == "warning"]

    def _line(f: dict) -> str:
        code = f.get("code") or "?"
        msg = str(f.get("message") or "")[:180]
        loc = f.get("file") or f.get("workflow_file") or f.get("page_file") or ""
        return f"- [{code}] {msg}" + (f"  ({loc})" if loc else "")

    lines: list[str] = []
    status = "PASSED" if passed else "FAILED"
    lines.append(f"Status: {status} ({err_n} error{'s' if err_n != 1 else ''}, "
                 f"{warn_n} warning{'s' if warn_n != 1 else ''})")
    if errs:
        lines.append(f"Errors (top {min(len(errs), max_errors)}):")
        for f in errs[:max_errors]:
            lines.append(_line(f))
    if warns:
        lines.append(f"Warnings (top {min(len(warns), max_warnings)}):")
        for f in warns[:max_warnings]:
            lines.append(_line(f))

    lines.append(
        "\nWhen the user reports a symptom that matches one of these findings, "
        "mention the specific finding in your reply and offer to fix it. Do NOT "
        "dump the whole list unprompted — surface only what's relevant."
    )
    return "\n".join(lines)


def derive_state_lines(all_turns: list[MemoryTurn]) -> list[str]:
    """Deterministic 'facts on the ground' summary. Walks ALL turns (not just
    the verbatim window) and picks out applied fixes, pending proposals, and
    the current topic based on the latest FIX/PLAN intents.

    Returned newest-first; capped at ``_STATE_MAX_ROWS`` rows. Pure.
    """
    if not all_turns:
        return []

    # Walk newest → oldest, collect a small set of state facts.
    rows: list[str] = []
    latest_pending: Optional[MemoryTurn] = None
    latest_intent: Optional[str] = None
    apply_seen_after_pending = False  # any newer assistant turn was applied?

    for turn in reversed(all_turns):
        if turn.role != "assistant":
            continue
        # An applied turn newer than a pending proposal kills the pending
        # signal (the user already accepted, this pending line is stale).
        if turn.applied and latest_pending is None:
            apply_seen_after_pending = True
        if latest_pending is None and turn.pending_fix and not turn.applied:
            latest_pending = turn
        if latest_intent is None and turn.intent:
            latest_intent = turn.intent

    # Pending fix takes top position (Smith should offer to apply, not
    # re-propose) — but only when nothing newer has already been applied.
    if latest_pending is not None and not apply_seen_after_pending:
        ts = latest_pending.created_at.strftime("%H:%M") if latest_pending.created_at else "??:??"
        rows.append(
            f"pending fix from {ts} — user has not clicked Apply yet. "
            "If the user re-mentions the same symptom, offer to Apply "
            "rather than re-propose."
        )

    # Applied fixes / commits, walked from most recent backwards. When the
    # most-recent apply left issues unresolved, promote a follow-up line so
    # Smith reads it as "continue investigating" on the next affirmative
    # user turn.
    for i, turn in enumerate(reversed(all_turns)):
        if turn.role != "assistant":
            continue
        if not turn.applied:
            continue
        ts = turn.created_at.strftime("%H:%M") if turn.created_at else "??:??"
        first_line = _clip(turn.content.split("\n", 1)[0], _STATE_ROW_CLIP - 40)
        # The FIRST applied turn walked (newest) gets special treatment when
        # verify was not clean — a continuation hint so a follow-up like
        # "yes please" doesn't restart cold.
        if i == 0 and turn.apply_resolved is False:
            rows.append(
                f"last apply at {ts} left {turn.apply_remaining} issue(s) "
                f"unresolved. If the user replies affirmatively ('yes', "
                f"'go on', 'take another look'), CONTINUE investigating "
                f"the SAME feature — memory has enough context, do NOT ask "
                f"which screen. Previous applied change: {first_line}"
            )
        else:
            rows.append(f"applied change at {ts}: {first_line}")
        if len(rows) >= _STATE_MAX_ROWS:
            break

    # Fallback to intent when nothing applied/pending — at least tell Smith
    # what topic the user is on.
    if not rows and latest_intent:
        rows.append(f"most recent intent: {latest_intent}")

    return rows[:_STATE_MAX_ROWS]


def normalize_conversation_rows(rows: list[Any]) -> list[MemoryTurn]:
    """Turn a list of Conversation ORM rows (or dicts, in tests) into a list of
    :class:`MemoryTurn` OLDEST-FIRST (the render order).

    Accepts anything with ``role``, ``content``, ``created_at``, and
    ``metadata_`` (or ``metadata``) attributes/keys — the tests pass plain
    dicts, the router passes ORM rows.
    """
    out: list[MemoryTurn] = []
    for row in rows or []:
        role = _pluck(row, "role")
        # Enums render as e.g. "MessageRole.user" — take the .value if present.
        if hasattr(role, "value"):
            role = role.value
        role = str(role or "").lower()
        if role not in ("user", "assistant"):
            continue
        content = _pluck(row, "content") or ""
        md = _pluck(row, "metadata_") or _pluck(row, "metadata") or {}
        if not isinstance(md, dict):
            md = {}
        applied = (
            md.get("fixApplied") is True
            or bool(md.get("commit_hash"))
        )
        # verify: {"resolved": bool, "remaining": [...]} on apply-outcome turns.
        verify = md.get("verify") if isinstance(md.get("verify"), dict) else {}
        apply_resolved: Optional[bool] = None
        apply_remaining = 0
        if applied and verify:
            if "resolved" in verify:
                apply_resolved = bool(verify.get("resolved"))
            rem = verify.get("remaining")
            if isinstance(rem, list):
                apply_remaining = len(rem)
        # CTX-1: edited_paths — what this turn actually wrote. Persisted by
        # the Smith terminal branches in routers/generate.py; used on the
        # NEXT turn by derive_last_touched to build a focal-resource slice.
        raw_paths = md.get("edited_paths") or []
        edited_paths = [str(p) for p in raw_paths if isinstance(p, str) and p]

        out.append(
            MemoryTurn(
                role=role,
                content=str(content),
                created_at=_pluck(row, "created_at"),
                intent=str(md.get("intent")) if md.get("intent") else None,
                pending_fix=isinstance(md.get("pending_fix"), dict),
                applied=applied,
                apply_resolved=apply_resolved,
                apply_remaining=apply_remaining,
                edited_paths=edited_paths,
            )
        )
    # Callers may pass in either order — sort by created_at so we always
    # return oldest-first (falls back to input order for missing timestamps).
    out.sort(key=lambda t: t.created_at or datetime.min)
    return out


def build_smith_memory(
    all_turns: list[MemoryTurn],
    verbatim_n: int = SMITH_MEMORY_VERBATIM_N,
) -> SmithMemory:
    """From a full ordered turn list, build the verbatim window + state
    summary. Pure — DB access happens in :func:`read_smith_memory`.

    ``verbatim_n`` is the number of trailing turns to keep verbatim (NOT the
    number of pairs — a single trailing user turn without an assistant reply
    still counts as N=1)."""
    verbatim = all_turns[-max(0, verbatim_n):] if verbatim_n > 0 else []
    return SmithMemory(
        verbatim=verbatim,
        state_lines=derive_state_lines(all_turns),
    )


# --------------------------------------------------------------------------- #
# CTX-1: last-touched derivation (pure)
# --------------------------------------------------------------------------- #

def derive_last_touched(all_turns: list[MemoryTurn]) -> Optional[str]:
    """Return the route Smith most recently wrote to, or None.

    Walks assistant turns newest-first; returns the first route derivable
    from their ``edited_paths``. The caller uses this to build a focal
    resource-registry slice for the next turn's memory block."""
    if not all_turns:
        return None
    for turn in reversed(all_turns):
        if turn.role != "assistant":
            continue
        for p in turn.edited_paths or []:
            route = path_to_route(p)
            if route:
                return route
    return None


def path_to_route(path: str) -> Optional[str]:
    """Best-effort ``schemas or app path → route`` normalization.

    Handles the two canonical layouts our generated apps use::

        src/schemas/candidates/new.json      → /candidates/new
        src/schemas/dashboard.json           → /dashboard
        src/app/candidates/new/page.tsx      → /candidates/new
        src/app/pipeline/[driveId]/route.ts  → /pipeline/[driveId]

    Anything else returns None so callers know not to try a slice for it
    (config files, library helpers, package.json, README, etc.).
    """
    if not path or not isinstance(path, str):
        return None
    # Strip any leading absolute-path prefix by finding the anchor.
    anchors = ("src/schemas/", "src/app/")
    idx = -1
    anchor = ""
    for a in anchors:
        j = path.find(a)
        if j >= 0 and (idx < 0 or j < idx):
            idx = j
            anchor = a
    if idx < 0:
        return None
    tail = path[idx + len(anchor):]
    if not tail:
        return None
    # src/schemas: strip .json suffix; the remaining path IS the route.
    if anchor == "src/schemas/":
        if not tail.endswith(".json"):
            return None
        tail = tail[: -len(".json")]
    else:
        # src/app: strip trailing /page.tsx | /route.ts | .tsx | .ts
        for suffix in ("/page.tsx", "/page.ts", "/route.ts", "/route.tsx",
                       "/layout.tsx"):
            if tail.endswith(suffix):
                tail = tail[: -len(suffix)]
                break
        else:
            # Not a routable app file — segments like src/app/lib/x.ts.
            return None
    tail = tail.strip("/")
    if not tail:
        return "/"
    return "/" + tail


# --------------------------------------------------------------------------- #
# DB read  (thin — the pure builders above hold the logic)
# --------------------------------------------------------------------------- #

async def read_smith_memory(
    sess: Any,
    project_id: uuid.UUID,
    *,
    verbatim_n: int = SMITH_MEMORY_VERBATIM_N,
    history_limit: int = 40,
    output_dir: Optional[str] = None,
) -> SmithMemory:
    """Load the recent Conversation window for one project and build the
    memory. Async because the router already uses an ``AsyncSession``.

    ``history_limit`` caps how far back we walk when deriving state
    (verbatim is a strict tail of that window).

    ``output_dir`` (CTX-1): when provided, derive the last-touched route
    from turn history and build a focal resource-registry slice for it.
    The slice is attached to :attr:`SmithMemory.resource_slice` and
    renders under ``## Last-touched context`` in the prompt block.
    Failures are swallowed — memory is never blocked by a slice-build
    error."""
    try:
        from sqlalchemy import select, desc
        from models.project import Conversation
    except Exception:  # pragma: no cover — imports must succeed in-app
        logger.exception("read_smith_memory: cannot import Conversation/select")
        return SmithMemory()

    try:
        result = await sess.execute(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(desc(Conversation.created_at))
            .limit(history_limit)
        )
        rows = list(result.scalars())
    except Exception:  # noqa: BLE001
        logger.exception("read_smith_memory: DB query failed")
        return SmithMemory()

    turns = normalize_conversation_rows(rows)
    mem = build_smith_memory(turns, verbatim_n=verbatim_n)

    if output_dir:
        try:
            from services.smith_resource_slice import build_slice_for_route
            route = derive_last_touched(turns)
            if route:
                mem.resource_slice = build_slice_for_route(output_dir, route)
        except Exception:  # noqa: BLE001
            logger.exception("read_smith_memory: resource-slice build failed")

        # Proof-report awareness — Smith reads the pipeline's proof pass
        # findings on every turn so it can proactively surface them.
        try:
            mem.proof_summary = build_proof_summary(output_dir)
        except Exception:  # noqa: BLE001
            logger.exception("read_smith_memory: proof-summary build failed")

        # BLUEPRINT.md — the authoritative app snapshot. When present,
        # Smith uses it as the primary context (prefer over the older
        # JSON blueprint slice). Failures fall through silently.
        try:
            bp = load_blueprint(output_dir)
            if bp:
                mem.blueprint = bp
        except Exception:  # noqa: BLE001
            logger.exception("read_smith_memory: blueprint load failed")

        # requirement.json — first-class user requirement (Slice 2 of
        # requirement-as-central-piece). Original prompt + parsed
        # directives + amendment history. Rendered at the TOP of the
        # memory so every Smith turn stays grounded in what the user
        # actually asked for. Also attach the fidelity report (Slice 3)
        # so Smith surfaces "you asked for X but it's not on the page"
        # proactively rather than the user having to notice.
        try:
            from services.requirement import (
                load_requirement, render_requirement_for_prompt,
            )
            _req = load_requirement(output_dir)
            _req_block = render_requirement_for_prompt(_req)
            if _req_block:
                # Append the fidelity report (missing / partial verdicts)
                # right under the requirement so Smith sees the gap next
                # to the ask. Missing / partial only — no need to bloat
                # the block with "ok" lines.
                _fid_lines: list[str] = []
                try:
                    import json as _json
                    _fid_path = Path(output_dir) / "src" / "contracts" / "requirement-fidelity.json"
                    if _fid_path.is_file():
                        _fid = _json.loads(_fid_path.read_text(encoding="utf-8"))
                        _open = [v for v in (_fid.get("verdicts") or [])
                                  if v.get("status") in ("missing", "partial")]
                        if _open:
                            _fid_lines.append("  Requirement gaps (per fidelity critic):")
                            for v in _open[:8]:
                                _fid_lines.append(
                                    f"    - [{v.get('status')}] {v.get('directive')}: "
                                    f"asked={v.get('asked')} — {v.get('evidence')}"
                                )
                except Exception:  # noqa: BLE001
                    pass
                mem.requirement_block = _req_block + (
                    "\n".join(_fid_lines) + "\n" if _fid_lines else ""
                )
        except Exception:  # noqa: BLE001
            logger.exception("read_smith_memory: requirement load failed")

        # IRF-M5-T3 wire — substrate context (shape summary + recent
        # verify_history + recent edit_history). Prefer the persisted
        # session_history.json from the last pipeline run (long-lived,
        # survives process restarts); fall back to the ambient
        # SessionContext for in-process runs. Silent on any failure —
        # memory renders identically without it.
        try:
            from services.session_context import current as _sc_current
            from services.session_context import load_history as _sc_load
            persisted = _sc_load(output_dir)
            sc_view: Any = persisted if persisted else _sc_current()
            if sc_view is not None:
                mem.session_context_block = render_session_context_block(sc_view)
        except Exception:  # noqa: BLE001
            logger.exception("read_smith_memory: session-context view failed")

    return mem


# --------------------------------------------------------------------------- #
# Chat-protocol history — CTX-thread                                          #
# --------------------------------------------------------------------------- #
# The verbatim block above stitches prior turns into a bulleted memory dump
# rendered inside a single user message. Fine for background state, but
# terrible for anaphora resolution — a follow-up like "did you fix it?"
# loses its referent because the LLM sees no prior assistant turn in the
# message protocol, only reference bullets.
#
# ``load_chat_history_for_prompt`` returns the same data in the chat
# protocol shape (``[{role: user, content}, {role: assistant, content}, …]``)
# so callers can prepend it to their ``messages`` list. Prior turns then
# behave as real conversation turns to the model, restoring native
# anaphora + context tracking.
#
# Contract: caller supplies the CURRENT user message. If the last row in
# the DB is a ``user`` row whose content matches (persisted by the router
# before Smith ran), we drop it — the caller's own current message is the
# one that will follow this list in the messages array.

_CHAT_HISTORY_CONTENT_CLIP = 800
"""Per-turn content cap when threading. Bigger than the verbatim clip
because we're spending these tokens on a smaller number of turns (6 vs
the state-bullet dump's 40)."""


async def load_pending_confirmation(
    sess: Any,
    project_id: uuid.UUID,
) -> dict | None:
    """The confirmation Smith asked for on the PREVIOUS assistant turn, if any.

    Confirmation used to be granted only when the model relayed the tool's
    summary VERBATIM, so the literal marker survived into the assistant
    message — and nothing in the system prompt told it to (register S24-8).
    A paraphrased prompt plus a user "yes" left the destructive op
    ungrantable: the tool re-asked forever. This reads the fact the SERVER
    recorded instead, so whether the model paraphrased is irrelevant.

    Returns ``{"tool": ..., "kind": ..., "target": ...}`` or ``None``.
    Never raises — an unreadable record means "no pending confirmation",
    which fails CLOSED (the tool asks again) rather than open.
    """
    try:
        from sqlalchemy import select, desc
        from models.project import Conversation, MessageRole, MessageType
    except Exception:  # pragma: no cover — imports must succeed in-app
        logger.exception("load_pending_confirmation: cannot import Conversation")
        return None

    try:
        result = await sess.execute(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .where(Conversation.message_type == MessageType.chat)
            .where(Conversation.role == MessageRole.assistant)
            .order_by(desc(Conversation.created_at))
            .limit(1)
        )
        row = result.scalars().first()
    except Exception:  # noqa: BLE001
        logger.exception("load_pending_confirmation: DB query failed")
        return None

    if row is None:
        return None
    meta = _pluck(row, "metadata_") or _pluck(row, "metadata") or {}
    if not isinstance(meta, dict):
        return None
    pending = meta.get("pending_confirmation")
    return pending if isinstance(pending, dict) and pending else None


async def load_chat_history_for_prompt(
    sess: Any,
    project_id: uuid.UUID,
    current_message: str,
    *,
    limit: int = 6,
) -> list[dict]:
    """Return the last ``limit`` chat-type user/assistant turns for the
    project, in **chronological order**, shaped for the Anthropic
    messages protocol.

    Excludes the current user message when it appears as the most recent
    row (the router persists user messages before Smith runs, so the DB
    tail typically ends with the current turn).

    Only ``MessageType.chat`` rows are threaded — generation / plan /
    error rows carry pipeline state that Smith doesn't need to see as
    conversation.

    Returns an empty list on any DB / import failure. Smith degrades
    gracefully — the flattened memory block still surfaces state facts
    even without threading.
    """
    try:
        from sqlalchemy import select, desc
        from models.project import Conversation, MessageRole, MessageType
    except Exception:  # pragma: no cover — imports must succeed in-app
        logger.exception("load_chat_history_for_prompt: cannot import Conversation")
        return []

    # Pull limit + 1 to have room to drop the current-message tail if
    # it's already been persisted.
    try:
        result = await sess.execute(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .where(Conversation.message_type == MessageType.chat)
            .where(Conversation.role.in_([MessageRole.user, MessageRole.assistant]))
            .order_by(desc(Conversation.created_at))
            .limit(limit + 1)
        )
        rows = list(result.scalars())
    except Exception:  # noqa: BLE001
        logger.exception("load_chat_history_for_prompt: DB query failed")
        return []

    if not rows:
        return []

    # Newest is first — check if it's a duplicate of the current user
    # message. Compare by (role, content) so a genuine "yes" that happens
    # to match a prior "yes" turn isn't dropped by accident.
    newest = rows[0]
    newest_role = _pluck(newest, "role")
    newest_role_str = newest_role.value if hasattr(newest_role, "value") else str(newest_role)
    newest_content = str(_pluck(newest, "content") or "")
    if (
        newest_role_str == "user"
        and current_message is not None
        and newest_content.strip() == str(current_message).strip()
    ):
        rows = rows[1:]

    rows = rows[:limit]  # trim back to requested size

    # Reverse to chronological (oldest → newest) for the messages array.
    rows.reverse()

    threaded: list[dict] = []
    for r in rows:
        role_val = _pluck(r, "role")
        role_str = role_val.value if hasattr(role_val, "value") else str(role_val)
        if role_str not in ("user", "assistant"):
            continue
        content = str(_pluck(r, "content") or "").strip()
        if not content:
            continue
        if len(content) > _CHAT_HISTORY_CONTENT_CLIP:
            content = content[: _CHAT_HISTORY_CONTENT_CLIP - 1] + "…"
        threaded.append({"role": role_str, "content": content})

    # Anthropic requires the messages array to alternate user/assistant
    # starting with user. If our chronological tail happens to start with
    # assistant (e.g. the router persisted a status message before any
    # user turn), drop it — Smith's caller will follow this list with the
    # real current user message, keeping the alternation intact.
    while threaded and threaded[0]["role"] != "user":
        threaded.pop(0)

    # Collapse consecutive same-role rows by keeping only the newest of
    # each run. Anthropic rejects a messages array where two same-role
    # rows are adjacent. Two "user" rows in a row happens when the user
    # sends "did you fix it?" then immediately sends "hello?"; two
    # "assistant" rows happen when Smith emits a system status message
    # persisted as assistant. Keeping the newest per-run preserves the
    # freshest intent while satisfying the protocol.
    collapsed: list[dict] = []
    for m in threaded:
        if collapsed and collapsed[-1]["role"] == m["role"]:
            collapsed[-1] = m
        else:
            collapsed.append(m)
    return collapsed


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _clip(text: Any, limit: int) -> str:
    s = str(text or "")
    s = s.replace("\n", " ")
    if len(s) <= limit:
        return s
    return s[: max(0, limit - 1)] + "…"


def _pluck(obj: Any, key: str) -> Any:
    """Read ``key`` from either an ORM row (attribute) or a dict (item)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
