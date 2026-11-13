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
- The phone app follows that plan role by role: the driver's pages are drawn as phone screens, the administrator's are
  not (`mobile.nativeRoles`). Test: `test_the_phone_app_draws_only_the_pages_of_the_roles_the_plan_gave_it.py`.

The phone app
- A phone app can share a driver's position and show a map with the road, the distance left and the arrival time
  (`FleetBeacon`, `ShareLocation`, `LiveTrackingMap`, `MapView`, `useRoute`), following a trip by asking the server
  for the newest note (`?snapshot=1`). The native builder's guide teaches when to use them. Sharing works while the app is
  open. Test: `test_the_phone_app_can_share_a_position_and_show_the_road.py` and the native node test.

A person's own details can be saved (found building the ride-hailing app by hand)
- A page of someone's own details (onboarding, profile, settings) with no workflow that saves them is refused before the app
  is built (`own-details-cannot-be-saved`), and the workflow-writing agent is told the pattern: a "Save my <thing>"
  workflow that reads the record by `$user.id`, refuses unless it is theirs, updates only what they may change and keeps
  an empty box as it was. Test: `test_a_page_of_a_persons_own_details_can_save_them.py`.

The phone's map and live location (found trying the driver app on an Android emulator)
- A blank map in Expo Go: Expo Go's own Maps setup did not draw tiles, and it cannot use the app's key. A development build made
  with the app's own Maps SDK key (`GOOGLE_MAPS_ANDROID_KEY`, written into `app.json` when the phone project is made) draws
  real tiles. Background location and push alerts will need this kind of build too.
- Two screens asking for the location at once (the home screen's position sharing and the map) left the second waiting for
  ever. One helper (`sdk/permission.ts`) looks first, asks once, and everyone gets the same answer. The map says in words when
  the location is blocked, cannot be found, or is old, and a parked phone reports at its interval so it is not shown stale.
- Map-first kit pieces: `MapScreen` (full-screen map, floating top panel, round buttons, follows the device and recentres),
  `BottomSheet` (stays up, never dims the map, drags between resting heights), `FloatingPanel`, `FloatingButton`, a dark
  map under a dark design. Test: `test_the_phone_app_can_share_a_position_and_show_the_road.py` and the native node tests.

## Checked and already in Forge (they were only hand edits in the test app)

- The menu file `src/schemas/shell.json`: regenerated from the test app's blueprint, it is identical to what Forge makes.
- The sidebar fix: the library SOURCE is fixed (`packages/library/.../SideNav/SideNav.tsx`) and Forge rebuilds the
  library from source into every new app, so the hand patch to the app's copy only repeated it.
- Sign out: Forge's account menu (`(dashboard)/AccountMenu.tsx`) has it in every app. The extra button on the test app's
  profile page is not needed.
- A driver who is online shares their position by themselves: the page writer is taught `FleetBeacon` (test
  `test_live_tracking_is_offered_to_the_page_agent.py`), so the home and live-map pages that were written by hand are
  what a new app's writer is taught to write.
- The ride ownership rule with `readsUnclaimed`: the engine supports it and the blueprint agent is taught to use it for
  work that is offered before anyone holds it.

- A person who works from the road gets a MAP-FIRST phone home (the map is the screen; the home, the offer and the trip are
  states of one bottom sheet), chosen by the platform plan (`mobile.mapFirstRoles`) and written through the native
  builder (`phone: {experience: "map_first", covers: [...]}`, `services/blueprint/map_first.py`, kit parts `MapScreen`,
  `BottomSheet`, `FloatingPanel`). The pages it covers get no screen and no tab; the web app is untouched.
- A phone screen may not tick: a `setInterval` that sets state in a screen is refused by the builder's checks, and the kit
  has `Countdown`, `Elapsed` and `useExpired` for clocks. The phone's number formatter is made once, not on every draw.
- A tab is named by the path of its route file, so a tab for `/rides/history` finds its screen.

- Phone alerts, server side: a phone registers its Expo token (`/api/push/device`, table `forge_device_tokens`), the push
  module sends to phones through Expo as well as browsers, and a `send_notification` step with `nearest` alerts the on-duty
  people closest to a place (the live fleet). Smith is taught to write it and the contract refuses one that cannot work.
  The phone side (asking permission, sending the token, opening the app on a tap) is NOT built yet.
- The live fleet lost the first driver's position when nobody was watching the map (the empty fleet was dropped before the
  driver was added). Fixed in `tracking/hub.ts`; it affected every app with live tracking.

## App only (a new Forge app will NOT have these)

These were hand-written in `output/n2xcrvt5` for that app's own data and stay there:
- The actual contents of its "Save my details" and "Save my vehicle" workflows and onboarding form parts (FLOW-016,
  FLOW-017). A new app gets the REFUSAL and the teaching, so Smith writes its own; it does not get a copy of these.
- The ten driver phone screens in `output/n2xcrvt5/native` (written through Forge's native engineer, answered by hand).

## Found, not fixed yet

- The phone app (Expo version 51) cannot be opened in the App Store's Expo Go on an iPhone, which only opens the newest
  version. An iPhone needs a proper build (a paid Apple account) or an upgrade of the phone template to a newer Expo.
- The test ride app's demo-ride workflow carries the "tell the nearest drivers" step by hand (app only); real apps get it
  through Smith's teaching.
- On the Android emulator used for testing, reading the clock costs about 65 microseconds a call (20,000 calls take over a
  second; a phone takes about a millisecond), so React's development build crawls and the JS thread sits near 100%. That
  is the emulator, not the app: a plain map screen is fine and the full driver screen is only slow. Test speed and
  "stuck on loading" claims on a real phone or a release build, not on that emulator in development mode.
- The test browser crashes ("Target crashed") on pages that draw the Google map several times in a row, in headless
  Chromium. Not yet known whether it is the test browser or the page.
- Open (searching) ride requests show the rider's phone to every driver before anyone accepts. It should show only after
  acceptance.
- A test saw no position updates from the driver after a dropped network, even with the retry fix in the web driver
  page. Not yet known if the app or the test is at fault.
- The driver's phone Profile page has no control for notification choices (no workflow exists for them).
- The Profile page shows the last four digits of the bank account number, which assumes the field comes back in full.
- Ride History on the phone filters the date range on the phone, so a very long history may be cut off by the list's
  page size.
- The native builder's compile check uses a toolchain folder that is chosen by environment; an old one missed a real type
  error. The folder should be keyed by the template's packages every time.
