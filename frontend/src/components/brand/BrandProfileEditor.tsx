"use client";

/**
 * What the discovery read, laid out so a person can correct it.
 *
 * EVERYTHING IS A DRAFT. The read is a first pass over somebody's own website
 * and it will be wrong about something — a brand colour taken from a
 * promotional banner, a sentence that describes last year's positioning. The
 * whole point of showing it is that the person who works there can fix it in
 * ten seconds, so every field here is an input rather than a label.
 *
 * Used by the onboarding wizard and by Settings, with the same shape in both:
 * the thing you check the first time is the thing you come back and change.
 * `onSave` is what differs — the wizard saves and moves on, Settings saves and
 * stays.
 */

import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  BrandDesign,
  BrandIdentity,
  BrandProfile,
  COLOR_ROLES,
  DISCOVERY_QUESTIONS,
  brand,
} from "@/lib/brand";

interface Props {
  orgId: string;
  profile: BrandProfile;
  onSaved: (profile: BrandProfile) => void;
  saveLabel?: string;
  /** Rendered beside the save button — the wizard puts "Skip" there. */
  secondaryAction?: React.ReactNode;
}

const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/**
 * The company's mark, fetched with the request's credentials.
 *
 * The endpoint is authenticated and an `<img src>` sends no Authorization
 * header, so the bytes have to come through `fetch` and reach the element as
 * an object URL. Revoked on unmount and before each refetch, because an
 * object URL holds its blob in memory until something lets go of it.
 */
function useBrandLogo(orgId: string, present: boolean): string | null {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!present) {
      setSrc(null);
      return;
    }
    let url: string | null = null;
    let cancelled = false;
    brand.logoObjectUrl(orgId).then((got) => {
      url = got;
      if (cancelled) {
        if (got) URL.revokeObjectURL(got);
        return;
      }
      setSrc(got);
    });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [orgId, present]);
  return src;
}

export function BrandProfileEditor({
  orgId,
  profile,
  onSaved,
  saveLabel = "Save",
  secondaryAction,
}: Props) {
  const [name, setName] = useState(profile.company_name ?? "");
  const [identity, setIdentity] = useState<BrandIdentity>(profile.identity ?? {});
  const [design, setDesign] = useState<BrandDesign>(profile.design ?? {});
  const logoSrc = useBrandLogo(orgId, profile.has_logo);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function setColor(role: string, value: string) {
    setSaved(false);
    setDesign((d) => ({
      ...d,
      colors: { ...(d.colors ?? {}), [role]: value },
    }));
  }

  function setFont(role: string, value: string) {
    setSaved(false);
    setDesign((d) => ({
      ...d,
      typography: { ...(d.typography ?? {}), [role]: value },
    }));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      // Blank colours are removed rather than stored as "": an empty role in
      // the Blueprint would overwrite the design agent's considered choice
      // with nothing, which is worse than leaving the role open.
      const colors = Object.fromEntries(
        Object.entries(design.colors ?? {}).filter(([, v]) => v && HEX.test(v)),
      );
      const typography = Object.fromEntries(
        Object.entries(design.typography ?? {}).filter(([, v]) => v?.trim()),
      );
      const updated = await brand.update(orgId, {
        company_name: name,
        identity,
        design: { ...design, colors, typography },
      });
      setSaved(true);
      onSaved(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that");
    } finally {
      setSaving(false);
    }
  }

  const invalid = Object.entries(design.colors ?? {}).filter(
    ([, v]) => v && !HEX.test(v),
  );

  return (
    <div className="space-y-8">
      {/* Name + mark */}
      <section className="space-y-3">
        <div className="flex items-end gap-4">
          {logoSrc && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logoSrc}
              alt={`${name || "Company"} logo`}
              className="h-12 w-12 shrink-0 rounded-lg border border-slate-200 object-contain p-1.5 dark:border-slate-800"
            />
          )}
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="company-name" className="text-sm font-medium">
              Company name
            </Label>
            <Input
              id="company-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                setSaved(false);
              }}
              placeholder="Your company"
              className="h-10"
            />
          </div>
        </div>
        {profile.source_url && (
          <p className="text-xs text-slate-500">
            Read from{" "}
            <span className="font-mono text-slate-600 dark:text-slate-400">
              {profile.source_url}
            </span>
            {profile.evidence?.rendered === false &&
              " — page source only, so the colours are what the markup states outright."}
          </p>
        )}
      </section>

      {/* The three questions */}
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            About the company
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Apps built here use this for vocabulary and tone — not for what
            they do.
          </p>
        </div>
        {DISCOVERY_QUESTIONS.map((q) => (
          <div key={q.key} className="space-y-1.5">
            <Label htmlFor={q.key} className="text-sm font-medium">
              {q.label}
            </Label>
            <Textarea
              id={q.key}
              rows={2}
              value={(identity[q.key] as string) ?? ""}
              placeholder={q.hint}
              onChange={(e) => {
                setIdentity((i) => ({ ...i, [q.key]: e.target.value }));
                setSaved(false);
              }}
            />
          </div>
        ))}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {(
            [
              ["industry", "Industry"],
              ["audience", "Who it is for"],
              ["tone", "How the writing sounds"],
              ["voice", "Voice"],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className="space-y-1.5">
              <Label htmlFor={key} className="text-sm font-medium">
                {label}
              </Label>
              <Input
                id={key}
                className="h-10"
                value={(identity[key] as string) ?? ""}
                onChange={(e) => {
                  setIdentity((i) => ({ ...i, [key]: e.target.value }));
                  setSaved(false);
                }}
              />
            </div>
          ))}
        </div>
      </section>

      {/* The design language */}
      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Design language
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Apps built in this language use these values exactly.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {COLOR_ROLES.map((role) => {
            const value = design.colors?.[role.key] ?? "";
            const bad = Boolean(value) && !HEX.test(value);
            return (
              <div key={role.key} className="space-y-1.5">
                <Label htmlFor={`c-${role.key}`} className="text-xs font-medium">
                  {role.label}
                </Label>
                <div
                  className={[
                    "flex items-center gap-2 rounded-lg border px-2 py-1.5",
                    bad
                      ? "border-red-400"
                      : "border-slate-200 dark:border-slate-800",
                  ].join(" ")}
                >
                  <span
                    aria-hidden
                    className="h-6 w-6 shrink-0 rounded border border-slate-200 dark:border-slate-700"
                    style={{ background: HEX.test(value) ? value : "transparent" }}
                  />
                  <input
                    id={`c-${role.key}`}
                    value={value}
                    placeholder="—"
                    spellCheck={false}
                    onChange={(e) => setColor(role.key, e.target.value.trim())}
                    className="w-full bg-transparent font-mono text-xs outline-none"
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {(
            [
              ["fontFamilyHeading", "Headings"],
              ["fontFamilyBase", "Body text"],
            ] as const
          ).map(([key, label]) => (
            <div key={key} className="space-y-1.5">
              <Label htmlFor={key} className="text-sm font-medium">
                {label}
              </Label>
              <Input
                id={key}
                className="h-10"
                placeholder="Left to the app's own design"
                value={design.typography?.[key] ?? ""}
                onChange={(e) => setFont(key, e.target.value)}
              />
            </div>
          ))}
        </div>
      </section>

      {invalid.length > 0 && (
        <p className="text-sm text-red-600 dark:text-red-400">
          {invalid.map(([k]) => k).join(", ")} must be a hex colour like
          #1B7F5A — anything else is dropped when saving.
        </p>
      )}
      {error && (
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      )}

      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving} className="h-10">
          {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          {!saving && saved && <Check className="mr-2 h-4 w-4" />}
          {saveLabel}
        </Button>
        {secondaryAction}
      </div>
    </div>
  );
}
