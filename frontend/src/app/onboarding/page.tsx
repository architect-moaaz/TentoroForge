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
 * THE SCREEN WEARS THE BRAND AS IT LEARNS IT. Until the site is read the
 * accent is Forge's own indigo; from the moment a palette comes back, the
 * progress rail, the active step, the primary button and every focus ring are
 * the COMPANY's colour, through one custom property the whole page reads
 * (`--ob-accent`). This is not decoration — it is the feature, demonstrated
 * rather than described, and it makes the question the last step asks answer
 * itself: a brand colour that is wrong is now wearing the entire screen, and
 * nobody has to check a hex code to notice.
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
import { Check, Loader2 } from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import {
  BrandDesign,
  BrandIdentity,
  BrandProfile,
  brand,
  companyNameFromUrl,
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
import {
  PaletteStrip,
  ReadingSequence,
  TypeSpecimen,
} from "@/app/onboarding/moments";

interface Org {
  id: string;
  name: string;
  slug: string;
}

type StepId = "site" | "who" | "what" | "how" | "design";

/** Forge's own accent, worn until the company's is known. */
const FORGE_ACCENT = "#444ce7";

/**
 * The steps, in order. The three discovery questions each get their own,
 * because each is a question; the design language is one step because its
 * fields are a single decision looked at together — a palette is read across
 * its swatches, not one swatch at a time.
 *
 * `title` is the question as a person would be asked it out loud. It is the
 * hero of its screen and set as one, so the screen reads as an interview
 * rather than a form with a heading on top.
 */
const STEPS: { id: StepId; label: string; title: string; blurb: string }[] = [
  {
    id: "site",
    label: "Your site",
    title: "Where can we find you?",
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
    title: "This is how you look",
    blurb:
      "Read from your site. Change anything that isn't right — apps built in this language use these values exactly.",
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

/**
 * Where they are, as a rail rather than a row of chips.
 *
 * Numbered, which the usual advice warns against — but this content genuinely
 * IS a sequence, which is the one case numbering earns. The numbers stay
 * small and quiet; the rail itself carries the progress, and it is painted in
 * the company's colour once there is one.
 */
function StepRail({ index }: { index: number }) {
  const pct = (index / (STEPS.length - 1)) * 100;
  return (
    <nav aria-label="Progress" className="mb-12">
      <div className="relative h-px w-full bg-slate-200 dark:bg-slate-800">
        <div
          className="absolute left-0 top-0 h-px bg-[var(--ob-accent)] transition-all duration-700 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      {/* On a phone the five labels want every pixel of a 375px screen and
          fit only by luck. Below `sm` the rail keeps the bar and says the
          count in words instead — the same orientation, none of the crush. */}
      <p className="mt-3 text-xs text-slate-500 dark:text-slate-400 sm:hidden">
        Step {index + 1} of {STEPS.length}
        <span className="ml-2 font-medium text-slate-900 dark:text-white">
          {STEPS[index].label}
        </span>
      </p>
      <ol className="mt-3 hidden justify-between sm:flex">
        {STEPS.map((step, i) => {
          const done = i < index;
          const here = i === index;
          return (
            <li
              key={step.id}
              aria-current={here ? "step" : undefined}
              className="flex items-baseline gap-1.5"
            >
              <span
                className={[
                  "text-[11px] tabular-nums",
                  here
                    ? "text-[var(--ob-accent)]"
                    : done
                      ? "text-slate-400"
                      : "text-slate-300 dark:text-slate-700",
                ].join(" ")}
              >
                {done ? "✓" : i + 1}
              </span>
              <span
                className={[
                  "text-xs transition-colors",
                  here
                    ? "font-medium text-slate-900 dark:text-white"
                    : done
                      ? "text-slate-500 dark:text-slate-400"
                      : "text-slate-300 dark:text-slate-700",
                ].join(" ")}
              >
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function OnboardingInner() {
  const router = useRouter();
  const [index, setIndex] = useState(0);
  const [url, setUrl] = useState("");
  const [org, setOrg] = useState<Org | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [justRead, setJustRead] = useState(false);

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

  // The one value the whole page's accent comes from. Their colour the moment
  // there is one; Forge's until then.
  const accent = design.colors?.primary || FORGE_ACCENT;
  // WHAT IS READABLE ON IT, which is not always white. A company whose brand
  // is a yellow or a lime gets white-on-yellow if the button hardcodes its
  // own foreground — and this is the screen wearing their colour at its
  // largest. The backend already decided this by luminance when it read the
  // site (`design.readable_on`), and `primaryForeground` is that decision,
  // so it is reused rather than guessed at a second time.
  const onAccent = design.colors?.primaryForeground || "#FFFFFF";

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
    setReading(true);
    setError(null);
    try {
      const workspace = org ?? (await createOrg(companyNameFromUrl(url)));
      setOrg(workspace);
      const read = await brand.discover(workspace.id, url.trim());
      setProfile(read);
      setName(read.company_name ?? "");
      setIdentity(read.identity ?? {});
      setDesign(read.design ?? {});
      setJustRead(true);
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
      setReading(false);
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
    setJustRead(false);
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
  const host = url.trim().replace(/^https?:\/\//i, "").replace(/\/.*$/, "");

  return (
    <div
      // One property, read by the rail, the numbers, the button and every
      // focus ring below. Set from the company's own primary the moment the
      // read lands, which is what makes the screen wear their brand.
      style={{
        ["--ob-accent" as string]: accent,
        ["--ob-on-accent" as string]: onAccent,
      }}
      className="mx-auto min-h-screen w-full max-w-2xl px-6 py-16 sm:py-20"
    >
      <div className="mb-14 flex items-center gap-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-900 text-white dark:bg-white dark:text-slate-900">
          <svg className="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z" />
            <path d="M2 17l10 5 10-5" />
            <path d="M2 12l10 5 10-5" />
          </svg>
        </div>
        <span className="text-sm font-medium tracking-tight text-slate-900 dark:text-white">
          Tentoro Forge
        </span>
      </div>

      <StepRail index={index} />

      {/* The question is the hero of its screen. */}
      <h1 className="max-w-[22ch] text-[2rem] font-semibold leading-[1.15] tracking-[-0.02em] text-slate-900 dark:text-white sm:text-[2.5rem]">
        {step.title}
      </h1>
      <p className="mt-3 max-w-[60ch] text-[15px] leading-relaxed text-slate-500 dark:text-slate-400">
        {step.blurb}
      </p>

      {/* Step 1 — the address, and the read. */}
      {step.id === "site" &&
        (reading ? (
          <ReadingSequence host={host || "your site"} />
        ) : (
          <form onSubmit={readSite} className="mt-10 max-w-xl">
            <Label htmlFor="url" className="sr-only">
              Company website
            </Label>
            <input
              id="url"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value);
                setError(null);
              }}
              placeholder="acme.com"
              autoFocus
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              // Keyboard focus stays visible — it just speaks this input's
              // own idiom. The global `:focus-visible` rule draws a 2px
              // rectangle two pixels off the element, which around a wide
              // borderless underline reads as a stray box rather than as
              // focus. The rule is suppressed here and replaced by the rule
              // already doing the work: the underline itself goes accent.
              // Always 2px so gaining focus never nudges the layout.
              className="w-full border-0 border-b-2 border-slate-200 bg-transparent px-0 pb-3 text-2xl text-slate-900 transition-colors placeholder:text-slate-300 focus:border-[var(--ob-accent)] focus-visible:border-[var(--ob-accent)] focus-visible:outline-none dark:border-slate-700 dark:text-white dark:placeholder:text-slate-600"
            />
            {error && (
              <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>
            )}
            <div className="mt-8 flex items-center gap-2">
              <Button
                type="submit"
                disabled={busy || !url.trim()}
                className="h-11 bg-[var(--ob-accent)] px-6 text-[var(--ob-on-accent)] hover:bg-[var(--ob-accent)] hover:brightness-110"
              >
                Read my site
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
            <p className="mt-4 text-xs text-slate-400">
              You can finish this any time from Settings → Brand.
            </p>
          </form>
        ))}

      {/* Steps 2–4 — one question each, with its draft answer already in it. */}
      {question && (
        <div className="mt-10 max-w-xl space-y-6">
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
        <div className="mt-10 space-y-8">
          <div className="flex items-start gap-5">
            {logoSrc && (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={logoSrc}
                alt={`${name || "Company"} logo`}
                className="h-14 w-14 shrink-0 rounded-xl object-contain"
              />
            )}
            <div className="min-w-0 space-y-3">
              <TypeSpecimen
                name={name || "Your company"}
                family={
                  design.typography?.fontFamilyHeading ||
                  design.typography?.fontFamilyBase
                }
              />
              <PaletteStrip design={design} animate={justRead} />
            </div>
          </div>

          <div className="space-y-6 border-t border-slate-200 pt-8 dark:border-slate-800">
            <CompanyNameField name={name} logoSrc={null} onName={setName} />
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
            <ReadFromNote
              sourceUrl={profile.source_url}
              rendered={profile.evidence?.rendered}
            />
            <InvalidColorNote roles={badColors} />
          </div>
        </div>
      )}

      {/* Back / Continue / Skip — on every step but the first, which has its
          own buttons inside the form so Enter submits the address. */}
      {step.id !== "site" && (
        <div className="mt-12 flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setJustRead(false);
              setIndex(Math.max(0, index - 1));
            }}
            disabled={busy}
            className="h-11 px-5"
          >
            Back
          </Button>
          <Button
            type="button"
            onClick={next}
            disabled={busy}
            className="h-11 bg-[var(--ob-accent)] px-6 text-[var(--ob-on-accent)] hover:bg-[var(--ob-accent)] hover:brightness-110"
          >
            {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {onLast && !busy && <Check className="mr-2 h-4 w-4" />}
            {onLast ? "Save and start building" : "Continue"}
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
        <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>
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
