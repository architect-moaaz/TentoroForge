/**
 * The SHIPPED tenancy.ts: with FORGE_ORG_DOMAIN set, each organisation gets
 * an address from its name, the host decides the organisation a request
 * acts in, a member acts there in their role in it, a platform role enters
 * any, and someone who does not belong acts in none. An admin renames the
 * address; a reserved or taken name is refused. Without the variable,
 * nothing changes.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

const G = globalThis as any;
G.__orgs = [{ id: "o-acme", name: "Acme Clinic" }, { id: "o-glob", name: "Globex" }, { id: "o-www", name: "WWW" }];
G.__members = [
  { user_id: "u-nurse", org_id: "o-acme", role: "Nurse" },
  { user_id: "u-nurse", org_id: "o-glob", role: "Clinic Manager" },
  { user_id: "u-other", org_id: "o-glob", role: "Nurse" },
];
G.__addr = [] as Array<{ org_id: string; slug: string }>;
G.__active = [] as Array<[string, string]>;

installHarness({ stubs: {
  "drizzle-orm": `export const sql = Object.assign((s, ...v) => ({ s: s.join("?"), v }), { raw: (r) => ({ raw: r }) });`,
  "./tenancy-policy": `export const TENANCY = { kind: "organisation", entity: "Clinic", table: "clinics", nameColumn: "name",
    memberRoles: ["Nurse", "Clinic Manager"], platformRoles: ["Platform Admin"], adminRole: "Clinic Manager", signup: "both", columns: {} };`,
  "@/db": `
    const G = globalThis;
    const lit = (q, re) => { const m = q.match(re); return m ? m[1].replace(/''/g, "'") : null; };
    export const db = { execute: async (q) => {
      if (q.s !== undefined) {
        if (q.s.includes("FROM forge_memberships")) return G.__members.filter((m) => m.user_id === q.v[0]).map((m) => ({ org_id: m.org_id, role: m.role }));
        if (q.s.includes("UPDATE users SET active_org_id")) { G.__active.push([q.v[1], q.v[0]]); return []; }
        throw new Error("unexpected " + q.s);
      }
      const r = q.raw;
      if (r.includes("LEFT JOIN forge_org_addresses")) return G.__orgs.filter((o) => !G.__addr.some((a) => a.org_id === o.id));
      if (r.startsWith("SELECT id::text AS id, \\"name\\" AS name FROM \\"clinics\\" WHERE id::text IN")) return G.__orgs;
      if (r.startsWith("INSERT INTO forge_org_addresses") && r.includes("DO NOTHING")) {
        const vals = [...r.matchAll(/'((?:[^']|'')*)'/g)].map((m) => m[1]);
        if (G.__addr.some((a) => a.org_id === vals[0] || a.slug === vals[1])) return [];
        G.__addr.push({ org_id: vals[0], slug: vals[1] }); return [{ slug: vals[1] }];
      }
      if (r.startsWith("INSERT INTO forge_org_addresses")) {
        const vals = [...r.matchAll(/'((?:[^']|'')*)'/g)].map((m) => m[1]);
        const row = G.__addr.find((a) => a.org_id === vals[0]);
        if (row) row.slug = vals[1]; else G.__addr.push({ org_id: vals[0], slug: vals[1] });
        return [];
      }
      if (r.startsWith("SELECT 1 FROM forge_org_addresses")) { const id = lit(r, /org_id = '((?:[^']|'')*)'/); return G.__addr.filter((a) => a.org_id === id).map(() => ({ x: 1 })); }
      if (r.startsWith("SELECT slug FROM forge_org_addresses")) { const id = lit(r, /org_id = '((?:[^']|'')*)'/); return G.__addr.filter((a) => a.org_id === id); }
      if (r.startsWith("SELECT org_id FROM forge_org_addresses")) { const s = lit(r, /slug = '((?:[^']|'')*)'/); return G.__addr.filter((a) => a.slug === s); }
      throw new Error("unexpected " + r);
    } };`,
} });

const t: any = await import("../tenancy.ts");

delete process.env.FORGE_ORG_DOMAIN;
eqJson(t.slugFromHost("acme.clinicapp.com"), null, "without the variable no host names an organisation");
const user = { id: "u-nurse", role: "Nurse", activeOrgId: "o-acme" };
eqJson(await t.atAddress(user, "acme.clinicapp.com"), null, "and nothing changes");

process.env.FORGE_ORG_DOMAIN = "clinicapp.com";
eqJson(t.slugFromHost("Acme.ClinicApp.com:443"), "acme", "the first label is the organisation");
for (const host of ["clinicapp.com", "a.b.clinicapp.com", "www.clinicapp.com", "acme.other.com", ""]) {
  eqJson(t.slugFromHost(host), null, `${host || "no host"} names no organisation`);
}
eqJson(t.slugify("Ärzte & Söhne — Nord"), "arzte-sohne-nord", "a slug from a name");

await t.ensureSlugs();
eqJson(G.__addr.map((a: any) => a.slug), ["acme-clinic", "globex", "www-org"], "every organisation an address from its name; a reserved one is changed");

const acme = await t.atAddress(user, "acme-clinic.clinicapp.com");
eqJson(acme, { activeOrgId: "o-acme", role: "Nurse", orgRole: "Nurse" }, "a member acts in the address's organisation");
const glob = await t.atAddress(user, "globex.clinicapp.com");
eqJson(glob, { activeOrgId: "o-glob", role: "Clinic Manager", orgRole: "Clinic Manager" }, "in their role THERE");
await new Promise((r) => setTimeout(r, 0));
eqJson(G.__active, [["u-nurse", "o-glob"]], "and it is remembered as where they act");

const outsider = await t.atAddress({ id: "u-other", role: "Nurse", activeOrgId: "o-glob" }, "acme-clinic.clinicapp.com");
eqJson(outsider, { activeOrgId: t.NO_ORG, role: "Nurse", orgRole: null, outsideOrg: "acme-clinic" }, "someone who does not belong acts in none");
eqJson((await t.atAddress(user, "nobody.clinicapp.com"))?.outsideOrg, "nobody", "an address no organisation holds opens none");
const admin = await t.atAddress({ id: "u-plat", role: "Platform Admin", activeOrgId: null }, "globex.clinicapp.com");
eqJson(admin?.activeOrgId, "o-glob", "a platform role enters any organisation");
eqJson(admin?.role, "Platform Admin", "as itself");

eqJson(await t.setSlug("o-glob", "admin"), { ok: false, error: "admin is kept for the application; choose another." }, "a reserved name is refused");
eqJson((await t.setSlug("o-glob", "acme-clinic")).ok, false, "another organisation's address is refused");
eqJson(await t.setSlug("o-glob", "Globex Health"), { ok: true, slug: "globex-health" }, "renamed");
eqJson(await t.orgBySlug("globex-health"), "o-glob", "the new address opens it");
eqJson(await t.orgBySlug("globex"), null, "the old one does not");
eqJson(t.addressOf("globex-health"), "https://globex-health.clinicapp.com", "its address in full");
ok(true, "done");
done("organisation address");
