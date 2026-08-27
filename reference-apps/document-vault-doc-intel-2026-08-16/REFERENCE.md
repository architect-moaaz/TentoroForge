# Document Vault — reference app

**Snapshot date:** 2026-08-16
**Source project id:** `9y8de8i7`
**Archetype:** document-intelligence (uploaded PDF → OCR → AI field extraction → key/value display)
**Preserved on branch:** `ui-simplified`

This is a frozen, working copy of the generated app kept for reference. It's the
first fully-working doc-intel app the platform produced and is the anchor for
every fix that landed in platform source on the same day (see "Platform back-ports"
below). Do NOT edit files here to fix new bugs — fix at the platform, regenerate,
compare against this reference.

## What the app does

1. User drops a PDF (Housing Bank slips, invoices, receipts — any doc-intel target)
   into the `FileUpload` widget on `/`.
2. `FileUpload` uploads the bytes to `/api/files/upload`, gets back a `fileId`,
   and ships the id plus derived `originalFilename` and `mimeType` as hidden
   form inputs.
3. The `Form` dispatches the `ProcessDocument` workflow with those three fields.
4. The `?detach=1` execute route returns HTTP 202 immediately (~200ms) so the
   user is navigated to `/documents` instantly; the pipeline runs in the
   background.
5. Workflow steps:
   - `insert_document` — row with status=queued, `{{originalFilename}}`, `{{fileId}}`, `{{mimeType}}`
   - `set_processing` — flip status
   - `call_paddleocr` — PaddleOCR sidecar (docker container `forge-paddleocr`)
     returns text + confidence + pageCount
   - `ocr_success_gate` — branches on `confidence > 0`
   - `ai_extract_fields` — Claude vision reads the ATTACHED PDF directly via
     `aiFileRef: "{{fileId}}"` (Arabic/CJK-safe; ignores OCR text quality) and
     emits a flat JSON of key→value strings
   - `persist_results` — writes `ocrText`, `extractedFields` (jsonb),
     `confidence` (real), `pageCount`, `processedAt`, status=complete
6. `/documents` list shows all uploaded docs (row-click navigates to detail).
7. `/documents/[id]` detail page shows:
   - Filename + status badge
   - "Processing failed" Alert (only when `errorMessage` present — resolved-to-null
     no longer misfires the Alert)
   - Preview card: "Open PDF ↗" button + inline `<object>` PDF embed via
     `/api/files/preview?src={{document.fileUrl}}` (proxy accepts UUID or URL)
   - Extracted fields card: `DescriptionList` with
     `dataSource: "{{document.extractedFields}}"` + `itemMode: "entries"` +
     `emptyText: "No fields extracted yet."`
   - OCR confidence card: DescriptionList with items array
   - Raw OCR text accordion: CodeBlock

## Platform back-ports this app anchors

Every deviation from a stock generated app now lives in platform source. If a
future regen doesn't match this reference's behavior, the platform edit is the
place to look.

**TypeScript packages** (rebuilt + re-vendored into this reference)
- `FileUpload.tsx` — hidden `originalFilename` + `mimeType` inputs.
- `CustomBlock.tsx` — post-mount DOMPurify (SSR-safe) + iframe/object/embed
  allowlist + `target` attr.
- `buildDefaultRegistry.tsx` — CustomBlock registered.
- `Conditional.tsx` (renderer) — distinguishes missing `when` from resolved-null
  values; treats URLs / ids / filenames as JS-truthy instead of choking on them
  in FEEL-lite.
- `DescriptionList.tsx` — accepts `dataSource` object with `itemMode:"entries"`
  + `{label,value}` shape + `emptyText`.
- `WorkflowDispatcher.tsx` — new `detach: boolean` option that appends
  `?detach=1` for fire-and-forget dispatch.

**Runtime templates** (copied verbatim into every generated app)
- `workflows/index.ts` — sole-template short-circuit returns raw values (jsonb
  writes get real objects, not `"[object Object]"`).
- `rules/engine.ts` — numeric-range checks coerce string→number.
- `api-files/preview-route.ts` — new unified preview endpoint (accepts UUID or URL).

**Emitters** (Python generators in `backend/services/`)
- `runtime_injector.py` — emits preview route into every app; execute route
  supports `?detach=1`.
- `schema_builder.py` — semantic guard promotes `confidence` / `score` /
  `probability` / `ratio` / `percent` fields from integer to `real`.

## What this app is NOT

- Not a first-class `document-intelligence-platform` archetype. The registry
  in `backend/services/archetype_workflows/__init__.py` doesn't have a doc-intel
  entry yet — the `ProcessDocument` workflow here was authored via the general
  planner. If/when a proper archetype is added, use this app as the desired
  output shape.
- Not committed with real business data. The DB was cleared before the snapshot;
  bring your own PDFs.
- Not a template for the schema builder — the `documents` entity's `createdAt`
  column had to be repaired at the DB level (`ALTER TABLE documents ALTER
  COLUMN created_at SET DEFAULT now()`). The plan schema for this entity is
  slightly non-standard; if you regenerate, verify the auto-appended timestamps
  fire (schema_builder auto-appends `.defaultNow().notNull()` if the entity
  doesn't declare its own timestamps).

## Running locally (for spot-checking)

```bash
cd reference-apps/document-vault-doc-intel-2026-08-16
npm install
docker compose -f docker-compose.yml up -d       # Postgres on :5433 → 5434
docker run -d --rm --name forge-paddleocr -p 8000:8000 <paddleocr-image>
npm run db:migrate && npm run db:seed
npm run dev                                       # → http://localhost:3000
```

Log in as `admin@example.com / admin1234`.

## Provenance

- Original project id: `9y8de8i7`
- Generated by the general planner pipeline (not a doc-intel archetype)
- Hand-repaired during a session on 2026-08-16 to prove the end-to-end
  upload → OCR → AI extract → display flow was feasible; every repair was
  then back-ported to platform source in the same session.
- The vendored `@tentoroforge/*` dists carry the platform-edit-compiled code
  as of the snapshot time.

## When to update this snapshot

Refresh this reference (delete + re-copy from a freshly regenerated doc-intel
app) when:
- The doc-intel archetype becomes a first-class emitter, OR
- The reference's behavior would benefit from a fresh compare against a
  post-fix regen, OR
- A user-facing UI/component shape lands in the platform that changes what
  a working doc-intel app looks like.

Do NOT refresh for cosmetic-only changes — the reference's job is to anchor
behavior, not chase style updates.
