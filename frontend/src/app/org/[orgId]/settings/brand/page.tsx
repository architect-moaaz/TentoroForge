"use client";

/**
 * Settings → Brand: finish the discovery, or change what it found.
 *
 * The other half of the onboarding's skip. Somebody who said "not now" on
 * their first day — or whose site could not be read, or who has since
 * redesigned — comes here, and the screen states which of those they are
 * rather than showing the same empty form to all three.
 *
 * Reading is a member's right and changing is an admin's, because a colour
 * changed here changes every application built afterwards. The backend
 * enforces that; this only avoids offering a button that would 403.
 */

import { use, useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  FileText,
  Globe,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { BrandProfileEditor } from "@/components/brand/BrandProfileEditor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useIsOrgAdmin } from "@/lib/org-admin";
import { ApiError } from "@/lib/api";
import { BrandProfile, brand, describeDesign } from "@/lib/brand";

export default function BrandSettingsPage({
  params,
}: {
  params: Promise<{ orgId: string }>;
}) {
  const { orgId } = use(params);
  const isAdmin = useIsOrgAdmin(orgId);

  const [profile, setProfile] = useState<BrandProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showDoc, setShowDoc] = useState(false);

  useEffect(() => {
    let cancelled = false;
    brand
      .get(orgId)
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setUrl(p?.source_url ?? "");
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [orgId]);

  async function runDiscovery(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setRunning(true);
    setError(null);
    try {
      setProfile(await brand.discover(orgId, url.trim()));
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not read that site.",
      );
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  const unfinished = !profile || !profile.usable;

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <header className="mb-8">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
          Brand
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          What this company is and what it looks like. Apps built here can be
          built in this design language — Smith asks which, once per app.
        </p>
      </header>

      {/* What state this organisation is in, said plainly. */}
      {unfinished && (
        <div className="mb-8 rounded-lg border border-slate-200 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-900/50">
          <p className="text-sm font-medium text-slate-900 dark:text-white">
            {profile?.status === "skipped"
              ? "You skipped this during setup."
              : profile?.status === "failed"
                ? "That site couldn't be read."
                : profile
                  ? "There isn't enough here to build from yet."
                  : "No design language on record."}
          </p>
          {profile?.failure_reason && (
            <p className="mt-1.5 flex items-start gap-2 text-sm text-slate-500">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              {profile.failure_reason}
            </p>
          )}
          <p className="mt-1.5 text-sm text-slate-500">
            Give us your web address and we&apos;ll read your colours, type and
            mark from it — or fill it in by hand below.
          </p>
        </div>
      )}

      {/* Run or re-run the read. */}
      {isAdmin && (
        <form onSubmit={runDiscovery} className="mb-10 space-y-3">
          <Label htmlFor="brand-url" className="text-sm font-medium">
            Company website
          </Label>
          <div className="flex items-center gap-3">
            <div className="flex flex-1 items-center gap-2 rounded-lg border border-slate-200 px-3 dark:border-slate-800">
              <Globe className="h-4 w-4 shrink-0 text-slate-400" />
              <Input
                id="brand-url"
                value={url}
                onChange={(e) => {
                  setUrl(e.target.value);
                  setError(null);
                }}
                placeholder="acme.com"
                className="h-10 border-0 px-0 shadow-none focus-visible:ring-0"
              />
            </div>
            <Button type="submit" disabled={running || !url.trim()} className="h-10">
              {running ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Reading…
                </>
              ) : (
                <>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  {profile?.usable ? "Read it again" : "Read my site"}
                </>
              )}
            </Button>
          </div>
          {profile?.usable && (
            <p className="text-xs text-slate-400">
              Reading it again replaces what&apos;s below. Apps already built
              keep the design they were built with.
            </p>
          )}
          {error && (
            <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          )}
        </form>
      )}

      {profile?.usable && (
        <p className="mb-6 inline-flex items-center gap-1.5 rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <Check className="h-3 w-3" />
          {describeDesign(profile.design)}
        </p>
      )}

      {isAdmin ? (
        <BrandProfileEditor
          orgId={orgId}
          profile={
            profile ?? {
              status: "pending",
              source_url: null,
              company_name: null,
              failure_reason: null,
              identity: {},
              design: {},
              evidence: {},
              design_md: "",
              usable: false,
              has_logo: false,
            }
          }
          onSaved={setProfile}
          saveLabel="Save brand"
        />
      ) : (
        <p className="rounded-lg border border-slate-200 p-5 text-sm text-slate-500 dark:border-slate-800">
          Only an organisation admin can change the design language. You can
          read it below.
        </p>
      )}

      {/* The document the generation process actually reads. */}
      {profile?.design_md && (
        <section className="mt-10 border-t border-slate-200 pt-6 dark:border-slate-800">
          <button
            type="button"
            onClick={() => setShowDoc((v) => !v)}
            className="flex items-center gap-2 text-sm font-medium text-slate-700 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
          >
            <FileText className="h-4 w-4" />
            {showDoc ? "Hide" : "Show"} design.md
          </button>
          <p className="mt-1 text-xs text-slate-400">
            This is what the agents are given when an app is built in your
            design language. It is generated from the fields above.
          </p>
          {showDoc && (
            <pre className="mt-4 max-h-[28rem] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs leading-relaxed text-slate-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
              {profile.design_md}
            </pre>
          )}
        </section>
      )}
    </div>
  );
}
