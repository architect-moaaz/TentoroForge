# Payment gateways: set up once, chosen per app, built in when an app takes money

Builds on what already takes money in a generated app: the ledger
(`forge_payments`), hosted checkout through `create_checkout`, signed webhooks
at `/api/webhooks/<integration>`, and the stand-in that takes a payment before
any key is set. That was one provider (Stripe), one-time payments only, keys
typed into a long list under Settings → Integrations, and nothing that asked
the owner which account an app should be paid into.

## What the owner gets

| Stage | What happens |
|---|---|
| **Settings → Payments** (organisation) | Add as many gateways as the business uses: Stripe, Razorpay, PayPal. Each has a name, where it takes money (domestic, international or both, with a home country), its currencies, and two sets of keys: **test** (for previews and the test version) and **live** (for production). Keys are checked against the gateway the moment they are saved: the card says *Verified — Acme Pvt Ltd, test mode* or exactly what is wrong. One is the default. |
| **While an app is being made** | Forge works out from the request and the definition whether the app takes money, and how: one-time payments (an order, a booking, a fee), subscriptions (memberships, plans), or both. It says why in a sentence. |
| **"Build app"** | When the app takes money, a dialog asks which gateway(s) it should be paid into, before anything is built. The best choice is already ticked: the default gateway, or a domestic and an international one together. Subscriptions show their plans (name, price, every month/year), editable there. Choices: build with these, or build without payments. With no gateway set up yet, the dialog says so and offers to set one up (opens Settings, comes back ticked) or to build now with test payments and connect later. |
| **The built app** | A payer is sent to the gateway's own secure page (no card ever touches the app). With two gateways the app routes each payer automatically: the domestic gateway for payers in its home country or currency, the international one for everyone else. Subscriptions get a pricing page, a billing page (current plan, next charge, cancel), and access that follows the subscription. |
| **Publish** | Test keys go to the test version and live keys to production; never the other way. Forge registers the app's webhook with Stripe and PayPal itself; for Razorpay it shows the exact address, secret and events to paste once. Payments confirm even before a webhook arrives (see Robustness). |
| **Later** | Every app has a **Payments** panel: turn payments on, change gateways, edit plans. Smith notices when a change makes an app take money ("add a premium plan", "charge for bookings") and asks which gateway, with the same choices. |

## Design

**Gateways are the organisation's; an app references them.**
- Table `payment_gateways` (one row per connected account): provider, label,
  coverage (`domestic` / `international` / `both`), home country, currencies,
  default flag, test and live credentials (encrypted with the platform's
  integrations key, per-row subkey), what each verification found (account
  name, mode, when), soft delete. Admin-only. Values are never returned; a
  key is shown as its last four characters.
- Verification is one read-only call per provider and mode, through one
  module (`services/payments/gateways.py`). A key in the wrong slot (a live key
  saved as test) is refused with that sentence.

**The Blueprint records the decision (`payments`).**
`needed`, `models` (`one_time`, `subscription`), `reason`, `decidedBy`
(`forge` / `person` / `smith`), `gateways` (platform gateway id, provider,
label, coverage, currencies), `routing` (`auto`), `plans` (id, name, interval,
price, currency, trial days, features, highlighted), `access` (`app`: an
active subscription is needed to use the app beyond pricing and billing;
`none`: plans are offered, nothing is locked). One integration row per chosen
provider (`serves: take_payment`) is derived from it, so the existing checks,
`connected.ts` and the workflow agent's `create_checkout` keep working.

**Deciding whether an app takes money** (`services/payments/need.py`): the
person's words first ("no payments", "free"), then a model reading the
request, requirements and product model against a fixed JSON contract
(needed, models, reason, plans, access), checked against deterministic
signals (a `create_checkout` step, a Plan/Subscription/Order record with a
price, words like subscribe/membership/checkout/fee). Without a model it falls
back to the signals alone. Decided once at the product-model review and
recorded; re-decided when the definition changes, never over a person's own
choice.

**The app's runtime.**
- `payments/` gains Razorpay and PayPal adapters beside Stripe, subscription
  methods on each (plan provisioning, subscribe, retrieve, cancel), a
  `confirm` that asks the gateway for the truth, and a router that picks the
  gateway per payer.
- `billing/`: plans projected from the Blueprint, `forge_subscriptions` and
  `forge_plan_refs` (a plan's id at each gateway, created once, reused; keyed
  by the account a key belongs to, so new keys for another account make their
  own plans), and routes: subscribe, return, cancel, status, access, manage.
  One runtime page, `/billing` (plans, the current plan, its next charge or
  end, cancel), the same in every app, styled by the app's tokens; `/pay/*`
  hosts Razorpay's checkout window and the stand-in.
- `access: "app"` is a gate in the app's middleware: a signed-in person
  without a plan reaches only signing in, billing and paying (pages redirect
  to `/billing`, APIs answer 402 `SUBSCRIPTION_REQUIRED`); the app's operators
  are not asked. It reads a short-lived `forge_access` cookie signed with the
  app's secret, and checks the subscription itself when the cookie is missing
  or expired.

**How a subscription ends**
- Cancel at the period's end (the default): access stays until the end paid
  for; asking again sends nothing. Cancel now: access ends at once, even
  after an earlier "at the period's end". A plan that is ending cannot be
  taken again until it ends (it would be charged twice for one period).
- The end is the gateway's own: Stripe's and Razorpay's `ended_at` for one
  cancelled now; PayPal reports no next billing time once cancelled, so a
  known end is never erased by an unknown one.
- A plan or subscription the gateway no longer knows (archived, or the keys
  now point at another account) does not block anyone: the plan is made
  again once and the payer goes on; a cancel ends the subscription here,
  keeping what was paid for until its end. An outage is still an error to
  try again.
- Refunds name their amount and currency (PayPal refunds everything when no
  amount is sent); a partial refund whose currency cannot be known is
  refused.

**Robustness**
- A payment is believed only from the gateway: its signed webhook, or a
  server-side read of the payment when the person returns (Stripe session,
  Razorpay payment link + signature, PayPal capture). So payments work in a
  local preview, where no webhook can arrive, and before Razorpay's webhook is
  pasted in.
- Every outcome is settled once (ledger state machine; webhook dedupe on the
  event id); a late or repeated event never moves a payment backwards.
- Amounts in minor units at the gateway, zero-decimal currencies respected.
- Subscription access is read from the app's own table; when the period has
  passed with no renewal heard, the gateway is asked before access is denied.
- Test keys never reach production and live keys never reach a preview or
  the test version.

## Build order
1. Migration + model + service + router for gateways; verification per provider.
2. Settings → Payments page.
3. Blueprint `payments` section (Zod, JSON contract) + need detection + gate payload.
4. Runtime adapters (Razorpay, PayPal), subscriptions, routing, pages; injector + sync.
5. The dialog at "Build app" and the server-side gate; projection into the app.
6. Env for preview / test / production; webhook registration at publish.
7. Smith: set up payments, sense the need, the Payments panel.

## Tests
- Unit: crypto round trip, masking, every verification answer (valid, invalid,
  wrong mode, gateway down) through a mocked transport, the auth matrix
  (admin, member, other organisation), need detection over a set of app
  briefs, Blueprint validation, env per side.
- Runtime (vitest): each adapter's requests against the gateways' documented
  shapes, signature verification with real HMACs (valid, tampered, stale),
  normalised events, routing, the subscription state machine, duplicate and
  out-of-order webhooks.
- End to end: a local gateway emulator speaking the documented Stripe,
  Razorpay and PayPal endpoints; a built app pays and subscribes through each
  and renews, fails and cancels by signed webhook.
- Browser: settings (add, verify, wrong key, default, delete), the dialog on
  a real Kimi build of a subscription app and of an app that takes no money.
- The full backend suite, tsc and vitest, compared with the baseline.

## Where it lives
- Platform: `backend/services/payments/` (`providers` catalog + key checks, `gateways` store, `need` decision,
  `app_payments` Blueprint record / agent notes / app files / env by side / build question / Smith sensing,
  `webhooks` registration), `backend/routers/payment_gateways.py`, migration `pg1030_payment_gateways`,
  Smith verb `set_up_payments` (`services/smith/payments_setup.py`).
- App runtime: `backend/templates/runtime/payments/` (`stripe`, `razorpay`, `paypal`, `stand-in`, `routing`,
  `units`, `billing`), `api-billing/*`, `api-pay/{return,confirm,stand-in}`, `pages/billing`, `pages/pay/*`,
  `db/forge-billing.schema.ts`. Installed by `app_payments.install_runtime` (build, Smith's sync, publish).
- Frontend: Settings → Payments (`app/org/[orgId]/settings/payments`), the build dialog and the app's Payments
  tab (`components/payments/*`), the shared rule (`lib/payment-gateways.ts`).

## Testing locally without gateway accounts
`backend/scripts/payments_emulator.py` answers the Stripe, Razorpay and PayPal endpoints Forge and the apps
call, serves stand-ins for their checkout pages and signs webhooks as they do. Run it, then set
`FORGE_PAYMENTS_EMULATOR=http://127.0.0.1:6599` for the backend and `FORGE_PAY_EMULATOR=http://127.0.0.1:6599`
in an app's `.env.local`. Any key works except one containing "bad". Never set either in production. Its
state is in memory: after a restart it knows none of the subscriptions it made, as a gateway would for
another account's.

Checked end to end on 4 November 2026 against a built app (Task Board) and its own Postgres: subscribe,
renew, fail, cancel at the end and now through each of the three gateways; webhooks (unreturned payer,
renewal, past due, replayed, tampered, stale, wrong secret); the gate; one-time payments through Razorpay
and Stripe (forged and swapped signatures refused, paid once, cancelled); refunds; the billing page in a
browser through a subscribe and a cancel.

Tests: `tests/routers/test_payment_gateways_api.py`, `tests/services/test_an_app_takes_money_the_way_its_owner_chose.py`,
`templates/runtime/__tests__/run-payment-tests.sh`, `frontend/src/__tests__/a-payer-goes-to-the-right-gateway.test.ts`.

## Known limits (v1)
- Razorpay webhooks are pasted by the owner once (Razorpay registers webhooks by API only for its partners);
  payments are confirmed on the payer's return until then.
- The test version is a Vercel preview: Deployment Protection, if switched on, answers gateway webhooks 401.
  Payments are still confirmed on return; renewals on the test side need the protection bypass.
- Stripe allows 16 webhook endpoints per account and PayPal 10 per app: an organisation publishing more apps
  than that on one account needs a relay (not built).
- Switching plans starts the new plan at once and stops the old one renewing (no proration).
