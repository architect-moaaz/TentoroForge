# Smith Auto-Act — Default to action instead of "which page?"

**Date:** 2026-08-07
**Owner:** Smith orchestrator
**Status:** Approved for implementation (S1 → S2 → S3 → S4 in one pass)

## Problem

When a user says *"make the Status field a color badge"*, Smith today runs `find_resources("Status")`, gets a weak-token-overlap score, and punts with *"which page?"*. This happens on ~70% of field-level asks.

The information Smith needs is available:
- `grep_schemas` — cross-file content search
- `find_component`, `read_page`, `list_entities` — already there
- The **user's current route** — sitting in the visual-editor store but never threaded into the `/chat` payload

Smith bails because the system prompt biases toward "ask when uncertain." That default made sense before `revert_last_patch` and per-round git snapshots. Now the cost of a wrong autonomous edit is one Undo click — cheaper than a disambiguation round-trip.

## Vision

Smith **acts by default**, escalates to ask only on true ambiguity:

- **High confidence** (route matches, single strong match) → edit + narrate + Undo
- **Universal intent** (*"Status field everywhere it appears"*) → edit all matches
- **True ambiguity** (2-3 equally strong candidates) → chip with 3 previewed options
- **Real dead end** (no candidates or contradicting evidence) → ask, but only after scanning

## Four slices — implement all in one pass

### S1 — Route context threading (~1 day)

**Frontend:**
- `ChatPanel.tsx` reads current route from the visual-editor / preview store when composing the `/chat` payload. Include `current_route: string | null` alongside `message`.
- If no editor is open (e.g. the chat panel is the only visible surface), send `null`.

**Backend:**
- `POST /api/projects/{id}/chat` payload schema gains `current_route: str | None = None`
- `services.smith_agent.run_smith_agent(...)` accepts `current_route`, injects it into `SmithMemory` context block as `Current page: /path`
- `services.smith_memory` renders it in the memory block only when non-null

**Tests:**
- `test_smith_memory.py`: memory block includes `Current page:` line when `current_route` set, omits when None
- Payload validation test: `current_route` optional, ignored gracefully on absence

### S2 — `resolve_target` scoring (~1 day)

**New module:** `backend/services/smith_decide.py`

```python
@dataclass(frozen=True)
class Candidate:
    kind: Literal["page", "component", "entity", "workflow"]
    route: str | None          # page's route if kind=page, else None
    path: str                  # file path on disk
    matched_by: list[str]      # ["label", "field_name", "entity_ref"]
    excerpt: str               # 200-char preview

@dataclass(frozen=True)
class Resolution:
    kind: Literal["act", "act_all", "chip", "ask"]
    targets: list[Candidate]   # 1 for act; N for act_all/chip; 0 for ask
    reason: str                # human-readable justification

def resolve_target(
    query: str,
    output_dir: str,
    *,
    current_route: str | None = None,
    recent_edits: list[str] = (),
) -> Resolution:
    """Score every candidate; return the action Smith should take.

    Scoring:
      +50  current_route == candidate.route
      +20  candidate.route in recent_edits
      +15  literal label match (case-insensitive)
      +10  entity relevance (query mentions entity that owns the field)

    Decision:
      score >= 60 AND gap-to-second >= 20  → act
      universal_intent(query)              → act_all
      2 <= len(candidates) <= 4            → chip
      else                                 → ask
    """
```

Universal-intent detector is a small regex helper: matches phrases like *"everywhere"*, *"all pages"*, *"on every X"*, *"across the app"*. If matched, the caller should apply the edit to every candidate.

**Tests:** `backend/tests/services/test_smith_decide.py`
- current-route hit outranks label-only match
- literal label match without route bias → chip (not act)
- universal_intent phrases route to `act_all`
- 5+ equal candidates → still `ask` (chip cap is 4)
- empty candidate list → `ask` with reason

### S3 — "Also apply to X, Y" affordance (~1 day)

When Smith `act`s on a single target but other candidates exist, the chat card gets an inline extension row:

```
✓ Made Status a color badge on /candidates.
  [Undo]  Also apply to: [/applications] [/interviews]
```

Clicking `[/applications]` fires a follow-up Smith turn with the same intent, scoped to `/applications`. This turns "Smith picked one, but I meant all three" into a two-click recovery.

**Backend:**
- Smith's response metadata gains `also_applies_to: list[{route, label}] | None`
- Populated by the caller when `resolve_target` returns `act` but candidates > 1

**Frontend:**
- `ChatMessage.tsx` renders the extension row when `metadata.also_applies_to` present
- Each chip on click sends `"apply same change to <route>"` as a new `/chat` message with the corresponding `current_route`

### S4 — Multi-candidate chip UI (~2 days)

When `resolve_target` returns `chip`, Smith responds with a special card instead of prose ambiguation:

```
Which "Status" did you mean?
┌─────────────────────────┐ ┌─────────────────────────┐ ┌─────────────────────────┐
│ /candidates             │ │ /applications           │ │ /interviews             │
│ Column in the table     │ │ Field on the form       │ │ Column in the table     │
│ Uses Badge already      │ │ Uses Select             │ │ Plain text              │
│  [Choose this]          │ │  [Choose this]          │ │  [Choose this]          │
└─────────────────────────┘ └─────────────────────────┘ └─────────────────────────┘
                                       [Apply to all]
```

**Backend:**
- Smith's response `message_type` gains new value `disambiguation`
- `metadata.candidates: list[{route, path, kind, excerpt, current_rendering}]`
- Each candidate carries a `current_rendering` string ("Badge · red for cancelled", "Select · 5 options", "Plain text") derived from reading the page schema

**Frontend:**
- New component `DisambiguationCard.tsx` (~sibling of SelfHealCard/VerifyProgressCard)
- Renders when `message.message_type === "disambiguation"`
- Each option's `[Choose this]` sends `"apply my previous change to <route>"` with `current_route: <route>`
- `[Apply to all]` sends `"apply my previous change everywhere it applies"` — Smith routes that back through `resolve_target` with universal intent

**Tests:**
- Backend unit: `metadata.candidates` shape validation
- Frontend: component snapshot + click sends correct payload

## Guardrails

- **Undo affordance mandatory** — every auto-act response includes `[Undo]`. Auto-act without undo would be too aggressive.
- **Confidence floor** — `resolve_target` never returns `act` with score < 60. Below that it degrades to `chip` or `ask`.
- **Post-edit validation** — Smith's existing `post_generate_fixes` runs; if the edit breaks structural invariants, roll back and escalate to `ask` with the failure reason.
- **Route bias sanity check** — if `current_route` doesn't exist in `plan.pages`, ignore it (stale editor state).

## Success metric

Recruitment fixture ask: *"make the Status field a color badge"*
- **Before**: 2 turns (ask → answer → edit)
- **After**: 1 turn (edit + narrate + "also apply to /applications, /interviews" chips)

Across 20 field-level asks on the fixture, target: reduce median turns from 2 → 1.

## Non-goals

- **No RAG / embeddings** — the registry is structured; token+route scoring is sufficient. Revisit only if residual ambiguity > 20% after S1-S4.
- **No cross-project context** — each Smith turn is scoped to one project. Recent-edit history is per-project.
- **No LLM-based intent classifier for universal_intent** — regex + small phrase list. LLM here would be over-engineered.

## Interfaces (concrete for implementation)

`SmithMemoryContext` (extend existing):
```python
@dataclass
class SmithMemoryContext:
    ...  # existing fields
    current_route: str | None  # NEW; None if editor not open
    recent_edits: list[str]    # NEW; last 5 routes user edited this session
```

`ChatMessage.metadata` extensions (both platform-side + frontend `types/project.ts`):
```typescript
type MessageMetadata = {
  ...  // existing
  also_applies_to?: Array<{route: string; label: string}> | null;
  candidates?: Array<{
    route: string;
    path: string;
    kind: 'page' | 'component' | 'entity' | 'workflow';
    excerpt: string;
    current_rendering: string;
  }> | null;
};
```

New `message_type = "disambiguation"` added to the enum in both backend model + frontend type.
