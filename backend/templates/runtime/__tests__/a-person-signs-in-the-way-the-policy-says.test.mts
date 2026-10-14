/**
 * The SHIPPED lib/sign-in.ts and lib/session-cookie.ts: a provider is
 * offered only when its names are set; a domain the entry does not admit is
 * refused; the claims name the role, any case, else the default; a magic
 * token is stored only as a digest; the sign-in's own cookies carry this
 * app's prefix.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness({
  stubs: {
    "@/lib/sign-in-policy": `export const SIGN_IN = { password: false, magicLink: true, sso: [
      { id: "entra", name: "Microsoft 365", kind: "oidc", provider: "entra", issuerKey: "SSO_ENTRA_ISSUER",
        clientIdKey: "SSO_ENTRA_CLIENT_ID", clientSecretKey: "SSO_ENTRA_CLIENT_SECRET", domains: ["acme.com"],
        roleFrom: { claim: "groups", map: { Finance: "Accountant" }, default: "Viewer" }, provisioning: "just_in_time" },
      { id: "google", name: "Google Workspace", kind: "oidc", provider: "google", issuerKey: "SSO_GOOGLE_ISSUER",
        clientIdKey: "SSO_GOOGLE_CLIENT_ID", clientSecretKey: "SSO_GOOGLE_CLIENT_SECRET", domains: [],
        roleFrom: null, provisioning: "invite_only" },
    ] };`,
  },
});

const m: any = await import("../../app-foundation/src/lib/sign-in.ts");
const entra = m.entryOf("entra");
const google = m.entryOf("google");

ok(!m.connected(entra, {}), "no names set: not connected");
ok(m.connected(entra, { SSO_ENTRA_ISSUER: "https://login.microsoftonline.com/t/v2.0", SSO_ENTRA_CLIENT_ID: "abc" }), "issuer + client id: connected");
ok(m.connected(google, { SSO_GOOGLE_CLIENT_ID: "abc" }), "Google's issuer is Google's own: the client id is enough");
eqJson(m.issuerOf(google, {}), "https://accounts.google.com", "the fixed issuer");
eqJson(m.issuerOf(entra, { SSO_ENTRA_ISSUER: "https://x/" }), "https://x", "a trailing slash taken off");
eqJson(m.callbackPath("entra"), "/api/auth/callback/entra", "where the provider sends the person back");

ok(m.domainAllowed("ann@acme.com", entra) && m.domainAllowed("ann@ACME.com", entra), "an allowed domain, any case");
ok(!m.domainAllowed("ann@other.com", entra), "another domain is refused");
ok(m.domainAllowed("anyone@anywhere.io", google), "no domains: everyone the provider knows");

eqJson(m.roleFromClaims({ groups: ["finance"] }, entra), "Accountant", "a mapped group, any case");
eqJson(m.roleFromClaims({ groups: ["Sales"] }, entra), "Viewer", "an unmapped group: the default");
eqJson(m.roleFromClaims({}, entra), "Viewer", "no groups: the default");
eqJson(m.roleFromClaims({ groups: "Finance" }, entra), "Accountant", "a single value is a list of one");
eqJson(m.roleFromClaims({ groups: ["Finance"] }, google), null, "no roleFrom: the application decides");

const t = m.magicToken();
ok(t.token.length >= 40 && t.hash === m.digest(t.token) && t.hash !== t.token, "the token and its digest differ; only the digest is stored");
eqJson(m.MAGIC_TTL_MS, 15 * 60_000, "fifteen minutes");

const shown = m.methods({ SSO_ENTRA_ISSUER: "https://i", SSO_ENTRA_CLIENT_ID: "c" });
eqJson(shown, { password: false, magicLink: true, sso: [
  { id: "entra", name: "Microsoft 365", kind: "oidc", connected: true },
  { id: "google", name: "Google Workspace", kind: "oidc", connected: false },
] }, "what the form is told: names and booleans, never a value");

process.env.NEXTAUTH_SECRET = "app-one";
const cookies: any = await import("../../app-foundation/src/lib/session-cookie.ts");
const c = cookies.sessionCookies();
const prefix = cookies.sessionCookiePrefix();
ok(c.state.name.startsWith(prefix) && c.pkceCodeVerifier.name.startsWith(prefix) && c.nonce.name.startsWith(prefix),
   "the sign-in's own cookies carry this app's prefix");
ok(c.state.options.maxAge === 900 && c.state.options.httpOnly, "state lives for the sign-in only, out of reach of scripts");

done();
