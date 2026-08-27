# Document Intelligence

_Last built: 2026-08-15 16:54:31 UTC · Blueprint version 1 · Written by: generation · Log: 1 entry_

> Internal admin tool for uploading paper/PDF records, running OCR via PaddleOCR sidecar and AI field extraction, and searching the resulting structured and full-text content.

## Architecture
- Frontend: Next.js ^15.1.0 (App Router) + React ^19.0.0
- Backend: Next.js API routes + Drizzle ORM + PostgreSQL
- Auth: NextAuth
- Runtime: @tentoroforge/renderer

## Data Model

```mermaid
erDiagram
    Document {
        uuid id PK
        varchar originalFilename
        varchar fileUrl
        varchar mimeType
        integer fileSizeBytes
        varchar status
        text ocrText
        jsonb extractedFields
        integer confidence
        integer pageCount
        uuid uploadedBy FK
        timestamp processedAt
    }
    ProcessDocumentJob {
        uuid id PK
        uuid documentId FK
        varchar step
        timestamp startedAt
        timestamp completedAt
        text error
        timestamp createdAt
        timestamp updatedAt
    }
    User {
        uuid id PK
        text email
        text name
        varchar role
        timestamp createdAt
        timestamp updatedAt
        text password
        boolean isActive
    }
    Document }o--|| User : "uploadedBy"
    ProcessDocumentJob }o--|| Document : "documentId"
```

### Entities

| Entity | Columns | FKs | Purpose |
|---|---|---|---|
| **Document** | id, originalFilename, fileUrl, mimeType, fileSizeBytes, status, ocrText, extractedFields (+8 more) | uploadedBy→user | — |
| **ProcessDocumentJob** | id, documentId, step, startedAt, completedAt, error, createdAt, updatedAt | documentId→document | — |
| **User** | id, email, name, role, createdAt, updatedAt, password, isActive | — | — |

## Actors & Roles

- **admin**

## Pages

| Route | Type | Entity | Purpose / Title |
|---|---|---|---|
| `/documents` | — | Document | Documents |
| `/documents/upload` | — | — | Upload |
| `/documents/[id]` | — | Document | Documents |
| `/documents/search` | — | Document | Search |
| `/` | — | Document | Dashboard |
| `/login` | — | — | Login |
| `/admins` | — | User | admins |
| `/admins/new` | — | — | Admins New |
| `/documents/new` | — | — | Documents New |
| `/home/new` | — | — | Home New |
| `/Document/:id/edit` | — | Document | — |
| `/Document/new` | — | — | — |
| `/admins/:id/edit` | — | User | — |
| `/documents/:id/edit` | — | Document | — |
| `/home/:id/edit` | — | Document | — |
| `/shell` | — | — | App Shell |

### Page Details

#### `/Document/:id/edit` — Document-new
- Data sources:
  - `document` — get Document
- Workflows dispatched: UpdateDocument

#### `/Document/new` — Document-new
- Workflows dispatched: CreateDocument

#### `/admins/:id/edit` — admins/[id]/edit.json
- Data sources:
  - `user` — get User
- Workflows dispatched: UpdateUser

#### `/admins/new` — admins-new
- Workflows dispatched: CreateUser

#### `/admins` — admins-page
- Data sources:
  - `admins` — list User

#### `/documents/:id/edit` — documents/[id]/edit.json
- Data sources:
  - `document` — get Document
- Workflows dispatched: UpdateDocument

#### `/documents/[id]` — document-detail-page
- Data sources:
  - `document` — get Document

#### `/documents/new` — documents-new
- Workflows dispatched: CreateDocument

#### `/documents/search` — documents/search
- Data sources:
  - `documents_search_extracted` — list Document
  - `documents_search_needs_review` — list Document
  - `documents_search_extraction_failed` — list Document

#### `/documents/upload` — documents/upload
- Components: data

#### `/documents` — documents-list-page
- Data sources:
  - `documents` — list Document

#### `/home/:id/edit` — home/[id]/edit.json
- Data sources:
  - `document` — get Document
- Workflows dispatched: UpdateDocument

#### `/home/new` — home/new.json
- Workflows dispatched: CreateDocument

#### `/` — home
- Data sources:
  - `documentStat` — aggregate Document
  - `documentStat2` — aggregate Document
  - `documentStat3` — aggregate Document
  - `documentStat4` — aggregate Document
  - `documentByStatus` — series Document
  - `documentByCreatedAt` — series Document

#### `/` — dashboard-page
- Data sources:
  - `totalDocuments` — aggregate Document
  - `completeDocuments` — aggregate Document
  - `failedDocuments` — aggregate Document
  - `recentDocuments` — list Document
  - `Document_recent` — list Document

#### `/login` — login
- Components: email, text

#### `/shell` — App Shell

## Navigation

```mermaid
flowchart LR
    admins["admins<br/><small>/admins</small>"]
    admins_new["Admins New<br/><small>/admins/new</small>"]
    documents["Documents<br/><small>/documents</small>"]
    documents_detail["Documents<br/><small>/documents/[id]</small>"]
    documents_new["Documents New<br/><small>/documents/new</small>"]
    documents_search["Search<br/><small>/documents/search</small>"]
    documents_upload["Upload<br/><small>/documents/upload</small>"]
    login["Login<br/><small>/login</small>"]
    documents -->|button:Add Document| documents_new
    documents -->|link| documents_upload
    documents_upload -->|button:Cancel| documents
    documents_detail -->|button:Back| documents
    documents_search -->|button:Add Document| documents_new
    documents_search -->|link| documents_upload
    admins -->|button:Add User| admins_new
    admins_new -->|button:Cancel| admins
    documents_new -->|button:Cancel| documents
    login -->|submit:login| documents
```

## Workflows

| Workflow | Trigger | Inputs | Steps |
|---|---|---|---|
| **CreateDocument** | manual | originalFilename, fileUrl, mimeType, fileSizeBytes, status, ocrText, extractedFields, confidence | 3 |
| **CreateProcessDocumentJob** | manual | documentId, step, startedAt, completedAt, error | 3 |
| **CreateUser** | manual | email, password, name, role | 3 |
| **DeleteDocument** | manual | id | 3 |
| **DeleteProcessDocumentJob** | manual | id | 3 |
| **DeleteUser** | manual | id | 3 |
| **ProcessDocumentWorkflow** | api_event | — | 14 |
| **ReprocessDocumentWorkflow** | api_event | — | 5 |
| **UpdateDocument** | manual | id, originalFilename, fileUrl, mimeType, fileSizeBytes, status, ocrText, extractedFields | 3 |
| **UpdateProcessDocumentJob** | manual | id, documentId, step, startedAt, completedAt, error | 3 |
| **UpdateUser** | manual | id, email, password, name, role | 3 |
| **UploadDocumentsWorkflow** | api_event | — | 5 |

### CreateDocument

Create a Document record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_insert["Create Document"]
    n_end((("End")))
    trigger --> db_insert
    db_insert --> n_end
```

### CreateProcessDocumentJob

Create a ProcessDocumentJob record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_insert["Create ProcessDocumentJob"]
    n_end((("End")))
    trigger --> db_insert
    db_insert --> n_end
```

### CreateUser

Create a User record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_insert["Create User"]
    n_end((("End")))
    trigger --> db_insert
    db_insert --> n_end
```

### DeleteDocument

Delete a Document record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_delete["Delete Document"]
    n_end((("End")))
    trigger --> db_delete
    db_delete --> n_end
```

### DeleteProcessDocumentJob

Delete a ProcessDocumentJob record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_delete["Delete ProcessDocumentJob"]
    n_end((("End")))
    trigger --> db_delete
    db_delete --> n_end
```

### DeleteUser

Delete a User record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_delete["Delete User"]
    n_end((("End")))
    trigger --> db_delete
    db_delete --> n_end
```

### ProcessDocumentWorkflow

Core async pipeline: marks document processing, calls PaddleOCR sidecar, runs AI extraction, persists results. Sets status=failed on any error.

```mermaid
flowchart TD
    trigger(["Trigger"])
    set_processing["Set Processing"]
    update_job_started["Update Job Started"]
    call_paddleocr["Call Paddleocr"]
    ocr_success_gate["Ocr Success Gate"]
    update_job_step_ai["Update Job Step Ai"]
    ai_extract_fields["Ai Extract Fields"]
    persist_results["Persist Results"]
    update_job_done["Update Job Done"]
    notify_complete["Notify Complete"]
    set_failed["Set Failed"]
    update_job_failed["Update Job Failed"]
    notify_failed["Notify Failed"]
    n_end((("Complete")))
    trigger --> set_processing
    set_processing --> update_job_started
    update_job_started --> call_paddleocr
    call_paddleocr --> ocr_success_gate
    ocr_success_gate --> update_job_step_ai
    ocr_success_gate --> set_failed
    update_job_step_ai --> ai_extract_fields
    ai_extract_fields --> persist_results
    persist_results --> update_job_done
    update_job_done --> notify_complete
    notify_complete --> n_end
    set_failed --> update_job_failed
    update_job_failed --> notify_failed
    notify_failed --> n_end
```

### ReprocessDocumentWorkflow

Resets a failed or complete document back to queued status and dispatches a new ProcessDocumentJob.

```mermaid
flowchart TD
    trigger(["Trigger"])
    reset_document["Reset Document"]
    insert_reprocess_job["Insert Reprocess Job"]
    notify_requeued["Notify Requeued"]
    n_end((("Complete")))
    trigger --> reset_document
    reset_document --> insert_reprocess_job
    insert_reprocess_job --> notify_requeued
    notify_requeued --> n_end
```

### UpdateDocument

Update a Document record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_update["Update Document"]
    n_end((("End")))
    trigger --> db_update
    db_update --> n_end
```

### UpdateProcessDocumentJob

Update a ProcessDocumentJob record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_update["Update ProcessDocumentJob"]
    n_end((("End")))
    trigger --> db_update
    db_update --> n_end
```

### UpdateUser

Update a User record.

```mermaid
flowchart TD
    trigger(["Start"])
    db_update["Update User"]
    n_end((("End")))
    trigger --> db_update
    db_update --> n_end
```

### UploadDocumentsWorkflow

Accepts multipart file upload, writes a Document row per file at status=queued, dispatches ProcessDocumentWorkflow per document.

```mermaid
flowchart TD
    trigger(["Trigger"])
    insert_document["Insert Document"]
    insert_job["Insert Job"]
    notify_queued["Notify Queued"]
    n_end((("Complete")))
    trigger --> insert_document
    insert_document --> insert_job
    insert_job --> notify_queued
    notify_queued --> n_end
```

## Design

### Palette

| Role | Color |
|---|---|
| brand | `#0F4C75` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%230F4C75%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| accent | `#0369A1` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%230369A1%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| surface_bg | `#F4F7FA` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%23F4F7FA%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| surface_elevated | `#FFFFFF` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%23FFFFFF%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| foreground_primary | `#0D1B2A` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%230D1B2A%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| foreground_muted | `#4A5E72` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%234A5E72%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |
| neutrals_base | `#E8EDF2` ![](data:image/svg+xml,<svg%20xmlns=%27http%3A//www.w3.org/2000/svg%27%20width=%2714%27%20height=%2714%27><rect%20width=%2714%27%20height=%2714%27%20fill=%27%23E8EDF2%27%20stroke=%27%2523888%27%20stroke-width=%270.5%27/></svg>) |

### Typography
- display_family: `DM Sans`
- body_family: `IBM Plex Sans`
- utility_family: `IBM Plex Mono`
- scale: `conservative_1.20`

### Layout
- density: `comfortable`
- radius: `sharp_2`

## Uncovered Artifacts

_These artifacts exist on disk but no other blueprint section references them. A non-empty list here means the app is out of sync with its authoring surface — either the blueprint needs a rebuild or the orphan needs to be deleted / wired in._

### Pages (1)
- `src/schemas/index.json`

## Generation Log

| When | Source | Summary |
|---|---|---|
| 2026-08-15 16:54:31 UTC | generation | Full generation (194 guard(s) applied) |
