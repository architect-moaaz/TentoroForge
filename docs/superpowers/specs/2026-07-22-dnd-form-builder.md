# Drag-and-Drop Form Builder — spec + slice plan

**Date:** 2026-07-22
**Branch:** forge-v3-smith-orchestrator-v2
**Status:** approved (design)

## Framing

**AI-driven remains the primary channel.** Chat with Smith is still how a
user builds a form from scratch — natural language beats 15 drags. DnD is
a *complementary* direct-manipulation surface for the micro-ops that are
awkward in chat:

- Reordering fields ("move phone below email")
- Deleting a single field
- Inserting one field between two others at a precise position
- Exploratory tweaks ("what would a Select look like here")

Both channels write to the **same** `src/schemas/<page>.json` file and share
one undo timeline. The two must never drift.

## Decisions locked (user-confirmed)

| Decision | Choice |
|---|---|
| First-ship scope | All five slices (DND-1..5) — reorder, delete, palette, live-sync, shared undo |
| Sync model | **Optimistic canvas + server confirms** — canvas updates instantly on drop; PUT fires in background; server applies deterministic guards + returns final schema; canvas reconciles |

## Architecture

### Backend seam — `POST /api/projects/{id}/schema-edit`

Accepts a **typed deterministic operation** on a page schema. Pure JSON
patch — no LLM in the hot path. Falls back to the existing chat-based
`edit_page` tool only when the op is expressive (natural-language phrasing,
which DnD never emits).

```
POST /api/projects/{id}/schema-edit
{
  "page_id":   "recruiters-new",
  "operation": "insert" | "delete" | "reorder" | "update-props",
  // insert:
  "component": "Input" | "Select" | "PasswordInput" | "FileUpload" | ...,
  "at_path":   ["root","children",0,"children",2,"children"],
  "index":     3,
  "props":     { "name": "phone", "label": "Phone" },
  // delete / update-props:
  "at_path":   [...],
  // reorder:
  "from_index": 2,
  "to_index":   0,
}
→ 200 { "schema": <new full schema>, "revision": "sha256:..." }
```

Server-side:
1. Load `src/schemas/<page_id>.json`.
2. Apply the op via `services/schema_json_patch.py` (new module, pure).
3. Run the deterministic post-gen guards (surface_wrap_guard, field_align,
   etc.) — same ones that gate a full generation. May reshape the drop.
4. Write atomically via `atomic_apply.apply_bundle` (Slice 5-T1).
5. Emit `schema-changed` event on the existing project event stream (Slice 10).
6. Return the final schema + revision hash so the canvas can reconcile.

### Frontend surfaces

**Palette** (left rail toggle) — filtered from `packages/registry/dist/starter.json`
to form-safe types. Each entry is a `<draggable>` with a preview.

**Canvas overlay** — every Form node's children get:
- Selection outline on click
- Drag handle (grab icon on hover)
- Delete affordance (⌫ key or hover-X button)
- Insertion indicators between siblings + at the end

**dnd-kit** for the DnD primitive — modern, keyboard-accessible, ~15kb.
Not react-dnd (older, larger, worse a11y).

**Optimistic state**:
```
onDrop(op) {
  applyLocally(op)            // canvas updates instantly
  const revToken = uuid()
  putSchemaEdit(op, revToken)
    .then(final => reconcile(final, revToken))
    .catch(err => rollback(op, err))
}
```

Reconciliation: if the server-returned schema differs from the local
optimistic result (a guard reshaped the drop), replay the delta with a
subtle flash so the user sees what changed.

### Coexistence with Smith

- Both channels PUT via the same seam (`schema-edit`), or Smith uses its
  existing `edit_page` tool which writes the same file.
- Server emits `schema-changed` for every write, regardless of source.
- Canvas subscribes to the event stream — when the currently-open page's
  mtime bumps, refetch + reconcile. If a drag is in progress, defer the
  reconcile until drop.
- Undo stack (from UX-1) is shared: each entry tagged with
  `source: "chat" | "canvas"` for a UI badge. `undo` pops the most recent
  regardless of source.

## Slice plan (5 slices, ~1.5–2 weeks)

| # | Slice | Effort | Files |
|---|---|---|---|
| **DND-1** | `POST /api/projects/{id}/schema-edit` — pure JSON patch, wraps `edit_page` | ~½ day | backend/services/schema_json_patch.py, backend/routers/schema_edit.py |
| **DND-2** | Canvas: click-to-select + delete + drag-to-reorder existing children | ~2 days | frontend/src/editor/canvas/*, add dnd-kit |
| **DND-3** | Palette + drop targets + insertion indicators + insert-field modal | ~4 days | frontend/src/editor/palette/*, drop-zone components, prop-form modal |
| **DND-4** | Live-sync: canvas subscribes to project event stream, reconciles on schema-changed | ~1 day | frontend/src/editor/hooks/useLiveSchema.ts, backend emit call |
| **DND-5** | Shared undo timeline across chat + DnD, source badge | ~1 day | frontend/src/editor/undo-store.ts extend, badge component |

Every slice ships independently — DND-1 alone enables headless clients;
DND-1+2 covers the highest-frequency ops. Each commit is a coherent
step.

## Non-goals (deferred)

- **Full canvas-based page authoring from scratch** — DnD only edits
  existing pages; creating a fresh page still goes through chat + the
  `add_page` seam.
- **Layout ops** (splitting a Stack, changing Grid columns via drag,
  moving fields between Cards). Field-level ops only.
- **Nested-field DnD** (dragging a whole Card containing fields).
  Prop-panel edits still work for those.
- **Real-time multi-user collaboration** on the same page (no CRDT). One
  editor at a time; live-sync is one-way (server → canvas) for
  same-user cross-session sync.
- **Custom validation feedback** in the drop modal — required props are
  enforced but no live "this Select is missing options" hints yet.
