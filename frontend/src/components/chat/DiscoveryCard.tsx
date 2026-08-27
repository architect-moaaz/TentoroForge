"use client";

import { useState } from "react";
import {
  Sparkles,
  ShieldCheck,
  Palette,
  AlertTriangle,
  HelpCircle,
  Layers,
  Swords,
  MessageSquare,
  Pencil,
  Zap,
  CheckCircle2,
} from "lucide-react";
import { AdjustPanel } from "./AdjustPanel";

/**
 * DiscoveryCard — renders the domain-discovery dossier emitted by
 * `agents/domain_agent.py::run_domain_discovery` and lets the user review +
 * optionally edit two fields (domain label + complianceNotes) before
 * triggering the rest of the generation pipeline.
 *
 * Approval sends one of:
 *   `[APPROVE_DISCOVERY]`                         — accept as-is
 *   `[APPROVE_DISCOVERY] {"domain":"…",           — accept with edits
 *                          "complianceNotes":["…"]}`
 *
 * The backend's _parse_discovery_edits whitelist matches the editable
 * keys here (`domain`, `complianceNotes`). Adding new editable fields
 * requires updating both sides.
 */

const COMPLIANCE_OPTIONS = [
  "none",
  "hipaa",
  "pci",
  "gdpr",
  "sox",
  "fda",
  "ferpa",
  "ada-wcag",
] as const;

type ComplianceRegime = (typeof COMPLIANCE_OPTIONS)[number];

interface DesignPattern {
  name: string;
  description: string;
  evidence?: string[];
}

interface VisualLanguage {
  paletteCharacter?: string;
  typographyTone?: string;
  densityPreference?: string;
}

interface EntitySuggestion {
  name: string;
  likelyFields?: string[];
}

interface Discovery {
  domain?: string;
  domainAliases?: string[];
  confidence?: number;
  description?: string;
  designPatterns?: DesignPattern[];
  visualLanguage?: VisualLanguage;
  entitySuggestions?: EntitySuggestion[];
  complianceNotes?: string[];
  commonPitfalls?: string[];
  uncertainAreas?: string[];
  source?: string;
  searchedWeb?: boolean;
  elapsedSeconds?: number;
}

interface DiscoveryCardProps {
  discovery: Discovery;
  onApprove: (signal: string) => void;
  /** Legacy free-text fallback. When `projectId` + `onDiscoveryUpdated`
   *  are provided the card opens the inline AdjustPanel instead and
   *  this becomes a no-op. */
  onAdjust: () => void;
  disabled?: boolean;
  /** B-007: The Fast/Complete picker collapses to a compact
   *  "Chosen: Fast" chip when the user has already picked a profile
   *  for this project (or when this card is not the latest discovery
   *  message). Prevents the picker from appearing on historical
   *  messages after generation completes. */
  alreadyChosen?: "fast" | "complete" | null;
  /** Enables the reliable in-place Adjust-strategy flow for the
   *  dossier. Without both fields, Adjust falls back to `onAdjust`
   *  (free-text chat). */
  projectId?: string;
  /** Called with the new dossier after each Adjust turn. Parent should
   *  swap the card's `discovery` prop so users see the current state. */
  onDiscoveryUpdated?: (updated: Discovery) => void;
}

// GP-1: named type alias so SWC/JSX parser doesn't have to reason about
// inline string-union types inside the JSX handler tree.
type GenerationMode = "fast" | "complete";
interface ApprovePayload {
  mode: GenerationMode;
  domain?: string;
  complianceNotes?: string[];
}

export function DiscoveryCard({
  discovery,
  onApprove,
  onAdjust,
  disabled,
  alreadyChosen,
  projectId,
  onDiscoveryUpdated,
}: DiscoveryCardProps) {
  // Two editable fields. Initialise from the dossier; user changes only
  // hit the backend when they press "Approve & generate".
  const [editing, setEditing] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const canAdjustInline = Boolean(projectId && onDiscoveryUpdated);
  const handleAdjust = () => {
    if (canAdjustInline) setAdjustOpen(true);
    else onAdjust();
  };
  const [domainEdit, setDomainEdit] = useState(discovery.domain ?? "");
  const [complianceEdit, setComplianceEdit] = useState<ComplianceRegime[]>(
    (discovery.complianceNotes ?? []).filter((c): c is ComplianceRegime =>
      (COMPLIANCE_OPTIONS as readonly string[]).includes(c),
    ),
  );

  const hasEdits =
    domainEdit !== (discovery.domain ?? "") ||
    JSON.stringify(complianceEdit.sort()) !==
      JSON.stringify((discovery.complianceNotes ?? []).slice().sort());

  // GP-1: mode selection ("fast" vs "complete") is carried in the same
  // [APPROVE_DISCOVERY] JSON payload the edit-whitelist already parses.
  // Backend persists it via services.generation_profile.persist_profile
  // so downstream phases (narrative expansion, decomposition,
  // post-generate depth) all read one authoritative choice.
  const handleApprove = (mode: GenerationMode) => {
    const payload: ApprovePayload = { mode };
    if (hasEdits) {
      if (domainEdit.trim() && domainEdit !== discovery.domain) {
        payload.domain = domainEdit.trim();
      }
      const sortedNow = [...complianceEdit].sort();
      const sortedOriginal = [...(discovery.complianceNotes ?? [])].sort();
      if (JSON.stringify(sortedNow) !== JSON.stringify(sortedOriginal)) {
        payload.complianceNotes = complianceEdit;
      }
    }
    onApprove(`[APPROVE_DISCOVERY] ${JSON.stringify(payload)}`);
  };

  const toggleCompliance = (regime: ComplianceRegime) => {
    setComplianceEdit((prev) =>
      prev.includes(regime)
        ? prev.filter((r) => r !== regime)
        : [...prev, regime],
    );
  };

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div className="border-b bg-gradient-to-r from-violet-50 to-purple-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-violet-500" />
          <h3 className="font-semibold text-sm text-violet-900">
            Domain context
          </h3>
          {typeof discovery.confidence === "number" && (
            <span className="ml-auto text-[10px] text-violet-700/70">
              confidence {Math.round(discovery.confidence * 100)}%
              {discovery.elapsedSeconds != null
                ? ` · ${Math.round(discovery.elapsedSeconds)}s`
                : ""}
              {discovery.searchedWeb ? " · web search" : ""}
            </span>
          )}
        </div>
        {discovery.description && (
          <p className="mt-1 text-xs text-muted-foreground">
            {discovery.description}
          </p>
        )}
      </div>

      <div className="divide-y text-xs">
        {/* Domain — editable */}
        <div className="px-4 py-2.5">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="font-medium text-muted-foreground">Domain</span>
            {!editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                disabled={disabled}
                className="inline-flex items-center gap-1 text-[10px] text-violet-600 hover:text-violet-800"
              >
                <Pencil className="h-2.5 w-2.5" />
                Edit
              </button>
            )}
          </div>
          {editing ? (
            <input
              type="text"
              value={domainEdit}
              onChange={(e) => setDomainEdit(e.target.value)}
              disabled={disabled}
              className="w-full rounded border border-input bg-background px-2 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-violet-400"
              placeholder="e.g. Hospitality"
            />
          ) : (
            <div className="flex items-center gap-2">
              <span className="font-medium text-foreground">
                {domainEdit || "(unspecified)"}
              </span>
              {discovery.domainAliases && discovery.domainAliases.length > 0 && (
                <span className="text-[10px] text-muted-foreground">
                  aka {discovery.domainAliases.slice(0, 3).join(", ")}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Compliance — editable */}
        <div className="px-4 py-2.5">
          <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
            <ShieldCheck className="h-3 w-3" />
            Compliance regimes
          </div>
          {editing ? (
            <div className="flex flex-wrap gap-1.5">
              {COMPLIANCE_OPTIONS.map((regime) => {
                const active = complianceEdit.includes(regime);
                return (
                  <button
                    key={regime}
                    type="button"
                    onClick={() => toggleCompliance(regime)}
                    disabled={disabled}
                    className={`rounded px-2 py-0.5 text-[11px] uppercase tracking-wide transition-colors ${
                      active
                        ? "bg-violet-600 text-white"
                        : "bg-muted text-muted-foreground hover:bg-muted-foreground/10"
                    }`}
                  >
                    {regime}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {complianceEdit.length === 0 || (complianceEdit.length === 1 && complianceEdit[0] === "none") ? (
                <span className="text-muted-foreground">None applicable</span>
              ) : (
                complianceEdit
                  .filter((r) => r !== "none")
                  .map((regime) => (
                    <span
                      key={regime}
                      className="rounded bg-amber-50 px-2 py-0.5 text-[11px] uppercase tracking-wide text-amber-800"
                    >
                      {regime}
                    </span>
                  ))
              )}
            </div>
          )}
        </div>

        {/* Visual language — read-only */}
        {discovery.visualLanguage && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Palette className="h-3 w-3" />
              Visual language
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
              {discovery.visualLanguage.paletteCharacter && (
                <span>
                  palette{" "}
                  <span className="text-foreground">
                    {discovery.visualLanguage.paletteCharacter}
                  </span>
                </span>
              )}
              {discovery.visualLanguage.typographyTone && (
                <span>
                  typography{" "}
                  <span className="text-foreground">
                    {discovery.visualLanguage.typographyTone}
                  </span>
                </span>
              )}
              {discovery.visualLanguage.densityPreference && (
                <span>
                  density{" "}
                  <span className="text-foreground">
                    {discovery.visualLanguage.densityPreference}
                  </span>
                </span>
              )}
            </div>
          </div>
        )}

        {/* Design patterns — read-only */}
        {discovery.designPatterns && discovery.designPatterns.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <Layers className="h-3 w-3" />
              Patterns ({discovery.designPatterns.length})
            </div>
            <div className="space-y-1.5">
              {discovery.designPatterns.slice(0, 5).map((p) => (
                <div key={p.name} className="text-muted-foreground">
                  <span className="font-medium text-foreground">{p.name}</span>
                  {p.description && (
                    <>
                      <span className="mx-1">—</span>
                      <span>{p.description}</span>
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Common pitfalls — read-only */}
        {discovery.commonPitfalls && discovery.commonPitfalls.length > 0 && (
          <div className="px-4 py-2.5">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-muted-foreground">
              <AlertTriangle className="h-3 w-3" />
              Common pitfalls ({discovery.commonPitfalls.length})
            </div>
            <ul className="ml-3 list-disc space-y-0.5 text-muted-foreground">
              {discovery.commonPitfalls.slice(0, 5).map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Uncertain areas — read-only, only when present */}
        {discovery.uncertainAreas && discovery.uncertainAreas.length > 0 && (
          <div className="px-4 py-2.5 bg-amber-50/40">
            <div className="mb-1.5 flex items-center gap-1.5 font-medium text-amber-800">
              <HelpCircle className="h-3 w-3" />
              The agent flagged these as uncertain
            </div>
            <ul className="ml-3 list-disc space-y-0.5 text-amber-700/80">
              {discovery.uncertainAreas.slice(0, 3).map((u, i) => (
                <li key={i}>{u}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Actions — GP-1: pick generation profile.
          B-007: if the user has already picked a profile for this project
          (or this isn't the latest discovery message), collapse to a
          compact "Chosen: Fast" chip so the picker doesn't linger in the
          chat after the choice is made. */}
      {alreadyChosen ? (
        <div className="border-t px-4 py-2.5">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            <span>
              Chosen:{" "}
              <span className="font-medium text-foreground">
                {alreadyChosen === "fast" ? "Build Fast" : "Build Complete"}
              </span>
            </span>
          </div>
        </div>
      ) : (
      <div className="border-t px-4 py-3">
        <div className="mb-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Choose how to build
          {hasEdits && <span> (with your edits)</span>}
        </div>

        {/* Bug B-020.5: users didn't know what they'd lose picking Fast vs
            Complete — copy was tooltip-only. Explicit side-by-side card
            answers the question up front. */}
        <div className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="rounded-md border border-amber-200 bg-amber-50/60 p-2.5 text-[11px] leading-relaxed text-amber-900">
            <div className="mb-1 flex items-center gap-1.5 font-semibold">
              <Zap className="h-3 w-3" /> Fast
              <span className="ml-auto font-normal text-amber-700/80">~12 min *</span>
            </div>
            <ul className="ml-3 list-disc space-y-0.5">
              <li>Working app end-to-end</li>
              <li>Core CRUD, forms, workflows</li>
              <li>Standard design + defaults</li>
              <li className="text-amber-800/70">Skips deep domain research</li>
              <li className="text-amber-800/70">Fewer nuanced dashboards / views</li>
            </ul>
            <div className="mt-1 text-amber-800/70">Best for: prototypes, quick iteration.</div>
          </div>
          <div className="rounded-md border border-violet-200 bg-violet-50/60 p-2.5 text-[11px] leading-relaxed text-violet-900">
            <div className="mb-1 flex items-center gap-1.5 font-semibold">
              <Swords className="h-3 w-3" /> Complete
              <span className="ml-auto font-normal text-violet-700/80">~30 min *</span>
            </div>
            <ul className="ml-3 list-disc space-y-0.5">
              <li>Everything Fast delivers, plus:</li>
              <li>Industry-specific research + terminology</li>
              <li>Richer dashboards, KPIs, insights</li>
              <li>More thorough page + form coverage</li>
              <li>Compliance-aware defaults (HIPAA/PCI/etc.)</li>
            </ul>
            <div className="mt-1 text-violet-800/70">Best for: real first build you plan to ship.</div>
          </div>
        </div>
        <div className="mb-2 text-[10px] italic text-muted-foreground">
          * Estimated time. Actual duration varies with app complexity and can
          run longer during peak load.
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => handleApprove("fast")}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 shadow-sm hover:bg-amber-100 disabled:opacity-50"
          >
            <Zap className="h-3 w-3" />
            Build Fast
          </button>
          <button
            onClick={() => handleApprove("complete")}
            disabled={disabled}
            className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-violet-500 to-purple-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:from-violet-600 hover:to-purple-700 disabled:opacity-50"
          >
            <Swords className="h-3 w-3" />
            Build Complete
          </button>
          <button
            onClick={handleAdjust}
            disabled={disabled || adjustOpen}
            className="ml-1 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <MessageSquare className="h-3 w-3" />
            Adjust strategy
          </button>
          {editing && (
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={disabled}
              className="ml-auto text-[11px] text-violet-600 hover:text-violet-800"
            >
              Done editing
            </button>
          )}
        </div>
      </div>
      )}
      {adjustOpen && projectId && onDiscoveryUpdated && (
        <AdjustPanel
          projectId={projectId}
          target="discovery"
          onPlanUpdated={(next) => {
            const updated = next as Discovery;
            onDiscoveryUpdated(updated);
            if (updated.domain !== undefined) {
              setDomainEdit(updated.domain ?? "");
            }
            if (Array.isArray(updated.complianceNotes)) {
              setComplianceEdit(
                (updated.complianceNotes ?? []).filter(
                  (c): c is ComplianceRegime =>
                    (COMPLIANCE_OPTIONS as readonly string[]).includes(c),
                ),
              );
            }
          }}
          onClose={() => setAdjustOpen(false)}
          disabled={disabled}
        />
      )}
    </div>
  );
}
