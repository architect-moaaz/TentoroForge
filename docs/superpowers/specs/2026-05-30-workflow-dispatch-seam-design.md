# Workflow Dispatch Seam — Design Spec

**Date:** 2026-05-30
**Status:** Approved (design) — pending implementation plan
**Scope:** Close the renderer → workflow dispatch seam so generated declarative forms trigger their workflow with the form's field values as the payload, end-to-end.

---

## 1. Problem

In generated Tentoro Forge apps, the schema/renderer path declares workflow
actions on nodes (a `Form` with `props.workflow`, or a `Button` with
`props.workflow`). Both components read `WorkflowDispatcherContext` and call
`dispatch(workflow, payload)` on submit/click:

- `packages/library/src/components/Form/Form.tsx:83,88` (declarative) and `:53,58` (container)
- `packages/library/src/components/Button/Button.tsx:87,112-115`

But **no real `dispatch` is ever provided.** The generated template
`backend/templates/app-foundation/src/lib/schema-page.tsx:43-50` defines a
**server-side** stub that only `console.warn`s, and hands it to the **client**
`WorkflowDispatcherProvider` (`packages/renderer/src/client/WorkflowDispatcher.tsx`).

Two consequences:
1. **Functional:** submitting a workflow form / clicking a workflow button does
   nothing — it never reaches `/api/workflows/...`.
2. **Boundary bug:** passing a plain server function as a prop to a `'use client'`
   component is invalid in the App Router (only Server Actions may cross that
   boundary). The stub could not work even if it did something.

The backend is ready: `runtime_injector.py` already injects
`src/app/api/workflows/[id]/execute/route.ts`, and `WorkflowTriggerButton.tsx`
already demonstrates the client `fetch('/api/workflows/{id}/execute', {input})`
pattern. The missing piece is purely the client dispatch wiring.

## 2. Goal & non-goals

**Goal:** When a user fills a generated **declarative** form (`Form` with a
`fields[]` array and a `workflow`) and submits, the form's field values are sent
as the workflow payload to `/api/workflows/{workflow}/execute`, with loading,
success/error toast, and automatic data refresh. The same dispatch wiring also
makes standalone workflow `Button`s actually fire (transport only).

**Non-goals (explicit follow-ups):**
- Container-mode `Form` (Figma-derived `children` with `Input` nodes) payload
  collection — currently dispatches `{}` (`Form.tsx:58`).
- Standalone `Button` reading enclosing form values — currently sends only the
  static schema `args` (`Button.tsx:114`).
- Field-name → workflow-input-key mapping/validation (today it is a raw
  passthrough by `name`).
- Interpolation of static `Button.args` expressions (only relevant to the
  out-of-scope button-payload case; the in-scope declarative-form path passes
  concrete react-hook-form values).

## 3. Why this scope

The generator emits **declarative** `Form` nodes for data entry, e.g.
`output/3wjvs581/src/schemas/products/form.json`:

```json
{"type":"Form","props":{"workflow":"createProduct","fields":[
  {"kind":"text","name":"name","required":true},
  {"kind":"number","name":"price","required":true}, ...]}}
```

`Form.tsx`'s `DeclarativeForm` path already collects these via react-hook-form
and calls `dispatch(workflow, values)` (`Form.tsx:84-88`). Because `Form` and
`Button` share the **same** `WorkflowDispatcherContext`, providing one real
dispatch closes the seam for both at once and makes the primary
form → workflow payload binding work end-to-end. Container forms and standalone
buttons are different code shapes that need their own payload work — deferred.

## 4. Approach (selected: A — client provider → existing HTTP route)

A small `'use client'` provider implements `dispatch` as a client
`fetch` to the already-injected route, reusing the app's existing
`sonner` toaster and React Query / `router.refresh()` data layer — the same UX
as the existing form-mutation path (`useEntityForm.ts` uses `toast` + RQ).

Alternatives considered and rejected:
- **B — Server Action calling `triggerWorkflow()` directly.** Purer RSC, no HTTP
  hop, but a new pattern, must verify the engine runs in an action context, and
  still needs a client wrapper for toast/refresh → strictly more surface.
- **C — default dispatcher baked into `packages/renderer`.** Most DRY, but
  couples a generic renderer to app-specific conventions (the `/api/workflows`
  URL contract and `sonner`). Wrong layer.

## 5. Changes (6 files)

### App templates — `backend/templates/app-foundation/`

1. **NEW `src/lib/WorkflowDispatchProvider.tsx`** (`'use client'`)
   - `useRouter()` (next/navigation), `toast` (sonner).
   - `dispatch = useCallback(async (name, args) => { ... })`:
     - guard: if `!name` return.
     - `await toast.promise(run, { loading: 'Running…', success: …, error: … })`
       where `run` = `fetch('/api/workflows/' + encodeURIComponent(name) + '/execute', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ input: args ?? {} }) })`,
       throwing on `!res.ok || result.error`.
     - on success: `router.refresh()`.
   - returns `<WorkflowDispatcherProvider dispatch={dispatch}>{children}</WorkflowDispatcherProvider>`.

2. **EDIT `src/lib/schema-page.tsx`**
   - Remove the server-side `dispatch` stub (lines ~39-50) and the direct
     `WorkflowDispatcherProvider` import/use.
   - Import the new client `WorkflowDispatchProvider` and wrap the rendered
     output: `return (<WorkflowDispatchProvider>{await SchemaRenderer({...})}</WorkflowDispatchProvider>);`
   - `SchemaRenderer` still runs server-side; its RSC output is passed as
     children to the client provider (valid App Router composition).

### Shared packages (pending-state UX)

3. **EDIT `packages/renderer/src/client/WorkflowDispatcher.tsx`**
   - `export type WorkflowDispatch = (name: string, args?: Record<string, unknown>) => void | Promise<void>;`
     (return a promise so callers can await; tolerate void for back-compat).

4. **EDIT `packages/library/src/components/Button/Button.tsx`**
   - Add local `const [running, setRunning] = useState(false)`.
   - In the workflow branch of `onClick`: `setRunning(true); try { await (dispatch?.(workflow, args)); } finally { setRunning(false); }`.
   - Render disabled + busy when `running || loading` (reuse existing
     `disabled`/`"…"`/`aria-busy` rendering).
   - `__dispatch` test hook preserved.

5. **EDIT `packages/library/src/components/Form/Form.tsx`**
   - `DeclarativeForm` (primary): make `onSubmit` await the dispatch; track local
     `submitting` state; disable the submit `<button>` while submitting.
   - Container mode: same await/disable treatment for consistency (still sends
     `{}` — payload unchanged, out of scope).
   - `__dispatch` test hook preserved.

### Build / distribution

6. Rebuild `packages/renderer` and `packages/library` (`tsc`), and confirm the
   app emitter re-vendors the built `dist` into generated apps (the
   `@tentoroforge/*` packages are vendored into `output/*`). Capture the exact
   re-vendor step during planning.

## 6. Data flow (primary case)

```
User fills declarative Form fields → submit
  → react-hook-form handleSubmit(values)
  → await dispatch(workflow, values)                  [shared WorkflowDispatcherContext]
        → POST /api/workflows/{workflow}/execute  body { input: values }
        → ok:   toast.success + router.refresh()       (refetch RSC data)
          fail: toast.error(message)
  → submit button disabled while the dispatch promise is pending
```

`values` keys are the field `name`s; the workflow receives them under `input`.

## 7. Error handling

- `fetch` non-2xx, `result.error`, or a thrown network error → `toast.error(message)`.
- Empty/missing workflow name → no-op (Form/Button already guard on `workflow`).
- App that declares no matching workflow → route returns an error → graceful
  error toast; no crash.

## 8. Testing

- **Form unit (declarative)** — render with `fields[]` + `workflow` + injected
  `__dispatch`; fill fields, submit; assert `__dispatch` called with the
  collected field values; assert submit button disabled while the returned
  promise is unresolved.
- **Button unit** — workflow `Button` with injected `__dispatch`; click; assert
  dispatch called with `(workflow, args)`; assert disabled while pending.
- **Provider unit** (jsdom; mock `fetch`, `next/navigation`, `sonner`) — assert
  POST to `/api/workflows/{name}/execute` with `{ input }`; `toast.success` +
  `router.refresh()` on 2xx; `toast.error` on failure.
- **Manual** — a generated app with a `createProduct` workflow + `products/form`
  schema: fill, submit, observe the network call, toast, and data refresh.

## 9. Risks

- **RSC composition**: passing the server-rendered `SchemaRenderer(...)` output
  as `children` of a client provider is supported, but verify against the actual
  Next.js version used by generated apps during implementation.
- **Vendoring**: changes to `renderer`/`library` only reach generated apps after
  rebuild + re-vendor — easy to miss; make it an explicit plan step and verify in
  the manual test against a freshly emitted app.
- **Workflow name vs id**: `dispatch` posts to `/api/workflows/{name}/execute`;
  `name` must equal the workflow id the engine loads (`/workflows/{id}.json`).
  Confirm the schema's `workflow` string matches the emitted workflow id.
