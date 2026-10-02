"use client";

/**
 * The whole company profile on one screen — Settings' half of the fields.
 *
 * EVERYTHING IS A DRAFT. The read is a first pass over somebody's own website
 * and it will be wrong about something — a brand colour taken from a
 * promotional banner, a sentence that describes last year's positioning. The
 * whole point of showing it is that the person who works there can fix it in
 * ten seconds, so every field here is an input rather than a label.
 *
 * NOT A WIZARD, deliberately. Onboarding walks a newcomer through the same
 * fields one question at a time, because somebody meeting this for the first
 * time is being interviewed about their company. Somebody who came back to
 * change one colour is not, and making them click Next four times to reach it
 * would be a worse screen for the more common visit. Same fields
 * (`./fields`), two shapes.
 */

import { useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandDesign, BrandIdentity, BrandProfile, brand } from "@/lib/brand";
import {
  ColorFields,
  CompanyNameField,
  DiscoveryQuestionField,
  HEX,
  IdentityDetailFields,
  InvalidColorNote,
  ReadFromNote,
  TypeFields,
  invalidColors,
  useBrandLogo,
} from "@/components/brand/fields";
import { DISCOVERY_QUESTIONS } from "@/lib/brand";

interface Props {
  orgId: string;
  profile: BrandProfile;
  onSaved: (profile: BrandProfile) => void;
  saveLabel?: string;
  /** Rendered beside the save button. */
  secondaryAction?: React.ReactNode;
}

/**
 * The profile as the API takes it, with the values that mean nothing removed.
 *
 * Blank colours are dropped rather than sent as "": an empty role in the
 * Blueprint would overwrite the design agent's considered choice with
 * nothing, which is worse than leaving the role open for it to decide. Shared
 * with the wizard so both screens save the same shape.
 */
export function cleanedForSave(
  name: string,
  identity: BrandIdentity,
  design: BrandDesign,
) {
  return {
    company_name: name,
    identity,
    design: {
      ...design,
      colors: Object.fromEntries(
        Object.entries(design.colors ?? {}).filter(([, v]) => v && HEX.test(v)),
      ),
      typography: Object.fromEntries(
        Object.entries(design.typography ?? {}).filter(([, v]) => v?.trim()),
      ),
    },
  };
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

  function touch<T>(fn: () => T): T {
    setSaved(false);
    return fn();
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await brand.update(
        orgId,
        cleanedForSave(name, identity, design),
      );
      setSaved(true);
      onSaved(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <CompanyNameField
          name={name}
          logoSrc={logoSrc}
          onName={(v) => touch(() => setName(v))}
        />
        <ReadFromNote
          sourceUrl={profile.source_url}
          rendered={profile.evidence?.rendered}
        />
      </section>

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
          <DiscoveryQuestionField
            key={q.key}
            which={q.key}
            value={(identity[q.key] as string) ?? ""}
            onChange={(v) =>
              touch(() => setIdentity((i) => ({ ...i, [q.key]: v })))
            }
          />
        ))}
        <IdentityDetailFields
          identity={identity}
          onChange={(key, value) =>
            touch(() => setIdentity((i) => ({ ...i, [key]: value })))
          }
        />
      </section>

      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
            Design language
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Apps built in this language use these values exactly.
          </p>
        </div>
        <ColorFields
          design={design}
          onColor={(role, value) =>
            touch(() =>
              setDesign((d) => ({
                ...d,
                colors: { ...(d.colors ?? {}), [role]: value },
              })),
            )
          }
        />
        <TypeFields
          design={design}
          onFont={(role, value) =>
            touch(() =>
              setDesign((d) => ({
                ...d,
                typography: { ...(d.typography ?? {}), [role]: value },
              })),
            )
          }
        />
      </section>

      <InvalidColorNote roles={invalidColors(design)} />
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

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
