# Geofencing in Forge

A zone is a place on a map (a circle or a polygon). Geofencing is what the app does when a person or thing enters it, leaves
it, stays in it, or comes near it. Everything below ships in every app Forge builds; an app with no zones pays nothing for it.

## 1. When an app gets it
`services/blueprint/geofence_plan.py` reads the brief. The word "geofence" is enough; so is "when the driver is within 300 m"; or two
different phrases about arriving, leaving or being near a place. "Live tracking" alone is not geofencing. The result is
kept at `.forge/geofence-plan.json` and becomes the blueprint's `geofencing` section.

## 2. What the plan says
Scenario (delivery, ride, fleet, attendance, store pickup, restricted area), the phrases that decided it, the zones, and
the rules. A zone has coordinates only if the brief gave them ("Zone: Depot - circle 150 m at 12.97, 77.59"); the rest are drawn
by the owner. A zone carries the settings its rules need (approach distance, stay time).

## 3. The engine (`templates/runtime/geofence/engine.ts`)
Pure maths and a state machine, no clock or database. Circles and polygons; entered, exited, dwell (once per visit),
approaching (once per approach); GPS accuracy (a fix is "surely inside" only if its error circle is); hysteresis; several
agreeing fixes; stale, future, old, duplicate and out-of-order fixes; gaps. A grid index finds the few zones near a point
out of thousands.

## 4. The data
`forge_geofences`, `forge_geofence_assignments` (which kinds of record a zone watches), `forge_geofence_state`,
`forge_geofence_events` (the engine's own id as the key, so a crossing is recorded once), `forge_geofence_rules`.

## 5. The service
Saves state, records events, announces only the ones newly recorded. One queue per record. A position is never lost to a
geofence failure; it is logged once.

## 6. Rules
Actions are `emit_event` and `notify` (a role). Each crossing acts once. An action that finishes a job, takes payment or
marks someone present is held until an event that is not GPS has been recorded for the same record, then runs once. With no
such event named, it never runs.

## 7. Live
A server-sent stream, `/api/geofence/stream`, per record kind, limited to the records the person may read.

## 8. The five screens
`GeofenceMap`, `GeofenceEditor`, `GeofenceMonitor`, `GeofenceEventTimeline`, `GeofenceSettings` (in `@/sdk/geofence`). Free map and Google map.

## 9. The simulator
`geofence/simulate.ts`: seeded walks, stays, duplicates, late fixes, wobble at an edge. Used by every scenario test.

## 10. Security and privacy
Zones: anyone signed in reads, `FORGE_GEOFENCE_ROLES` (default admin, any case) changes. Crossings follow the app's own read
rules for the record. Positions only arrive from someone who chose to share (the tracking route). Crossings are kept 90 days
(`FORGE_GEOFENCE_RETENTION_DAYS`), positions can be stored coarser (`FORGE_GEOFENCE_COORD_DECIMALS`), and one record's crossings
can be erased by a zone manager.

## 11. Tests
Node: engine, service, rules, hub, plan, privacy, load, and whole scenarios. Python: the wrapper that runs them, the plan, the
blueprint section, the injector, and the shipped screens and routes.

## 12. Limits (not done, said plainly)
- A rule cannot notify "this order's customer", only a role; customer-facing rules emit an event for the app's workflows.
- The live feed and the held-rule list are per server process; two servers on one record may read the same state.
- A failed rule is not retried (it is claimed first; the failure goes on the bus).
- A fast vehicle crossing a small zone needs `minFixes: 1`.
- Nothing has run on a real phone, and no app has been built from one prompt end to end.
- Consent is the sharing choice the tracking screen already asks; geofencing adds no consent screen of its own.
- Regenerating the blueprint schema from `packages/schema` loses hand-added fields (see FIXES_LEDGER.md).

- A zone or rule that came from the plan and was then DELETED or renamed is put back the next time the app's seed runs; nothing records that it was removed on purpose. (Changing one is safe: a zone that is there is left as it is.)
- The history screen and the live feed read the records a person may open, capped at 500 of them (the tracking access rule). A person who can open more than 500 records can miss crossings of the rest.
- A rule's claim is taken before its action runs. If the action then fails (a push that throws), the claim is spent and a later retry of the same crossing reads as a duplicate: the failure is recorded (`geofence.action_failed`) but not retried.
