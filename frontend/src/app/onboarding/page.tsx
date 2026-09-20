"use client";

/**
 * Where a new account lands: a five-step wizard, skippable at every step.
 *
 * WHY IT IS HERE AT ALL. A person signing up is signing up on behalf of a
 * company that already exists, with a website that already says who they are
 * and what they look like. Every app they build here is for that company, and
 * without this every one of them re-invents the palette from a chat message.
 * One question — what is your web address — replaces an interview.
 *
 * WHY A WIZARD AND NOT ONE FORM. The three discovery questions are
 * QUESTIONS — who you are, what you do, how you do it — and a person is
 * answering them about their own company, probably for the first time. Nine
 * inputs on one screen is not an interview, it is a form to get past, and
 * what comes back is whatever the read already filled in, nodded through.
 * One question at a time, each with its draft answer already in the box and
 * room to rewrite it, is the difference between confirming and skimming.
 *
 * Settings is deliberately NOT this (see BrandProfileEditor): somebody
 * returning to change one colour should not be walked through an interview to
 * reach it. Same fields, two shapes.
 *
 * WHY IT CREATES THE WORKSPACE. Signup makes a user and nothing else; the
 * profile belongs to an organisation, so one has to exist to hold it. Naming
 * it is also the one unavoidable step, so it is folded into the step that was
 * already being asked rather than added beside it: the address gives a
 * provisional name, and the read replaces it with the real one.
 *
 * SKIPPING IS A FIRST-CLASS PATH, not a grey link in a corner, and it is
 * available on every step rather than only the first. Someone who joined to
 * try one thing should be building in thirty seconds. The skip is *recorded*
 * rather than ignored, so Settings knows the difference between "not now" and
 * "never heard of it" — and a skip from a later step SAVES what they have
 * already typed, because answering three questions and then leaving must not
 * throw the three answers away.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Globe,
  Loader2,
  Sparkles,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import {
  BrandDesign,
  BrandIdentity,
  BrandProfile,
  brand,
  companyNameFromUrl,
  describeDesign,
  slugFromName,
} from "@/lib/brand";
import { cleanedForSave } from "@/components/brand/BrandProfileEditor";
import {
  ColorFields,
  CompanyNameField,
  DiscoveryQuestionField,
  IdentityDetailFields,
  InvalidColorNote,
  ReadFromNote,
  TypeFields,
  invalidColors,
  useBrandLogo,
} from "@/components/brand/fields";

interface Org {
  id: string;
  name: string;
  slug: string;
}

type StepId = "site" | "who" | "what" | "how" | "design";

/**
 * The steps, in order. The three discovery questions each get their own,
 * because each is a question; the design language is one step because its
 * fields are a single decision looked at together — a palette is read across
 * its swatches, not one swatch at a time.
 */
const STEPS: { id: StepId; label: string; title: string; blurb: string }[] = [
  {
    id: "site",
    label: "Your site",
    title: "Tell us about your company",
    blurb:
      "Give us your web address and we'll read what your company does and what it looks like — your colours, type and mark. Every app you build here can then be built in that language, or given one of its own.",
  },
  {
    id: "who",
    label: "Who you are",
    title: "Who are you?",
    blurb:
      "What kind of organisation this is, and what it exists to do. Apps built here use this for vocabulary and tone — never for what they do.",
  },
  {
    id: "what",
    label: "What you do",
    title: "What do you do?",
    blurb:
      "The product or service, in your own words for your own things. A term you use here outranks a synonym the builder would have chosen.",
  },
  {
    id: "how",
    label: "How you do it",
    title: "How do you do it?",
    blurb:
      "How you work, and what you say makes your way of doing it different.",
  },
  {
    id: "design",
    label: "Design",
    title: "Your design language",
    blurb:
      "Read from your site. Correct anything that isn't right — apps built in this language use these values exactly.",
  },
];

/** Which discovery answer each question step edits. */
const QUESTION_FOR: Partial<Record<StepId, keyof BrandIdentity>> = {
  who: "who_you_are",
  what: "what_you_do",
  how: "how_you_do_it",
};

/** Which extra fields sit beside each question, so none of them go homeless. */
const DETAILS_FOR: Partial<Record<StepId, readonly (keyof BrandIdentity)[]>> = {
  who: ["industry", "audience"],
  what: [],
  how: ["tone", "voice"],
};

function StepBar({ index }: { index: number }) {
  return (
    <ol className="mb-10 flex flex-wrap items-center gap-x-2 gap-y-2">
      {STEPS.map((step, i) => {
        const done = i < index;
        const here = i === index;
        return (
          <li key={step.id} className="flex items-center gap-2">
            <span
              aria-current={here ? "step" : undefined}
              className={[
                "flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium transition-colors",
                here
                  ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
                  : done
                    ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                    : "text-slate-400",
              ].join(" ")}
            >
              <span
                className={[
                  "flex h-4 w-4 items-center justify-center rounded-full text-[10px]",
                  here
                    ? "bg-white/20"
                    : done
                      ? "bg-slate-300 text-slate-700 dark:bg-slate-600 dark:text-white"
                      : "border border-slate-300 dark:border-slate-700",
                ].join(" ")}
              >
                {done ? <Check className="h-2.5 w-2.5" /> : i + 1}
              </span>
              {step.label}
            </span>
            {i < STEPS.length - 1 && (
              <span className="h-px w-4 bg-slate-200 dark:bg-slate-800" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function OnboardingInner() {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const [url, setUrl] = useState("");
  const [org, setOrg] = useState<Org | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  // The answers being edited. Seeded from the read the moment it lands, and
  // held here rather than in each step so moving Back and forward does not
  // lose a word — every step edits one object.
  const [name, setName] = useState("");
  const [identity, setIdentity] = useState<BrandIdentity>({});
  const [design, setDesign] = useState<BrandDesign>({});

  const step = STEPS[index];
  const question = QUESTION_FOR[step.id];
  const logoSrc = useBrandLogo(org?.id ?? "", Boolean(profile?.has_logo));
  const badColors = useMemo(() => invalidColors(design), [design]);

  // SOMEBODY WHO WAS INVITED IS NOT A NEW COMPANY. They already belong to an
  // organisation that has, or will have, a profile of its own — putting them
  // through a company interview would have them describe someone else's
  // business. Straight through to the workspace.
  useEffect(() => {
    let cancelled = false;
    api
      .get<Org[]>("/api/orgs")
      .then((orgs) => {
        if (cancelled) return;
        if (orgs.length > 0) router.replace(`/org/${orgs[0].id}`);
        else setChecked(true);
      })
      .catch(() => !cancelled && setChecked(true));
    return () => {
      cancelled = true;
    };
  }, [router]);

  /** Make the workspace that will hold the profile. Retries a taken slug. */
  async function createOrg(orgName: string): Promise<Org> {
    const base = slugFromName(orgName);
    for (let attempt = 0; attempt < 4; attempt += 1) {
      const slug =
        attempt === 0 ? base : `${base}-${Math.random().toString(36).slice(2, 6)}`;
      try {
        return await api.post<Org>("/api/orgs", { name: orgName, slug });
      } catch (e) {
        // Another company on this platform already has the obvious slug for
        // this name. That is not the person's problem to solve, so it is not
        // shown to them — the next attempt carries a suffix.
        if (e instanceof ApiError && e.status === 409) continue;
        throw e;
      }
    }
    throw new Error("Could not create a workspace with that name");
  }

  /** Step 1: read the site, then walk them through what it found. */
  async function readSite(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const workspace = org ?? (await createOrg(companyNameFromUrl(url)));
      setOrg(workspace);
      const read = await brand.discover(workspace.id, url.trim());
      setProfile(read);
      setName(read.company_name ?? "");
      setIdentity(read.identity ?? {});
      setDesign(read.design ?? {});
      // The real name, now that the site has stated it. The provisional one
      // came off the hostname and nobody should have to live with it.
      if (read.company_name && read.company_name !== workspace.name) {
        try {
          setOrg(
            await api.put<Org>(`/api/orgs/${workspace.id}`, {
              name: read.company_name,
            }),
          );
        } catch {
          // A workspace named after its domain is a cosmetic problem, and
          // losing the design language over one would not be.
        }
      }
      setIndex(1);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not read that site. You can skip this and add it later.",
      );
    } finally {
      setBusy(false);
    }
  }

  /** Save the answers, if there is a workspace and anything to save. */
  async function persist(workspace: Org) {
    try {
      await brand.update(workspace.id, cleanedForSave(name, identity, design));
    } catch {
      // Bookkeeping must not strand somebody on a screen they asked to leave;
      // the discovered profile is already stored server-side either way.
    }
  }

  /**
   * Not now — from any step.
   *
   * From step one that means "I never started", which is what `skip` records.
   * From a later step they HAVE answered things, so those are saved first:
   * leaving must not silently discard three answers somebody just typed.
   */
  async function skip() {
    setBusy(true);
    setError(null);
    try {
      const workspace = org ?? (await createOrg("My workspace"));
      if (profile) await persist(workspace);
      else {
        try {
          await brand.skip(workspace.id);
        } catch {
          // See persist().
        }
      }
      router.replace(`/org/${workspace.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a workspace");
      setBusy(false);
    }
  }

  async function finish() {
    if (!org) return;
    setBusy(true);
    await persist(org);
    router.replace(`/org/${org.id}`);
  }

  function next() {
    if (index < STEPS.length - 1) setIndex(index + 1);
    else void finish();
  }

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  const onLast = index === STEPS.length - 1;

  return (
    <div className="mx-auto min-h-screen w-full max-w-3xl px-6 py-16">
      <div className="mb-10 flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white dark:bg-white dark:text-slate-900">
          <Sparkles className="h-4 w-4" />
        </div>
        <span className="text-lg font-semibold text-slate-900 dark:text-white">
          Tentoro Forge
        </span>
      </div>

      <StepBar index={index} />

      <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
        {step.title}
      </h1>
      <p className="mt-2 max-w-xl text-sm text-slate-500">{step.blurb}</p>

      {/* Step 1 — the address, and the read. */}
      {step.id === "site" && (
        <form onSubmit={readSite} className="mt-8 max-w-xl space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="url" className="text-sm font-medium">
              Company website
            </Label>
            <div className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 dark:border-slate-800">
              <Globe className="h-4 w-4 shrink-0 text-slate-400" />
              <Input
                id="url"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setError(null);
                }}
                placeholder="acme.com"
                autoFocus
                className="h-11 border-0 px-0 shadow-none focus-visible:ring-0"
              />
            </div>
          </div>
          {error && (
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
          <div className="flex items-center gap-3 pt-2">
            <Button type="submit" disabled={busy || !url.trim()} className="h-11">
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Reading your site…
                </>
              ) : (
                <>
                  Continue
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={skip}
              disabled={busy}
              className="h-11 text-slate-500"
            >
              Skip for now
            </Button>
          </div>
          <p className="text-xs text-slate-400">
            You can finish this any time from Settings → Brand.
          </p>
        </form>
      )}

      {/* Steps 2–4 — one question each, with its draft answer already in it. */}
      {question && (
        <div className="mt-8 max-w-xl space-y-5">
          <DiscoveryQuestionField
            which={question}
            value={(identity[question] as string) ?? ""}
            rows={4}
            showLabel={false}
            onChange={(v) => setIdentity((i) => ({ ...i, [question]: v }))}
          />
          <IdentityDetailFields
            identity={identity}
            only={DETAILS_FOR[step.id]}
            onChange={(key, value) =>
              setIdentity((i) => ({ ...i, [key]: value }))
            }
          />
        </div>
      )}

      {/* Step 5 — the design language, looked at together. */}
      {step.id === "design" && profile && org && (
        <div className="mt-8 space-y-6">
          {profile.usable && (
            <p className="inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <Check className="h-3 w-3" />
              {describeDesign(design)}
            </p>
          )}
          <CompanyNameField name={name} logoSrc={logoSrc} onName={setName} />
          <ReadFromNote
            sourceUrl={profile.source_url}
            rendered={profile.evidence?.rendered}
          />
          <ColorFields
            design={design}
            onColor={(role, value) =>
              setDesign((d) => ({
                ...d,
                colors: { ...(d.colors ?? {}), [role]: value },
              }))
            }
          />
          <TypeFields
            design={design}
            onFont={(role, value) =>
              setDesign((d) => ({
                ...d,
                typography: { ...(d.typography ?? {}), [role]: value },
              }))
            }
          />
          <InvalidColorNote roles={badColors} />
        </div>
      )}

      {/* Back / Continue / Skip — on every step but the first, which has its
          own buttons inside the form so Enter submits the address. */}
      {step.id !== "site" && (
        <div className="mt-10 flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={() => setIndex(Math.max(0, index - 1))}
            disabled={busy}
            className="h-11"
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <Button type="button" onClick={next} disabled={busy} className="h-11">
            {busy ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : onLast ? (
              <Check className="mr-2 h-4 w-4" />
            ) : null}
            {onLast ? "Save and start building" : "Continue"}
            {!onLast && <ArrowRight className="ml-2 h-4 w-4" />}
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={skip}
            disabled={busy}
            className="h-11 text-slate-500"
          >
            Finish later
          </Button>
        </div>
      )}
      {step.id !== "site" && error && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>
      )}
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <AuthGuard>
      <OnboardingInner />
    </AuthGuard>
  );
}
