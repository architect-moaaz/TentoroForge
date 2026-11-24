/**
 * Signup and first sign-in make the account record only for the roles whose
 * login is one (`security.accountRoles` → ACCOUNT_ROLES).
 *
 * DITANS (2026-11-24): every employer who signed up got a Candidate record,
 * because the starting values and the typed name and email alone made one.
 * Runs the SHIPPED app-foundation account-row.ts with its imports stubbed.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const declared = process.env.ACCOUNT_ROLES_DECLARED === "1";
const account = JSON.stringify({ entity: "Candidate", fields: [
  { name: "fullName", label: "Full name", kind: "text", required: true },
  { name: "email", label: "Email", kind: "email", required: true },
  { name: "plan", label: "Plan", kind: "text", required: true }], labelField: "fullName", locationField: null });
installHarness({
  stubs: {
    "@/lib/account":
      `export const ACCOUNT = ${account}; export const ACCOUNT_INITIAL = { plan: "free" };` +
      ` export const SIGNUP_ROLE = 'Candidate'; export const SIGNUP_ROLES = ['Candidate', 'Organisation Admin'];` +
      (declared ? ` export const ACCOUNT_ROLES = ['Candidate'];` : ""),
    "@/lib/account-table": "export const accountTable = { __name: 'candidates' };",
    "@/db/schema/user": "export const users = { __name: 'users' };",
    "drizzle-orm": "export const eq = () => ({});",
    "@/lib/data-engine": "export const sealSensitive = async () => {};",
    "@/lib/data-init": "export const ensureDataEngineInitialized = async () => {};",
  },
});
const { accountValues, hasAccountRecord } = await import("../../app-foundation/src/lib/account-row.ts");

const candidate = accountValues({}, "nurse@example.com", "A Nurse", "Candidate");
eqJson(candidate.values, { plan: "free", fullName: "A Nurse", email: "nurse@example.com" },
       "a candidate's signup makes their Candidate record");
eqJson(accountValues({}, "x@example.com", "X", null).values?.email, "x@example.com",
       "no role named is the signup role, which has one");
const employer = accountValues({}, "boss@hospital.example", "The Boss", "Organisation Admin");
if (declared) {
  eqJson(employer, {}, "an employer's signup makes no Candidate record");
  eqJson(hasAccountRecord("DITANS Operations"), false, "nor does a member of staff's first sign-in");
  eqJson(hasAccountRecord("Candidate"), true, "the candidate's does");
} else {
  ok(!!employer.values, "undeclared, what an employer sent still makes one, as before");
  eqJson(hasAccountRecord("DITANS Operations"), true, "and every role has one");
}
done("a signup makes the account record only for its roles");
