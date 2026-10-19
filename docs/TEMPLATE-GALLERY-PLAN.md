# Template Gallery: review, publishing, ratings

Turns "Save as template" (PR #25, org-private templates) into a reviewed, public
Templates Gallery. Built on smithv5.

## The eight asks, and where each is answered

| # | Ask | Answer |
|---|-----|--------|
| 1 | A template made from an app goes to the Tentoro admin for approval | **Submit for review** sends the request to every super admin (`FORGE_SUPER_ADMIN_EMAILS`, default `admin@tentoro.ai`). Only approved templates reach the Gallery. |
| 2 | The requester sees the status of the request | Status badge on every template in **Your templates** (Draft, In review, Approved, Changes needed, Removed), plus a history of each step with the admin's note. The requester is also notified when it changes. |
| 3 | admin@tentoro.ai is notified | In-app notification (new bell in the sidebar) **and** an email to every admin address. Email is logged in development and goes out through SendGrid or SMTP in production. |
| 4 | Admin reviews the app; the requester adds screenshots and the template is validated; free or paid later | The submit wizard has three steps: Details → Screenshots (upload, or "add the app's own screens" from the build) → Checks. The checks run on the server: a definition with screens and records, at least one screenshot, a description, no secrets. Pricing is stored (`free`/`paid` + amount + currency). Only *Free* can be chosen today; *Paid* shows as "coming soon". The admin's review page has the full preview, the screenshots, the checks, the history, **Open a test copy** (builds the exact app in the admin's own organisation, not counted as a use), and Approve or Request changes (a reason is required). |
| 5 | Approved, it joins the Gallery: screenshots, data models, workflows, screens, description; the card shows who built it, when, and its version | **Gallery** section: cards with a cover screenshot, builder, date, `vN`, uses and rating. The detail view has a screenshot carousel, description, and tabs for Screens, Data models (with fields), Workflows (with steps), Roles and rules, and Reviews. |
| 6 | Show how often the template has been used | Each project made from it is recorded once (`template_uses`). The card and detail show "Used N times". The admin's test copies are not counted. |
| 7 | The builder's profile is viewable from the card | Clicking the builder's name opens their profile: name, avatar, member since, organisation, published templates, total uses and average rating. It is only shown for people with a published template, so it can't be used to look anyone up. |
| 8 | Ratings and feedback | 1–5 stars plus an optional comment, one per person per template (they can edit or delete it). Builders can't rate their own. Each review shows "Used this template" when the reviewer did. The builder is notified of new feedback. |

## Design

**Two stores, each owning what it is good at.**
- *Disk* (`output/_templates/<id>/`) keeps what a template **is**, as it does today: `blueprint.json`, `ids.json`, `patches.json`, `brand/`, and now `screenshots/`. `meta.json` gains `version`, `lineage` and `screenshots`.
- *Postgres* keeps what happens **to** it, across organisations and people at once: the listing status, review decisions and history, uses, and ratings. All of these need atomic, concurrent writes and queries across every org.
- A template saved before this change, or by Smith from a chat turn (no DB session there), has no row yet. It reads as **Draft** and the row is created when it is first submitted. Nothing needs backfilling.

**Status machine** (server-enforced; any other move is a 409):

```
draft ──submit──▶ pending ──approve──▶ approved ──remove──▶ removed
  ▲                 │  └──reject──▶ rejected                  │
  └──cancel request─┘        └───────resubmit──▶ pending ◀────┘ (resubmit)
approved (older version) ──newer version approved──▶ superseded
```
Content (name, description, screenshots) can be edited in draft, rejected,
removed or pending. It is locked once approved: a change becomes a new version.

**Versions.** A template saved again from the same app is the next version of the
same *lineage* (`org:source_project`). The Gallery shows the newest approved
version of each lineage. Uses and ratings are counted across the lineage, so a
new version keeps its history. Approving v2 marks v1 superseded. Projects already
made from v1 keep their own copy.

**Who sees what.**
- The template's own organisation sees all its templates in any status.
- Super admins see everything.
- Everyone signed in sees approved templates.
- Anyone else gets a 404, as today, so a private template's id reveals nothing.

Using a template follows the same rule: your own org's templates in any status,
anyone's approved templates, and an admin's test copy of anything.

**Safety.**
- Screenshots: PNG, JPEG or WebP only, checked by their bytes (not the filename), up to 5 MB and 8 per template. They are stored under generated names and served only through an authenticated route that applies the visibility rule above.
- Secret scan before submission: the definition and Smith's file edits are scanned for key shapes (`sk-…`, `AKIA…`, `ghp_…`, private-key blocks, Slack and Stripe live keys). A match blocks submission and names where it was found.
- Template ids are validated as 32 hex characters, as today.

## Build order

1. Migration `tg1017_template_gallery` and models `TemplateListing`, `TemplateEvent`, `TemplateUse`, `TemplateReview`.
2. Service `services/template_gallery.py`: the status machine, checks, secret scan, visibility, stats, notifications (in-app + email), and screenshot storage.
3. Router: submit / cancel / screenshots / detail / reviews / gallery / creator profile, plus admin routes under `/api/admin/template-requests`.
4. Smith's "save as template" says that it saved a private draft and how to publish it.
5. Frontend:
   - submit wizard
   - status and history in Your templates
   - Gallery cards and detail view
   - creator profile
   - reviews
   - notification bell
   - admin page `/admin/templates`
6. Tests:
   - unit tests for the service
   - API tests for every route and every refusal
   - end-to-end against the running Forge with three real accounts (builder, admin, a person in another org)
   - a browser walk-through of every screen
   - Smith on Kimi

## Hardening pass (2026-10-19, on smithv5 c764d796)

smithv5 brought a redesigned project page (tabs across the top, a More menu);
"Save as template" stays in its header. Every ask is tested again from scratch,
aimed at what the first pass did not reach:

| Area | How it is tested |
|---|---|
| Every route × every kind of person | A matrix test: builder, org member (not builder), org admin, outsider, Tentoro admin, Tentoro admin **impersonating** someone, signed out — each against every template route, with the answer each must get. |
| Two people at once | Against the real Postgres, concurrently: two admins deciding one request, a double-clicked Submit, a double-clicked rating, two saves. Exactly one wins; nothing answers 500. |
| Email really leaves | Forge's production SMTP path pointed at a local mail sink: the admin's and the builder's emails arrive with the right subject, link and escaped text. |
| A Gallery template becomes a working app | Another organisation uses an approved template, Smith (Kimi) is told "the exact same app", it is built, and its preview runs. |
| Every screen, every state | In the browser, through the redesigned project page: save → publish wizard (upload, reorder, remove, app screens) → admin asks for changes → builder resubmits → admin approves → another org uses and rates it → builder takes it out of the Gallery → deletes it. |
| A full Gallery | 30 approved templates: every cover loads, nothing answers 429, and the page and its API stay fast. |
| Edges | Templates saved before the Gallery existed; a template whose files were removed; oversized fields; ids that try to walk out of the folder; markup in names. |
| Regressions | The full backend suite against a clean smithv5 checkout, test by test; type-check of the frontend. |
