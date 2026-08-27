# Integrations Settings — design + slice plan

**Date:** 2026-07-22
**Branch:** forge-v3-smith-orchestrator-v2
**Status:** approved (design), in-progress (Slice 1)

## Problem

Every workflow node that talks to an external service (`send_email`, `ai_generate`,
S3 uploads, `send_sms`, Stripe, …) needs credentials. Today those credentials live
only in the generated app's `.env.local`, meaning:

- Non-dev users need shell access to configure integrations.
- Restart required for any change (Next.js reads `.env.local` only at boot).
- No structure — the user has to know which key each node needs.
- No pattern for per-tenant or per-user credentials later.

## Solution shape

Two orthogonal sources of truth, one resolver:

```
handler code           ─ getSecret("resend", "RESEND_API_KEY")
                           │
                           ▼
   ┌─────────────────────────────────────────┐
   │   integrations DB row (encrypted)       │  ◄── admin UI writes here
   │   process.env[KEY]                      │  ◄── developer/deploy sets here
   │   spec.default                          │  ◄── documented fallback
   └─────────────────────────────────────────┘
              first-wins order
```

**Handlers never care** which source won.

**A registry** (`node_config_specs.py`) is the single source of truth used for:
1. Emitting a sectioned `.env.local` with the right comments.
2. Generating the settings page's form fields (label / kind / required).
3. Validating that a plan's workflows have somewhere to get their keys from.

## Decisions locked (user-confirmed)

| Decision | Choice | Consequence |
|---|---|---|
| Encryption key | Derive from `NEXTAUTH_SECRET` via HKDF | Zero new env vars. Per-provider subkeys for defense in depth. |
| Access control | Admin-only (existing `role='admin'` gate) | Non-admins never see `/settings/integrations`. |
| UI grouping | One card per provider, multi-field | e.g. AWS S3 card holds bucket + region + access key + secret. Matches Zapier/n8n mental model. |
| Scope | Integration providers only (Resend, Anthropic, S3, Twilio, Stripe, …) | `DATABASE_URL`, `NEXTAUTH_SECRET`, `FORGE_URL` stay env-only — they bootstrap the app. |

## Architecture

### Storage

```sql
CREATE TABLE integrations (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider     TEXT NOT NULL,              -- 'resend', 'anthropic', 's3', ...
  key          TEXT NOT NULL,              -- 'RESEND_API_KEY', 'FORGE_EMAIL_FROM', ...
  value_ct     TEXT,                       -- ciphertext (nullable = "user cleared it")
  value_iv     TEXT,                       -- IV (base64)
  updated_at   TIMESTAMP NOT NULL DEFAULT now(),
  updated_by   UUID REFERENCES users(id),
  UNIQUE(provider, key)
);
```

`value_ct` is nullable so the UI can distinguish "not set" from "empty string".

### Encryption

```
master_secret = NEXTAUTH_SECRET
subkey        = HKDF-SHA256(master_secret, salt="forge-integrations-v1", info=provider)
ciphertext    = AES-256-GCM(subkey, iv, plaintext)
```

- Web Crypto only (`crypto.subtle`) — zero npm dep.
- Per-provider subkey means compromising one subkey doesn't decrypt another provider.
- `salt` is fixed and namespaced (`v1`) so we can rotate to `v2` later without breaking old rows.

### Resolver

```ts
// standalone-app/src/lib/integrations/resolver.ts
export async function getSecret(
  provider: string,
  key: string,
): Promise<string | undefined> {
  // 1. DB row (decrypted)
  const row = await db.query.integrations.findFirst({
    where: and(eq(t.provider, provider), eq(t.key, key)),
  });
  if (row?.value_ct && row?.value_iv) {
    try { return await decrypt(provider, row.value_ct, row.value_iv); }
    catch { /* fall through */ }
  }
  // 2. Env
  const env = process.env[key];
  if (env) return env;
  // 3. Documented default (from spec registry, mirrored client-side as a constant)
  return DEFAULTS[provider]?.[key];
}
```

Called once per handler invocation. No cross-request cache in v1 — DB round-trip
cost is negligible next to the actual API call the handler is about to make.

### API surface

- `GET /api/integrations` — admin-only; returns `[{provider, key, is_set, updated_at, updated_by_name}]`. **Never returns plaintext values** — even to admins. The UI shows "•••••••• Set" / "Not set".
- `PUT /api/integrations` — admin-only; body `{provider, key, value}`. Encrypts and upserts. `value: ""` clears the row.

### UI

`/settings/integrations` page schema, emitted at gen time:
- Route rendered only when `role === 'admin'` (existing gate).
- One `Card` per provider used by the plan's workflows.
- Card body = form fields derived from spec, each showing "Set" / "Not set" indicator + input.
- Save button per card → PUT to `/api/integrations`.

## Slice plan (6 slices, ~7-10 commits)

| # | Slice | Files | Test story |
|---|---|---|---|
| **1** | **Spec registry** | `backend/services/node_config_specs.py` (data), `backend/services/integrations_spec.py` (helpers) | Pure-Python unit tests: shape validation, `providers_used_by_plan()` helper |
| 2 | TS runtime | `standalone-app/src/lib/integrations/{schema.ts,crypto.ts,resolver.ts}.tmpl` | `node -e` smoke: encrypt round-trip, resolver fallback order |
| 3 | Handler shim | Patches in `standalone-app/src/lib/workflows/index.ts.tmpl` | Handler still returns success when DB empty (env fallback works) |
| 4 | Migration + API route | `backend/services/integrations_scaffold.py`, `standalone-app/src/app/api/integrations/route.ts.tmpl` | Post-gen writes files; migration syntax valid; admin gate honored |
| 5 | Settings page | Emit page schema from spec + used-providers list, add nav-flow entry | Page renders, admin sees all fields, non-admin gets 404 |
| 6 | Live E2E on 3ncq1pky | Hand-emit into existing app, save Resend key via UI, delete env var, create recruiter | DB-stored key wins, forge_notifications row NOT created after successful Resend send |

Every slice ships independently — existing apps keep working through Slice 3 (env
fallback). Slices 4-5 enable the UI. Slice 6 proves it end-to-end.

## Non-goals (v1)

- Per-user OAuth (Slack workspace tokens, Google-per-user). Needs a separate
  `user_credentials(user_id, provider)` table + OAuth handshake flow.
- Editor-side seeding. User configures post-generation via the app's own
  settings page.
- Rotation UI ("regenerate key"). Manual for now.
- Audit log of who changed what (updated_by is captured; a UI on top of it is v2).
- Multi-tenant scoping. Values are per-app, not per-tenant.

## Out of scope, deferred to later specs

- Provider auto-detection ("we see your workflows use Twilio — add an integration
  card even before the plan mentions it").
- Test-connection button per card ("send a test email").
- Encrypted export/import of all integrations for backup.
