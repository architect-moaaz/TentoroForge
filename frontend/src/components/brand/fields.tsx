"use client";

/**
 * The company profile's fields, as pieces two screens assemble differently.
 *
 * Settings shows all of them at once — somebody who came back to change one
 * colour should not be walked through an interview to reach it. Onboarding
 * shows them one group at a time, because a person meeting this for the first
 * time is answering questions about their company, and a wall of nine inputs
 * is not a question.
 *
 * Both need the SAME fields: the same labels, the same placeholder hints, the
 * same hex validation, the same "blank means leave it open" rule. Writing
 * them twice would mean a correction to the wording of "how the writing
 * sounds" landing in one place and not the other, so they live here and each
 * screen composes them.
 */

import { useEffect, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  BrandDesign,
  BrandIdentity,
  COLOR_ROLES,
  DISCOVERY_QUESTIONS,
  brand,
} from "@/lib/brand";

export const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** The roles whose value is present but not a colour. */
export function invalidColors(design: BrandDesign): string[] {
  return Object.entries(design.colors ?? {})
    .filter(([, v]) => v && !HEX.test(v))
    .map(([k]) => k);
}

/**
 * The company's mark, fetched with the request's credentials.
 *
 * The endpoint is authenticated and an `<img src>` sends no Authorization
 * header, so the bytes have to come through `fetch` and reach the element as
 * an object URL. Revoked on unmount and before each refetch, because an
 * object URL holds its blob in memory until something lets go of it.
 */
export function useBrandLogo(orgId: string, present: boolean): string | null {
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

/** The mark beside the name the company goes by. */
export function CompanyNameField({
  name,
  onName,
  logoSrc,
}: {
  name: string;
  onName: (v: string) => void;
  logoSrc: string | null;
}) {
  return (
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
          onChange={(e) => onName(e.target.value)}
          placeholder="Your company"
          className="h-10"
        />
      </div>
    </div>
  );
}

/** Where the values came from, when they were read rather than typed. */
export function ReadFromNote({
  sourceUrl,
  rendered,
}: {
  sourceUrl: string | null;
  rendered?: unknown;
}) {
  if (!sourceUrl) return null;
  return (
    <p className="text-xs text-slate-500">
      Read from{" "}
      <span className="font-mono text-slate-600 dark:text-slate-400">
        {sourceUrl}
      </span>
      {rendered === false &&
        " — page source only, so the colours are what the markup states outright."}
    </p>
  );
}

/**
 * One of the three discovery questions.
 *
 * `rows` differs by screen on purpose: two lines is right beside eight other
 * fields in Settings, and cramped when the question is the only thing on the
 * screen.
 */
export function DiscoveryQuestionField({
  which,
  value,
  onChange,
  rows = 2,
  showLabel = true,
}: {
  which: (typeof DISCOVERY_QUESTIONS)[number]["key"];
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  showLabel?: boolean;
}) {
  const q = DISCOVERY_QUESTIONS.find((d) => d.key === which);
  if (!q) return null;
  return (
    <div className="space-y-1.5">
      {showLabel && (
        <Label htmlFor={q.key} className="text-sm font-medium">
          {q.label}
        </Label>
      )}
      <Textarea
        id={q.key}
        rows={rows}
        value={value}
        placeholder={q.hint}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

const DETAILS = [
  ["industry", "Industry"],
  ["audience", "Who it is for"],
  ["tone", "How the writing sounds"],
  ["voice", "Voice"],
] as const;

/** What the reading inferred around the three answers. */
export function IdentityDetailFields({
  identity,
  onChange,
  only,
}: {
  identity: BrandIdentity;
  onChange: (key: keyof BrandIdentity, value: string) => void;
  /** Restrict to a few keys — the wizard puts each beside its own question. */
  only?: readonly (keyof BrandIdentity)[];
}) {
  const shown = only
    ? DETAILS.filter(([key]) => only.includes(key))
    : DETAILS;
  if (shown.length === 0) return null;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {shown.map(([key, label]) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={key} className="text-sm font-medium">
            {label}
          </Label>
          <Input
            id={key}
            className="h-10"
            value={(identity[key] as string) ?? ""}
            onChange={(e) => onChange(key, e.target.value)}
          />
        </div>
      ))}
    </div>
  );
}

/** The palette, as swatches somebody can correct. */
export function ColorFields({
  design,
  onColor,
}: {
  design: BrandDesign;
  onColor: (role: string, value: string) => void;
}) {
  return (
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
                bad ? "border-red-400" : "border-slate-200 dark:border-slate-800",
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
                onChange={(e) => onColor(role.key, e.target.value.trim())}
                className="w-full bg-transparent font-mono text-xs outline-none"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const FACES = [
  ["fontFamilyHeading", "Headings"],
  ["fontFamilyBase", "Body text"],
] as const;

export function TypeFields({
  design,
  onFont,
}: {
  design: BrandDesign;
  onFont: (role: string, value: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {FACES.map(([key, label]) => (
        <div key={key} className="space-y-1.5">
          <Label htmlFor={key} className="text-sm font-medium">
            {label}
          </Label>
          <Input
            id={key}
            className="h-10"
            placeholder="Left to the app's own design"
            value={design.typography?.[key] ?? ""}
            onChange={(e) => onFont(key, e.target.value)}
          />
        </div>
      ))}
    </div>
  );
}

/** The message shown when a colour box holds something that is not a colour. */
export function InvalidColorNote({ roles }: { roles: string[] }) {
  if (roles.length === 0) return null;
  return (
    <p className="text-sm text-red-600 dark:text-red-400">
      {roles.join(", ")} must be a hex colour like #1B7F5A — anything else is
      dropped when saving.
    </p>
  );
}
