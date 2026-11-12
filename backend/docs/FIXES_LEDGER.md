# Fixes ledger: what was found building and testing apps, and where each fix lives

Every bug found while building and testing an app with Forge goes here, with where the fix lives:

- **Forge**: fixed in the platform (templates, projection, agent teaching), so every app built from now on has it. It
  names the regression test that keeps it fixed.
- **App only**: fixed by hand in one generated app. A new app built with Forge will NOT have it. It stays on the list
  until it is moved into Forge.

Rule: a fix that lands only in an app is not finished. Add a line under "App only" the moment you make it, and move it
when it is ported.

Test app: ride-hailing platform (driver app and admin dashboard), `output/n2xcrvt5`, branch `smithv5-realtime`.
Dates are 2026-11.

## In Forge (every new app has these)

Live tracking and maps
- A driver's live position reaches the admin's map without a page refresh, and a driver who goes offline leaves it
  within seconds (fleet route rechecks duty). Test: `test_live_tracking_is_offered_to_the_page_agent.py`,
  `a-fleet-shows-only-people-on-duty-whom-the-viewer-may-see.test.mts`.
- Empty map no longer blank: world view, then zoom to the first pin. A single "Go online" beacon, not two.
- Google Maps is an optional second map (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`); the free map stays the default and takes
  over if Google refuses the key. Routes, distance and arrival time from Google Routes (`GOOGLE_MAPS_SERVER_KEY`),
  then a free routing service, then a straight line, always saying which. Key never reaches a browser response or a
  log. Test: `test_maps_can_be_google_and_routes_have_a_time.py`, `the-road-between-two-places.test.mts`.

Security
- Any signed-in user could run admin workflows (empty `LAUNCH_ROLES`). Fixed in projection (`PROJECTED_PATHS`).
- Uploaded files were served inline with any type. Allowlist, nosniff, attachment, sandbox. Test:
  `test_the_ride_hailing_build_found_five_platform_bugs.py`.
- A driver could read other drivers' assigned rides, with the customer's name and phone. New ownership option
  `readsUnclaimed`: reads reach my rows and rows nobody holds yet; writes stay mine. The blueprint agent is told to
  use it for offered work. Test: `test_offered_work_is_read_by_its_holder_and_emails_are_one_account.py`.
- `A@x.com` and `a@x.com` made two accounts. Sign-up lower-cases the address; sign-up and sign-in compare without
  capitals. Same test file.
- Raw database errors were shown to people. `plainFailure` turns them into plain words.

Data and workflows
- Seed: null required locations, non-unique email, names written into enum columns. Fixed in projection and seed.
- Sign-up asked for rating and total rides, started drivers online, accepted a phone of letters. `account_model` and
  the sign-up route.
- Two drivers could both accept the same ride; expired requests could be accepted. Verify step and expiry query step.
- `completed_at` defaulted to now. `_HAPPENS_LATER`.
- Admin alerts addressed to a driver id leaked to drivers. Admin inbox id.

Screens
- Hydration errors from "x minutes ago" and countdowns. Absolute times; countdown mounts after load.
- Menu `?view=` vs `?tab=`, four items lit, white text on lavender rail. `project_shell`, `railIsDark`.

Smith (Forge's assistant)
- A per-role platform plan (phone app, website, both) is shown before a multi-role app is made, only when needed
  (two or more roles that would not all use the same platform, and one needs a phone). Simple apps keep the one
  question. Test: `test_smith_shows_a_platform_plan_only_when_an_app_needs_one.py`.

## App only (a new Forge app will NOT have these yet)

These were fixed by hand in `output/n2xcrvt5` and still need moving into Forge:
- Onboarding parts (`personal`, `vehicle`, `payout`) written with `WorkflowForm`, plus the workflows "Save my
  details" and "Save my vehicle" (FLOW-016, FLOW-017) added to that app's blueprint by hand.
- Driver home and live map pages using `FleetBeacon` (hand-written page code, synced into the blueprint).
- Profile page with Sign out and an edit link.
- `src/schemas/shell.json` and the vendored `SideNav` dist patch (the package source IS fixed in Forge:
  `packages/library/.../SideNav.tsx`; the app copy was patched separately).
- The "Ride" ownership rule with `readsUnclaimed`, added to the app's blueprint by hand (the Forge side is done; a new
  app only gets it if the blueprint agent writes it, which it is now taught to do).

## Found, not fixed yet

- The test browser crashes ("Target crashed") on pages that draw the Google map several times in a row, in headless
  Chromium. Not yet known whether it is the test browser or the page.
- A person with a customer phone: open (searching) ride requests still show the rider's phone to every driver, before
  anyone accepts. It should show only after acceptance.
- Position updates after a network drop: one test saw no new positions from the driver after reconnect. Needs a closer
  look.
