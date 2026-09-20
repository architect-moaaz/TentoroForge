/**
 * A run is refused when it arrives without what it needs.
 *
 * 0l133sp2: a member's "Submit Identity Verification" ran with no identity
 * document. The step wrote `kycStatus: pending` and NULL over the photo
 * column, the run said "completed", and the member was told it had been sent.
 *
 * Run (Node 25+ with built-in type stripping):
 *   cd backend/templates/runtime && \
 *   node --experimental-strip-types __tests__/required-inputs.test.mts
 */
import { missingRequiredInputs } from "../workflows/required-inputs.ts";

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

const wf = { requiredInputs: ["member", "idDocumentPhoto"] };

check("nothing missing when both are given",
  missingRequiredInputs(wf, { member: "m1", idDocumentPhoto: "file_1" }), []);
check("an absent input is missing",
  missingRequiredInputs(wf, { member: "m1" }), ["idDocumentPhoto"]);
check("an empty box is missing, not a value to write",
  missingRequiredInputs(wf, { member: "m1", idDocumentPhoto: "" }), ["idDocumentPhoto"]);
check("null is missing",
  missingRequiredInputs(wf, { member: "m1", idDocumentPhoto: null }), ["idDocumentPhoto"]);
check("false and 0 are answers, not omissions",
  missingRequiredInputs({ requiredInputs: ["agreed", "count"] }, { agreed: false, count: 0 }), []);
check("a workflow that declares none needs none",
  missingRequiredInputs({}, {}), []);

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
