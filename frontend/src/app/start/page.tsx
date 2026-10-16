"use client";

/**
 * Where a new account lands: one question, then one form.
 *
 * "What kind of account?" — personal, business, or joining a team — and the
 * answer decides the next screen. Personal and business make the organisation
 * on one form (name, the address shown as the name is typed, who to invite,
 * a mark), and a business then gives its website on the same kind of screen:
 * the site is read, the palette and type come back in one card, the page
 * wears the colour, and the three things the read said about the company —
 * who you are, what you do, how you do it — are shown once as editable
 * drafts on a single screen, because confirming is not composing. One press
 * saves it all; the same fields stay in Settings → Brand.
 * Somebody joining a team is shown the teams that invited
 * them — an invitation is taken up the moment they sign in with the invited
 * address — and, when nobody has yet, told so plainly instead of shown an
 * empty page.
 */

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Building2, Check, Loader2, RefreshCw, Upload, Users } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";
import { COLOR_ROLES, type BrandIdentity, type BrandProfile, brand, describeDesign } from "@/lib/brand";
import { cleanedForSave } from "@/components/brand/BrandProfileEditor";
import { DiscoveryQuestionField, IdentityDetailFields, ReadFromNote, useBrandLogo } from "@/components/brand/fields";
import { PaletteStrip, ReadingSequence, TypeSpecimen } from "@/app/onboarding/moments";
import { ACCOUNT_TYPES, ROLES, type AccountType, type MemberRole, badEmails, parseEmails, slugPreview, slugProblem } from "./lib";

interface Org { id: string; name: string; slug: string }
interface Waiting {
  email: string;
  memberships: { invite_id: string; org_id: string; name: string; slug: string; role: string; invited: boolean }[];
  pending: { invite_id: string; org_id: string; name: string; slug: string; role: string }[];
}
interface InviteOutcome { invite_email: string | null; joined: boolean; emailed: boolean; invite_url: string }

type Step = "type" | "create" | "join" | "brand" | "about";

function Progress({ at, total }: { at: number; total: number }) {
  return (
    <div className="mx-auto mb-10 flex w-24 gap-1" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => i).map((i) => (
        <div key={i} className={`h-1 flex-1 rounded-full ${i <= at ? "bg-slate-900 dark:bg-white" : "bg-slate-200 dark:bg-slate-700"}`} />
      ))}
    </div>
  );
}

function Mark() {
  return (
    <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white dark:bg-white dark:text-slate-900">
      <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
      </svg>
    </div>
  );
}

/** A row of the readout: a label and what was found, or "not found" said plainly. */
function Found({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <span className="shrink-0 text-slate-500 dark:text-slate-400">{label}</span>
      <span className="min-w-0 text-right text-slate-900 dark:text-white">{children ?? <span className="text-slate-400">not found</span>}</span>
    </div>
  );
}

const ROLE_LABEL: Record<string, string> = {
  ...Object.fromEntries(COLOR_ROLES.map((r) => [r.key, r.label])),
  primaryForeground: "On brand", secondary: "Secondary", muted: "Muted", mutedForeground: "Muted text", card: "Cards",
};
const ROLE_ORDER = ["primary", "primaryForeground", "secondary", "accent", "background", "foreground", "muted", "border"];

/** Everything the site read produced, in the order it matters. */
function BrandReadout({ profile }: { profile: BrandProfile }) {
  const design = profile.design ?? {};
  const identity = profile.identity ?? {};
  const colors = Object.entries(design.colors ?? {}).filter(([, v]) => typeof v === "string" && v)
    .sort(([a], [b]) => (ROLE_ORDER.indexOf(a) + 1 || 99) - (ROLE_ORDER.indexOf(b) + 1 || 99));
  const type = design.typography ?? {};
  const radius = design.radius ?? {};
  const elevation = design.elevation ?? {};
  const voice = [["Industry", identity.industry], ["Audience", identity.audience], ["Tone", identity.tone], ["Voice", identity.voice], ["Values", identity.values]]
    .filter(([, v]) => v) as [string, string][];
  const card = "rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-slate-900";
  const head = "mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400";
  return (
    <div data-brand-readout="" className="grid gap-4 sm:grid-cols-2">
      <section className={card} aria-label="Colours">
        <h2 className={head}>Colours</h2>
        {colors.length === 0 && <p className="text-sm text-slate-400">No colours could be read.</p>}
        <ul className="space-y-1.5">
          {colors.map(([key, hex]) => (
            <li key={key} className="flex items-center gap-3 text-sm">
              <span aria-hidden="true" className="h-6 w-6 shrink-0 rounded-md border border-black/10" style={{ background: hex }} />
              <span className="flex-1 text-slate-700 dark:text-slate-200">{ROLE_LABEL[key] ?? key.replace(/([A-Z])/g, " $1").toLowerCase()}</span>
              <code className="text-xs text-slate-500">{hex}</code>
            </li>
          ))}
        </ul>
      </section>
      <section className={card} aria-label="Type">
        <h2 className={head}>Type</h2>
        <Found label="Headings"><span style={{ fontFamily: type.fontFamilyHeading }}>{type.fontFamilyHeading}</span></Found>
        <Found label="Body"><span style={{ fontFamily: type.fontFamilyBase }}>{type.fontFamilyBase}</span></Found>
        {type.fontWeightHeading && <Found label="Heading weight">{type.fontWeightHeading}</Found>}
        {type.fontSizeBase && <Found label="Base size">{type.fontSizeBase}</Found>}
        <h2 className={`${head} mt-4`}>Shape & density</h2>
        <Found label="Corners">{radius.md || radius.base || Object.values(radius)[0]}</Found>
        <Found label="Shadows">{elevation.md || elevation.base || Object.values(elevation)[0]}</Found>
        <Found label="Density">{design.informationDensity}</Found>
      </section>
      <section className={card} aria-label="Voice">
        <h2 className={head}>Voice</h2>
        {voice.length === 0 && <p className="text-sm text-slate-400">Nothing about the voice could be read.</p>}
        {voice.map(([label, value]) => <Found key={label} label={label}>{value}</Found>)}
      </section>
      <section className={card} aria-label="Brand guidelines">
        <h2 className={head}>Brand guidelines</h2>
        <p className="text-sm text-slate-600 dark:text-slate-300">What every agent that builds for you will be shown about your company and its design language.</p>
        {profile.design_md ? (
          <details className="mt-2 group">
            <summary className="cursor-pointer text-sm font-medium text-slate-900 dark:text-white">Read the guidelines</summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs leading-relaxed text-slate-700 dark:bg-slate-950 dark:text-slate-300">{profile.design_md}</pre>
          </details>
        ) : <p className="mt-2 text-sm text-slate-400">Written once the profile is saved.</p>}
      </section>
    </div>
  );
}

function StartInner() {
  const router = useRouter();
  const params = useSearchParams();
  const me = useAuthStore((s) => s.user);
  const [step, setStep] = useState<Step>("type");
  const [type, setType] = useState<AccountType>("personal");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // The form.
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [invites, setInvites] = useState("");
  const [role, setRole] = useState<MemberRole>("member");
  const [logo, setLogo] = useState<File | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [made, setMade] = useState<Org | null>(null);
  const [sent, setSent] = useState<InviteOutcome[]>([]);

  // Joining.
  const [waiting, setWaiting] = useState<Waiting | null>(null);
  const [checking, setChecking] = useState(false);

  // The brand, for a business: the site, the read, what came back.
  const [site, setSite] = useState("");
  const [reading, setReading] = useState(false);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  // What the read said about the company, as the person edits it.
  const [identity, setIdentity] = useState<BrandIdentity>({});
  const logoSrc = useBrandLogo(made?.id ?? "", Boolean(profile?.has_logo));
  // The screen wears the company's colour the moment there is one.
  const accent = profile?.design?.colors?.primary || "";
  const onAccent = profile?.design?.colors?.primaryForeground || "#FFFFFF";

  // The address follows the name until the person edits it by hand.
  useEffect(() => { if (!slugTouched) setSlug(slugPreview(name)); }, [name, slugTouched]);
  const slugWarning = useMemo(() => (slug || name ? slugProblem(slug) : ""), [slug, name]);
  const emailList = useMemo(() => parseEmails(invites), [invites]);
  const emailWarning = useMemo(() => {
    const bad = badEmails(emailList);
    return bad.length ? `Not an email address: ${bad.join(", ")}` : "";
  }, [emailList]);

  // A link straight to one path (`?type=joining`) skips the question — read
  // once, at arrival: a later re-render must not drag the person back to it.
  const arrived = useRef(false);
  useEffect(() => {
    if (arrived.current) return;
    arrived.current = true;
    const t = params.get("type");
    if (t === "joining") { setType("joining"); setStep("join"); }
    else if (t === "business" || t === "personal") { setType(t); setStep("create"); }
  }, [params]);

  async function lookWhoInvitedMe() {
    setChecking(true);
    try { setWaiting(await api.get<Waiting>("/api/me/invitations")); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not read your invitations."); }
    finally { setChecking(false); }
  }
  useEffect(() => { if (step === "join" && !waiting) void lookWhoInvitedMe(); }, [step]); // eslint-disable-line react-hooks/exhaustive-deps

  function chooseType() {
    setError("");
    setStep(type === "joining" ? "join" : "create");
  }

  async function createOrganisation(e: React.FormEvent) {
    e.preventDefault();
    if (slugWarning || emailWarning || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const org = await api.post<Org>("/api/orgs", { name: name.trim(), slug });
      setMade(org);
      // What kind of account this is, on the organisation, for whoever asks later.
      try { await api.put(`/api/orgs/${org.id}`, { settings: { account_type: type } }); } catch { /* not worth stopping for */ }
      if (logo) {
        const fd = new FormData();
        fd.append("file", logo);
        try { await api.upload(`/api/orgs/${org.id}/logo`, fd); } catch { /* the mark can be added in Settings */ }
      }
      const outcomes: InviteOutcome[] = [];
      for (const email of emailList) {
        try { outcomes.push(await api.post<InviteOutcome>(`/api/orgs/${org.id}/invite`, { email, role })); }
        catch (err) { outcomes.push({ invite_email: email, joined: false, emailed: false, invite_url: "" }); void err; }
      }
      setSent(outcomes);
      if (type === "business") setStep("brand");
      else router.replace(`/org/${org.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That address is taken by another organisation. Change it and try again.");
        setSlugTouched(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Could not create the organisation.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function readSite(e: React.FormEvent) {
    e.preventDefault();
    if (!made || !site.trim()) return;
    setBusy(true); setReading(true); setError("");
    try {
      const read = await brand.discover(made.id, site.trim());
      setProfile(read);
      setIdentity(read.identity ?? {});
      if (read.company_name && read.company_name !== made.name) {
        try { setMade(await api.put<Org>(`/api/orgs/${made.id}`, { name: read.company_name })); } catch { /* cosmetic */ }
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not read that site. You can skip this and add it later from Settings → Brand.");
    } finally {
      setBusy(false); setReading(false);
    }
  }

  async function saveBrand() {
    if (!made) return;
    setBusy(true);
    try {
      if (profile) await brand.update(made.id, cleanedForSave(profile.company_name ?? made.name, identity, profile.design ?? {}));
      else await brand.skip(made.id);
    } catch { /* the profile is stored server-side by the read either way */ }
    router.replace(`/org/${made.id}`);
  }

  async function accept(orgId: string, inviteId: string) {
    setBusy(true);
    try {
      await api.post(`/api/orgs/${orgId}/invite/${inviteId}/accept`, {});
      router.replace(`/org/${orgId}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not accept the invitation.");
      setBusy(false);
    }
  }

  const stepIndex = step === "type" ? 0 : step === "brand" ? 2 : step === "about" ? 3 : 1;
  const segments = type === "business" ? 4 : 3;

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-16 dark:bg-slate-950">
      <div className="mx-auto w-full max-w-xl">
        <Mark />
        <Progress at={stepIndex} total={segments} />

        {step === "type" && (
          <section data-step="type">
            <h1 className="text-center text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Select an account type</h1>
            <div role="radiogroup" aria-label="Account type" className="mt-8 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
              {ACCOUNT_TYPES.map((a, i) => (
                <button key={a.value} type="button" role="radio" aria-checked={type === a.value} onClick={() => setType(a.value)}
                        className={`flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors ${i > 0 ? "border-t border-slate-100 dark:border-slate-800" : ""} ${type === a.value ? "bg-slate-50 dark:bg-slate-800/60" : "hover:bg-slate-50 dark:hover:bg-slate-800/40"}`}>
                  <span>
                    <span className="block text-[15px] font-medium text-slate-900 dark:text-white">{a.title}</span>
                    <span className="block text-sm text-slate-500 dark:text-slate-400">{a.hint}</span>
                  </span>
                  <span aria-hidden="true" className={`grid h-5 w-5 shrink-0 place-items-center rounded-full border-2 ${type === a.value ? "border-blue-600" : "border-slate-300 dark:border-slate-600"}`}>
                    {type === a.value && <span className="h-2.5 w-2.5 rounded-full bg-blue-600" />}
                  </span>
                </button>
              ))}
            </div>
            <Button type="button" onClick={chooseType} className="mt-8 h-12 w-full rounded-full text-base">Continue</Button>
          </section>
        )}

        {step === "create" && (
          <form data-step="create" onSubmit={createOrganisation} className="space-y-7">
            <h1 className="text-center text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Create an organization</h1>
            <div className="space-y-1.5">
              <Label htmlFor="org-name" className="text-[15px] font-medium">Organization name</Label>
              <p className="text-sm text-slate-500">A name for your organization.</p>
              <Input id="org-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Organization name" autoFocus required className="h-12 rounded-full px-4" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="org-slug" className="text-[15px] font-medium">Organization slug</Label>
              <p className="text-sm text-slate-500">A unique URL-friendly identifier for your organization.</p>
              <Input id="org-slug" value={slug} onChange={(e) => { setSlugTouched(true); setSlug(e.target.value.toLowerCase()); }} placeholder="organization-slug" className="h-12 rounded-full px-4 font-mono text-sm" aria-invalid={Boolean(slugWarning)} />
              {slugWarning && <p className="text-sm text-amber-700 dark:text-amber-400">{slugWarning}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="org-invites" className="text-[15px] font-medium">Invite members <span className="ml-1 text-sm font-normal text-slate-400">Optional</span></Label>
              <p className="text-sm text-slate-500">Add team members to collaborate. Separate several emails with commas.</p>
              <Input id="org-invites" value={invites} onChange={(e) => setInvites(e.target.value)} placeholder="friend@company.dev" className="h-12 rounded-full px-4" aria-invalid={Boolean(emailWarning)} />
              {emailWarning && <p className="text-sm text-amber-700 dark:text-amber-400">{emailWarning}</p>}
              {emailList.length > 0 && (
                <fieldset className="mt-3 space-y-2">
                  <legend className="text-sm font-medium text-slate-700 dark:text-slate-300">Their role</legend>
                  {ROLES.map((r) => (
                    <label key={r.value} className="flex cursor-pointer items-start gap-3 text-sm">
                      <input type="radio" name="role" className="mt-1 accent-blue-600" checked={role === r.value} onChange={() => setRole(r.value)} />
                      <span><span className="font-medium text-slate-900 dark:text-white">{r.title}</span> <span className="text-slate-500">— {r.hint}</span></span>
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
            <div className="space-y-1.5">
              <Label className="text-[15px] font-medium">Organization avatar <span className="ml-1 text-sm font-normal text-slate-400">Optional</span></Label>
              <div className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <span className="grid h-12 w-12 place-items-center rounded-full bg-blue-50 text-blue-600 dark:bg-blue-950"><Building2 className="h-6 w-6" /></span>
                <span className="flex-1 truncate text-sm text-slate-600 dark:text-slate-300">{logo ? logo.name : "Drag and drop or choose a file"}</span>
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => setLogo(e.target.files?.[0] ?? null)} />
                <Button type="button" variant="outline" className="rounded-full" onClick={() => fileRef.current?.click()}><Upload className="mr-2 h-4 w-4" />Choose file</Button>
              </div>
            </div>
            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" className="h-12 rounded-full px-5" onClick={() => setStep("type")} disabled={busy}>Back</Button>
              <Button type="submit" className="h-12 flex-1 rounded-full text-base" disabled={busy || !name.trim() || Boolean(slugWarning) || Boolean(emailWarning)}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}Continue
              </Button>
            </div>
          </form>
        )}

        {step === "brand" && made && (
          <section data-step="brand" style={accent ? ({ ["--ob-accent" as string]: accent, ["--ob-on-accent" as string]: onAccent } as React.CSSProperties) : undefined}>
            {!profile && !reading && (
              <form onSubmit={readSite} className="space-y-7">
                <div className="text-center">
                  <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Where can we find {made.name}?</h1>
                  <p className="mx-auto mt-3 max-w-md text-[15px] text-slate-500 dark:text-slate-400">
                    Give us your web address and we read what your company does and what it looks like — your colours, type and mark. Every app you build here can then wear them.
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="org-site" className="text-[15px] font-medium">Company website</Label>
                  <Input id="org-site" value={site} onChange={(e) => { setSite(e.target.value); setError(""); }} placeholder="acme.com" autoFocus autoCapitalize="off" autoCorrect="off" spellCheck={false} className="h-12 rounded-full px-4" />
                </div>
                {sent.length > 0 && (
                  <ul className="space-y-1 text-sm text-slate-500 dark:text-slate-400">
                    {sent.map((o) => (
                      <li key={o.invite_email ?? ""} className="flex items-start gap-2">
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                        <span>{o.invite_email}: {o.joined ? "already had an account and is in." : o.emailed ? "invited by email." : o.invite_url ? <>invited — pass them <code className="break-all text-xs">{o.invite_url}</code></> : "invited."}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                <div className="flex items-center gap-2">
                  <Button type="button" variant="ghost" className="h-12 rounded-full px-5" onClick={saveBrand} disabled={busy}>Skip for now</Button>
                  <Button type="submit" className="h-12 flex-1 rounded-full text-base" disabled={busy || !site.trim()}>Read my site</Button>
                </div>
                <p className="text-center text-xs text-slate-400">You can finish this any time from Settings → Brand.</p>
              </form>
            )}
            {reading && (
              <div className="text-center">
                <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Reading {site.trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "")}</h1>
                <div className="mx-auto mt-6 max-w-md text-left"><ReadingSequence host={site.trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "") || "your site"} /></div>
              </div>
            )}
            {profile && !reading && (
              <div className="space-y-7">
                <div className="text-center">
                  <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">This is how {profile.company_name || made.name} looks</h1>
                  <p className="mx-auto mt-3 max-w-md text-[15px] text-slate-500 dark:text-slate-400">{describeDesign(profile.design ?? {}) || "Read from your site. Every app you build here can be built in this language."}</p>
                </div>
                <div className="rounded-2xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
                  <div className="flex items-start gap-5">
                    {logoSrc && (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={logoSrc} alt={`${profile.company_name || made.name} logo`} className="h-14 w-14 shrink-0 rounded-xl object-contain" />
                    )}
                    <div className="min-w-0 flex-1 space-y-3">
                      <TypeSpecimen name={profile.company_name || made.name} family={profile.design?.typography?.fontFamilyHeading || profile.design?.typography?.fontFamilyBase} />
                      <PaletteStrip design={profile.design ?? {}} animate />
                    </div>
                  </div>
                </div>

                {/* EVERYTHING THE READ FOUND, laid out so a wrong value is seen here
                    rather than discovered in the first app: each colour with its
                    role and hex, each typeface with its job, shape and density,
                    the voice, and the guidelines the agents will be shown. */}
                <BrandReadout profile={profile} />
                <ReadFromNote sourceUrl={profile.source_url} rendered={profile.evidence?.rendered} />
                {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
                <div className="flex items-center gap-2">
                  <Button type="button" variant="ghost" className="h-12 rounded-full px-5" onClick={() => { setProfile(null); setSite(""); }} disabled={busy}>Try another site</Button>
                  <Button type="button" onClick={() => setStep("about")} disabled={busy}
                          className={`h-12 flex-1 rounded-full text-base ${accent ? "bg-[var(--ob-accent)] text-[var(--ob-on-accent)] hover:bg-[var(--ob-accent)] hover:brightness-110" : ""}`}>
                    Continue
                  </Button>
                </div>
                <p className="text-center text-xs text-slate-400">Fine-tune the colours and type any time in Settings → Brand.</p>
              </div>
            )}
          </section>
        )}

        {step === "about" && made && (
          <section data-step="about" style={accent ? ({ ["--ob-accent" as string]: accent, ["--ob-on-accent" as string]: onAccent } as React.CSSProperties) : undefined} className="space-y-7">
            <div className="text-center">
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">About {profile?.company_name || made.name}</h1>
              <p className="mx-auto mt-3 max-w-md text-[15px] text-slate-500 dark:text-slate-400">
                We drafted these from your site. Fix anything that is wrong — the apps you build will speak in these words.
              </p>
            </div>
            <div className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
              {(["who_you_are", "what_you_do", "how_you_do_it"] as const).map((key) => (
                <DiscoveryQuestionField key={key} which={key} rows={3} value={(identity[key] as string) ?? ""}
                                        onChange={(v) => setIdentity((i) => ({ ...i, [key]: v }))} />
              ))}
              <div className="border-t border-slate-200 pt-5 dark:border-slate-800">
                <p className="mb-3 text-sm font-medium text-slate-700 dark:text-slate-300">What the read inferred around them</p>
                <IdentityDetailFields identity={identity} onChange={(key, value) => setIdentity((i) => ({ ...i, [key]: value }))} />
              </div>
            </div>
            {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
            <div className="flex items-center gap-2">
              <Button type="button" variant="ghost" className="h-12 rounded-full px-5" onClick={() => setStep("brand")} disabled={busy}>Back</Button>
              <Button type="button" onClick={saveBrand} disabled={busy}
                      className={`h-12 flex-1 rounded-full text-base ${accent ? "bg-[var(--ob-accent)] text-[var(--ob-on-accent)] hover:bg-[var(--ob-accent)] hover:brightness-110" : ""}`}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Check className="mr-2 h-4 w-4" />}Save and start building
              </Button>
            </div>
            <p className="text-center text-xs text-slate-400">Every one of these can be changed later in Settings → Brand.</p>
          </section>
        )}

        {step === "join" && (
          <section data-step="join" className="text-center">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">Join a team</h1>
            {checking && !waiting && <Loader2 className="mx-auto mt-8 h-6 w-6 animate-spin text-slate-400" />}
            {waiting && (waiting.memberships.length > 0 || waiting.pending.length > 0) && (
              <div className="mt-8 space-y-3 text-left">
                {waiting.memberships.map((m) => (
                  <div key={m.org_id} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-5 py-4 dark:border-slate-800 dark:bg-slate-900">
                    <span className="flex items-center gap-3">
                      <Users className="h-5 w-5 text-slate-400" />
                      <span><span className="block font-medium text-slate-900 dark:text-white">{m.name}</span><span className="block text-sm text-slate-500">{m.invited ? "You were invited" : "You belong here"} as {m.role}</span></span>
                    </span>
                    <Button type="button" className="rounded-full" onClick={() => router.replace(`/org/${m.org_id}`)}>Open</Button>
                  </div>
                ))}
                {waiting.pending.map((p) => (
                  <div key={p.invite_id} className="flex items-center justify-between rounded-xl border border-blue-200 bg-blue-50/50 px-5 py-4 dark:border-blue-900 dark:bg-blue-950/30">
                    <span className="flex items-center gap-3">
                      <Users className="h-5 w-5 text-blue-500" />
                      <span><span className="block font-medium text-slate-900 dark:text-white">{p.name}</span><span className="block text-sm text-slate-500">Invited you as {p.role}</span></span>
                    </span>
                    <Button type="button" className="rounded-full" disabled={busy} onClick={() => accept(p.org_id, p.invite_id)}>Accept</Button>
                  </div>
                ))}
              </div>
            )}
            {waiting && waiting.memberships.length === 0 && waiting.pending.length === 0 && (
              <div className="mt-8 rounded-xl border border-dashed border-slate-300 bg-white p-6 text-left dark:border-slate-700 dark:bg-slate-900">
                <p className="text-[15px] text-slate-700 dark:text-slate-200">
                  Nobody has invited <strong>{waiting.email || me?.email}</strong> yet.
                </p>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  Ask your organisation's administrator to invite this exact address from their Settings → Members. The moment they do, it appears here; you will not need anything else.
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <Button type="button" variant="outline" className="rounded-full" onClick={lookWhoInvitedMe} disabled={checking}>
                    <RefreshCw className={`mr-2 h-4 w-4 ${checking ? "animate-spin" : ""}`} />Check again
                  </Button>
                  <Button type="button" variant="ghost" className="rounded-full" onClick={() => { setType("personal"); setStep("create"); }}>
                    Create an organisation instead
                  </Button>
                </div>
              </div>
            )}
            {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}
            <Button type="button" variant="ghost" className="mt-6 h-11 rounded-full px-5" onClick={() => setStep("type")}>Back</Button>
          </section>
        )}
      </div>
    </div>
  );
}

export default function StartPage() {
  return (
    <AuthGuard>
      <Suspense fallback={<div className="flex h-screen items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>}>
        <StartInner />
      </Suspense>
    </AuthGuard>
  );
}
