/**
 * The record behind the id is loaded before the steps read it.
 *
 * 0l133sp2: "Approve verification" refused every pending member, because its
 * guard `member.kycStatus = "pending"` was read off the id STRING the control
 * sent; and the admin's notification was stored as " has submitted an identity
 * document", because `{{member.displayName}}` read nothing.
 *
 * Run (Node 25+ with built-in type stripping):
 *   cd backend/templates/runtime && \
 *   node --experimental-strip-types __tests__/record-inputs.test.mts
 */
import { fillSelfInputs, hydrateRecordInputs } from "../workflows/record-inputs.ts";

let passed = 0;
let failed = 0;

function check(name: string, actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}\n      expected: ${JSON.stringify(expected)}\n      actual:   ${JSON.stringify(actual)}`);
  }
}

const ROW = { id: "m1", displayName: "Swarupa", kycStatus: "pending" };
const wf = { recordInputs: [{ name: "member", table: "members" }] };
const load = async (table: string, id: string) =>
  table === "members" && id === "m1" ? ROW : null;

console.log("hydrateRecordInputs");

check("an id becomes the record the steps read",
  await hydrateRecordInputs(wf, { member: "m1" }, load), { member: ROW });

check("a record already in hand is left alone",
  await hydrateRecordInputs(wf, { member: { id: "m2", kycStatus: "verified" } }, load),
  { member: { id: "m2", kycStatus: "verified" } });

check("a row nobody can find leaves the id as it was",
  await hydrateRecordInputs(wf, { member: "gone" }, load), { member: "gone" });

check("a loader that throws does not lose the run",
  await hydrateRecordInputs(wf, { member: "m1" }, async () => { throw new Error("no db"); }),
  { member: "m1" });

check("other inputs are untouched",
  await hydrateRecordInputs(wf, { member: "m1", idDocumentPhoto: "file_9" }, load),
  { member: ROW, idDocumentPhoto: "file_9" });

check("a workflow with no record inputs is handed back as it came",
  await hydrateRecordInputs({}, { a: 1 }, load), { a: 1 });

// Kids Vaccination Tracker (forge-v3, 2026-10-03): "Add Child needs parent —
// nothing was changed" for every parent. `parent` is the signed-in person.
console.log("fillSelfInputs");
const addChild = { recordInputs: [{ name: "parent", table: "parents" }, { name: "doctor", table: "doctors" }] };
const isAccount = (t: string) => t === "parents";
check("a missing record input of the account's table is the signed-in person",
  fillSelfInputs(addChild, { fullName: "Ava" }, { id: "u-parent" }, isAccount),
  { fullName: "Ava", parent: "u-parent" });
check("a value the caller sent is kept — an admin filing for someone names whom",
  fillSelfInputs(addChild, { parent: "p-other" }, { id: "u-admin" }, isAccount), { parent: "p-other" });
check("an empty string is missing, and filled",
  fillSelfInputs(addChild, { parent: "" }, { id: "u-parent" }, isAccount), { parent: "u-parent" });
check("a record of another table is never the person",
  fillSelfInputs(addChild, {}, { id: "u-parent" }, isAccount), { parent: "u-parent" });
check("nobody signed in, nothing filled",
  fillSelfInputs(addChild, { fullName: "Ava" }, undefined, isAccount), { fullName: "Ava" });
check("an app with no account entity fills nothing",
  fillSelfInputs(addChild, {}, { id: "u-parent" }, () => false), {});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
