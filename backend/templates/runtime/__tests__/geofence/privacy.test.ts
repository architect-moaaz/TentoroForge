import { test } from "node:test";
import assert from "node:assert/strict";
import { retentionDays, cutoffMs, coordDecimals, coarsen, purgeDue, DEFAULT_RETENTION_DAYS } from "../../geofence/privacy.ts";

test("crossings are kept 90 days unless the app says otherwise", () => {
  assert.equal(retentionDays({}), DEFAULT_RETENTION_DAYS);
  assert.equal(retentionDays({ FORGE_GEOFENCE_RETENTION_DAYS: "30" }), 30);
  assert.equal(retentionDays({ FORGE_GEOFENCE_RETENTION_DAYS: "0" }), 0);
});

test("a retention setting nobody can read falls back to the default, never to 'keep for ever' or 'delete all'", () => {
  for (const bad of ["abc", "-5", "NaN", "", "  "]) assert.equal(retentionDays({ FORGE_GEOFENCE_RETENTION_DAYS: bad }), DEFAULT_RETENTION_DAYS, bad);
  assert.equal(retentionDays({ FORGE_GEOFENCE_RETENTION_DAYS: "999999" }), 3650);
});

test("the cut-off is the retention period before now, and none when kept for ever", () => {
  assert.equal(cutoffMs(10 * 86_400_000, 3), 7 * 86_400_000);
  assert.equal(cutoffMs(1_000_000, 0), null);
});

test("positions are stored as exactly as asked, within sensible limits", () => {
  assert.equal(coordDecimals({}), 6);
  assert.equal(coordDecimals({ FORGE_GEOFENCE_COORD_DECIMALS: "3" }), 3);
  assert.equal(coordDecimals({ FORGE_GEOFENCE_COORD_DECIMALS: "0" }), 2, "never so coarse that a zone cannot be told apart from its city");
  assert.equal(coordDecimals({ FORGE_GEOFENCE_COORD_DECIMALS: "12" }), 7);
  assert.equal(coordDecimals({ FORGE_GEOFENCE_COORD_DECIMALS: "x" }), 6);
  assert.equal(coarsen(12.97163849, 3), 12.972);
  assert.equal(coarsen(-77.594612, 2), -77.59);
});

test("cleaning up happens at most once an hour", () => {
  assert.equal(purgeDue(0, 59 * 60_000), false);
  assert.equal(purgeDue(0, 60 * 60_000), true);
});
