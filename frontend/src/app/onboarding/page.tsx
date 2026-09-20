"use client";

/**
 * Where a new account lands: three screens, all of them skippable.
 *
 * WHY IT IS HERE AT ALL. A person signing up is signing up on behalf of a
 * company that already exists, with a website that already says who they are
 * and what they look like. Every app they build here is for that company, and
 * without this every one of them re-invents the palette from a chat message.
 * One question — what is your web address — replaces an interview.
 *
 * WHY IT CREATES THE WORKSPACE. Signup makes a user and nothing else; the
 * profile belongs to an organisation, so one has to exist to hold it. Naming
 * it is also the one unavoidable step, so it is folded into the step that was
 * already being asked rather than added beside it: the address gives a
 * provisional name, and the read replaces it with the real one.
 *
 * SKIPPING IS A FIRST-CLASS PATH, not a grey link in a corner. Someone who
 * joined to try one thing should be building in thirty seconds, and the
 * discovery is offered again in Settings for as long as it is unfinished. The
 * skip is *recorded* rather than ignored, so Settings knows the difference
 * between "not now" and "never heard of it".
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Check,
  Globe,
  Loader2,
  Sparkles,
} from "lucide-react";
import { AuthGuard } from "@/components/auth-guard";
import { BrandProfileEditor } from "@/components/brand/BrandProfileEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";
import {
  BrandProfile,
  brand,
  companyNameFromUrl,
  describeDesign,
  slugFromName,
} from "@/lib/brand";

interface Org {
  id: string;
  name: string;
  slug: string;
}

type Step = "url" | "review";

function OnboardingInner() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("url");
  const [url, setUrl] = useState("");
  const [org, setOrg] = useState<Org | null>(null);
  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

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
  async function createOrg(name: string): Promise<Org> {
    const base = slugFromName(name);
    for (let attempt = 0; attempt < 4; attempt += 1) {
      const slug = attempt === 0
        ? base
        : `${base}-${Math.random().toString(36).slice(2, 6)}`;
      try {
        return await api.post<Org>("/api/orgs", { name, slug });
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

  async function handleDiscover(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const workspace = org ?? (await createOrg(companyNameFromUrl(url)));
      setOrg(workspace);
      const read = await brand.discover(workspace.id, url.trim());
      setProfile(read);
      // The real name, now that the site has stated it. The provisional one
      // came off the hostname and nobody should have to live with it.
      if (read.company_name && read.company_name !== workspace.name) {
        try {
          const renamed = await api.put<Org>(`/api/orgs/${workspace.id}`, {
            name: read.company_name,
          });
          setOrg(renamed);
        } catch {
          // A workspace named after its domain is a cosmetic problem, and
          // losing the design language over one would not be.
        }
      }
      setStep("review");
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

  /** Not now. Recorded when there is a workspace to record it against. */
  async function handleSkip() {
    setBusy(true);
    setError(null);
    try {
      const workspace = org ?? (await createOrg("My workspace"));
      try {
        await brand.skip(workspace.id);
      } catch {
        // Recording the skip is bookkeeping for Settings; failing to record
        // it must not strand somebody on the screen they asked to leave.
      }
      router.replace(`/org/${workspace.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a workspace");
      setBusy(false);
    }
  }

  function finish() {
    if (org) router.replace(`/org/${org.id}`);
  }

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

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

      {step === "url" && (
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
            Tell us about your company
          </h1>
          <p className="mt-2 max-w-xl text-sm text-slate-500">
            Give us your web address and we&apos;ll read what your company does
            and what it looks like — your colours, type and mark. Every app you
            build here can then be built in that language, or given one of its
            own.
          </p>

          <form onSubmit={handleDiscover} className="mt-8 max-w-xl space-y-4">
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
              <Button
                type="submit"
                disabled={busy || !url.trim()}
                className="h-11"
              >
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
                onClick={handleSkip}
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
        </div>
      )}

      {step === "review" && profile && org && (
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">
            Here&apos;s what we read
          </h1>
          <p className="mt-2 max-w-xl text-sm text-slate-500">
            {profile.usable
              ? "Correct anything that isn't right — this is what your apps will be built from."
              : "We couldn't read much from that page. Fill in what you can, or skip it and come back later."}
          </p>
          {profile.usable && (
            <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              <Check className="h-3 w-3" />
              {describeDesign(profile.design)}
            </p>
          )}

          <div className="mt-8">
            <BrandProfileEditor
              orgId={org.id}
              profile={profile}
              onSaved={(saved) => {
                setProfile(saved);
                finish();
              }}
              saveLabel="Save and start building"
              secondaryAction={
                <Button
                  type="button"
                  variant="ghost"
                  onClick={finish}
                  className="h-10 text-slate-500"
                >
                  Skip — I&apos;ll fix this later
                </Button>
              }
            />
          </div>
        </div>
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
