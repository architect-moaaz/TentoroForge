/**
 * Creating an account from the phone: what a person must give before anything is sent, what is sent to
 * `/api/auth/signup` (the web's body, to the letter), what a refusal says in words, and where the sign-in
 * gate lets a signed-out person go (sign-up is open) and a signed-in one leave (sign-up leads home).
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();
const su = await import("../src/sdk/signup.ts");
const gate = await import("../src/sdk/gate.ts");

const ACCOUNT = {
  entity: "Member", labelField: "fullName", locationField: null,
  fields: [
    { name: "fullName", label: "Full name", kind: "text", required: true },
    { name: "email", label: "Email", kind: "email", required: true },
    { name: "phone", label: "Phone", kind: "tel", required: false },
    { name: "trade", label: "Trade", kind: "select", required: true, options: [{ label: "Electrical", value: "electrical" }] },
    { name: "newsletter", label: "Newsletter", kind: "checkbox", required: true },
  ],
};

console.log("what a person must give");
eqJson(su.signUpFields(ACCOUNT).map((f: any) => f.name), ["fullName", "phone", "trade", "newsletter"], "the account's own fields, without the email every account has");
eqJson(su.signUpFields(null), [], "no account entity: nothing of its own to ask");
eqJson(su.validateSignUp({ email: "", password: "", name: "" }, null), { name: "Enter your name.", email: "Enter your email address.", password: "Choose a password." }, "an app with no account entity asks a name, an email and a password");
eqJson(su.validateSignUp({ email: "ann@x.io", password: "secret1", name: "Ann" }, null), {}, "…and nothing else");
eqJson(su.validateSignUp({ email: "not-an-email", password: "12345" }, null), { name: "Enter your name.", email: "That does not look like an email address.", password: "Use at least 6 characters." }, "a bad email and a short password, in words");
const partial = su.validateSignUp({ email: "ann@x.io", password: "secret1", account: { fullName: "Ann" } }, ACCOUNT);
eqJson(partial, { trade: "Trade is required." }, "a required field left out is named; a switch is never 'missing'; an optional one is fine");
eqJson(su.validateSignUp({ email: "ann@x.io", password: "secret1", account: { fullName: "Ann", trade: "electrical" } }, ACCOUNT), {}, "complete");

console.log("what is sent");
eqJson(su.signUpBody({ email: " Ann@X.io ", password: "secret1", account: { fullName: "Ann Lee", trade: "electrical" } }, ACCOUNT),
  { email: "Ann@X.io", password: "secret1", name: "Ann Lee", account: { fullName: "Ann Lee", trade: "electrical" } }, "the name is the label field's value; the email is trimmed");
eqJson(su.signUpBody({ email: "ann@x.io", password: "secret1", name: "Ann" }, null), { email: "ann@x.io", password: "secret1", name: "Ann", account: {} }, "no account entity: the typed name");
eqJson(su.signUpBody({ email: "ann.lee@x.io", password: "secret1" }, null).name, "ann.lee", "no name at all: the part of the email before the @");

console.log("what a refusal says");
const calls: any[] = [];
const answer = (res: any) => async (path: string, init: any) => { calls.push([path, init]); return res; };
let out: any = await su.signUpRequest(answer({ ok: true, status: 201, body: { id: "1" }, networkError: null }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson(out, { ok: true }, "created");
eqJson([calls[0][0], calls[0][1].method], ["/api/auth/signup", "POST"], "to the app's own route");
out = await su.signUpRequest(answer({ ok: false, status: 409, body: { error: { code: "CONFLICT", message: "Email already registered" } }, networkError: null }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson(out, { ok: false, reason: "taken", message: "Email already registered" }, "taken, in the app's own words");
out = await su.signUpRequest(answer({ ok: false, status: 409, body: null, networkError: null }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson(out.message, "That email is already registered. Sign in instead.", "taken, with no words from the app");
out = await su.signUpRequest(answer({ ok: false, status: 400, body: { error: "Password must be at least 6 characters" }, networkError: null }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson([out.reason, out.message], ["invalid", "Password must be at least 6 characters"], "a plain-string error is said as it is");
out = await su.signUpRequest(answer({ ok: false, status: 405, body: null, networkError: null }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson(out.reason, "unavailable", "an app with no sign-up route says so");
out = await su.signUpRequest(answer({ ok: false, status: 0, body: null, networkError: "Network request failed" }), { email: "a@x.io", password: "secret1", name: "A" }, null);
eqJson([out.reason, out.message], ["network", "Network request failed"], "no answer: the network's sentence");

console.log("the gate");
const g = (over: object) => gate.gateDecision({ status: "signedOut", needsOrganisation: false, pathname: "/orders", publicRoutes: [], home: "/home", ...over } as any);
eqJson([g({ pathname: "/signup" }), g({ pathname: "/signup/" })], [null, null], "signed out may open sign-up: it is how an account begins");
eqJson(g({ pathname: "/orders" }), "/login", "…and no other private route");
eqJson(g({ status: "signedIn", pathname: "/signup" }), "/home", "signed in has nothing to do on sign-up: home");
eqJson(g({ status: "signedIn", needsOrganisation: true, pathname: "/signup" }), "/organisation", "…or the organisation to pick first");

done("account creation");
