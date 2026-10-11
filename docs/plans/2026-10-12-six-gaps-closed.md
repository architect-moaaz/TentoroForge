# Six gaps closed: what landed on `smith-revamp` on 2026-10-12

Companion to `2026-10-11-what-forge-builds-today.md`, which named the gaps. This records what was
built against each, where it lives, how it is proven, and what is still unverified live.

Every part follows the same shape: a contract field declared first (`packages/schema/src/blueprint/blueprint.ts`,
then `npm run emit:blueprint-schema`); a neutral paragraph for the agent that decides it; a refusal in
`services/blueprint/agent_contract.py` for what the runtime could not serve; a projection into the app; a runtime
piece under `templates/runtime` or `templates/app-foundation`; a check on a Bench that lands on the scorecard; a
Smith verb in both corpora. Nothing is flag-gated.

| Part | Commit | Contract | Runtime | Check (criterion) | Smith |
|---|---|---|---|---|---|
| Groundwork | be9f49d0 | `end.reply`/`redirect` | machine routes open, declared secrets settable, adapter registry, no forgeable actor | — | `connect_service` over adapters |
| Clock | 4bb2f827 | `trigger.cron/entity/on/event`, `wait.for/until`, `dueIn`, `escalateTo` | cron tick, durable `wait_timer`, escalation, `CRON_SECRET` | `clock_check` (systems) | `set_schedule`, `pause/resume_schedule`, `run_now`, `set_deadline` |
| Other systems | 3ae65c16 | `Integration.inbound`, `http_call.auth{secretRef}` | `/api/webhooks/[integration]` (HMAC/bearer/provider), replay guard | `webhook_check` (systems) | `add_webhook`, declared systems |
| Audit | 79b3a9c5 | `security.audit`, `Entity.appendOnly`, `Field.mask/readers`, `audit_trail` page | `forge_audit` chain, immutable, `/api/audit` | `audit_check` (audit) | `show/export/verify/edit_audit` |
| Payments | 74cd98c1 | `type: money`, `product.currency`, `create_checkout`… | adapters `{stripe, stand_in}`, `forge_payments`, stand-in page | `payment_check` (systems) | `connect_service` Stripe, `refund`, `set_currency` |
| Tenancy | c5aadb03 | `Entity.tenant`, `security.tenancy` | `forge_memberships`, `users.active_org_id`, derived workspace scopes, signup/invite/switch | `tenancy_trials` (access) | `add_organisation`, `move_login` |
| SSO | 29972bf6 | `security.signIn {password, magicLink, sso[]}` | `auth.ts` providers from names, `/api/auth/magic`, `/api/auth/methods`, BoxyHQ for SAML | `sso_check` against `/dev/mock-idp` (routes) | `connect_service` sign-in adapter, `set_sign_in_method`, `map_sso_roles`, `restrict_sign_in_domains` |
| Mobile | (this commit) | `mobile {installable, display, orientation, push, store}`, `send_notification.channels` | manifest, icons, shell-only `sw.js`, `/offline`, `push.ts`, `/api/push`, VAPID keys per app | `pwa_check` installable (routes) + push (systems) | `edit_mobile`, `test_notification` |

## Decisions taken while building

- **Secret names live in the Blueprint, values on the platform.** An entry's names are derived (`SSO_<ID>_ISSUER`,
  `STRIPE_SECRET_KEY`), registered as settable under `app:<slug>` (`services/declared_secrets.py`), and the check
  never holds a real value: webhooks are proven with a per-bench signing secret, sign-in against the platform's
  mock issuer, push against a listener the check runs.
- **SAML is OIDC to the app.** The app speaks OpenID Connect to BoxyHQ Jackson (compose service `jackson`, profile
  `sso`); the mock issuer answers Jackson's paths too, so one check covers both.
- **A publish pins `NEXTAUTH_URL` only when a provider must send people back** (`services/deploy/sign_in_address.py`),
  to the project's production alias; otherwise it stays unset as before.
- **Push keys are the app's own and never rotate on a rebuild** (`services/push_keys.py`, `assembly._SECRET_KEYS`,
  shipped by the Vercel provider when the deployment lacks them).
- **The service worker keeps the shell, never the data**: `/api/**` and HTML are never cached; navigations are
  network-first with `/offline` as the fallback.
- **A DAG node may declare `defaulted` sections** (`mobile`): sections whose absence means their defaults, so a
  resumed build does not re-run the product analysis over a document written before the section existed.

## Unverified live

- forge-v3 runs b12b9f04 (before every part here); none of this is deployed, and nothing is pushed.
- A real Stripe webhook and a real identity-provider redirect need a publish (the preview sits behind the platform).
- The Jackson bridge has never been started; `register_saml` is exercised only against a stub.
- The Expo store wrapper is not built: `mobile.store` is a contract field only.
- Suite: the 79-failure baseline at b12b9f04 is unchanged except the environmental `a465s2ht` case.
