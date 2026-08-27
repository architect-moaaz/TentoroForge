"use client";

/**
 * NextStepsCard — Smith's first message after generation completes.
 *
 * The user is dropped into a fresh generated app with no obvious entry
 * point. This card renders a small ordered set of chips derived from
 * the actual plan.json (backend service ``next_steps.derive_next_steps``)
 * so every suggestion names a real entity / route.
 *
 * Each chip is one of three kinds:
 *   - "send"     → posts the message to chat as if the user typed it
 *   - "navigate" → deep-links the preview iframe to a route
 *   - "tool"     → posts a message Smith's routing prompt maps to a
 *                  tool call (publish, generate_mobile_app)
 *
 * If the user takes an action or dismisses the card, it collapses; the
 * message stays in history so scroll-back doesn't lose the suggestion.
 */

import { useState } from "react";
import {
  Sparkles,
  Plus,
  LayoutDashboard,
  ShoppingCart,
  Palette,
  Rocket,
  Smartphone,
  ShieldCheck,
  ArrowRight,
  X,
  Globe,
  FileText,
  Waypoints,
  type LucideIcon,
} from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useVisualEditorStore } from "@/stores/visual-editor";

export type NextStepKind = "send" | "navigate" | "tool";

export interface NextStep {
  label: string;
  kind: NextStepKind;
  message?: string;
  url?: string;
  icon?: string;
  rationale?: string;
}

interface NextStepsCardProps {
  steps: NextStep[];
  /** Fired for "send" and "tool" chips — routes into the existing
   *  onSend chat pipeline. */
  onSend?: (message: string) => void;
  /** Fired for "navigate" chips — the parent scrolls / points the
   *  preview iframe at the route. */
  onNavigate?: (url: string) => void;
  disabled?: boolean;
}

// Small icon lookup — keeps the backend from having to know about
// lucide-react. If the backend names an icon we don't render, we fall
// back to a neutral arrow.
const ICONS: Record<string, LucideIcon> = {
  plus: Plus,
  "layout-dashboard": LayoutDashboard,
  "shopping-cart": ShoppingCart,
  palette: Palette,
  rocket: Rocket,
  smartphone: Smartphone,
  "shield-check": ShieldCheck,
};

function iconFor(name?: string): LucideIcon {
  if (name && ICONS[name]) return ICONS[name];
  return ArrowRight;
}

export function NextStepsCard({
  steps,
  onSend,
  onNavigate,
  disabled,
}: NextStepsCardProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed || steps.length === 0) return null;

  const handleClick = (step: NextStep) => {
    if (disabled) return;
    if (step.kind === "navigate" && step.url) {
      if (onNavigate) {
        onNavigate(step.url);
      } else if (onSend) {
        // Fallback until preview-iframe control is wired: ask Smith
        // conversationally. His nav-intent detector will surface the
        // matching page.
        onSend(`Take me to ${step.url}`);
      }
    } else if (step.message) {
      onSend?.(step.message);
    }
    // Collapse the card once the user acts — but keep it in history so
    // scrolling back still shows what was offered.
    setDismissed(true);
  };

  return (
    <div className="my-2 rounded-lg border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between border-b bg-gradient-to-r from-emerald-50 to-teal-50 px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-500" />
          <h3 className="text-sm font-semibold text-emerald-900">
            What would you like to try?
          </h3>
        </div>
        <button
          onClick={() => setDismissed(true)}
          className="rounded p-1 text-emerald-700/70 hover:bg-emerald-100 hover:text-emerald-900"
          aria-label="Dismiss suggestions"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Chips */}
      <div className="grid grid-cols-1 gap-2 px-4 py-3 sm:grid-cols-2">
        {steps.map((step) => {
          const Icon = iconFor(step.icon);
          // JV-27/#6 — the Verify & Fix chip opens a small scope picker
          // popover instead of firing immediately. All other chips keep
          // their existing single-click behaviour.
          if (isVerifyAndFix(step)) {
            return (
              <VerifyScopePopover
                key={`${step.kind}:${step.label}`}
                step={step}
                Icon={Icon}
                disabled={disabled}
                onSend={onSend}
                onDone={() => setDismissed(true)}
              />
            );
          }
          return (
            <button
              key={`${step.kind}:${step.label}`}
              type="button"
              onClick={() => handleClick(step)}
              disabled={disabled}
              title={step.rationale ?? undefined}
              className="group inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-white px-3 py-2 text-left text-xs shadow-sm transition-colors hover:border-emerald-400 hover:bg-emerald-50 disabled:opacity-50"
            >
              <Icon className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
              <div className="flex flex-1 flex-col overflow-hidden">
                <span className="font-medium text-foreground">
                  {step.label}
                </span>
                {step.rationale && (
                  <span className="truncate text-[10px] text-muted-foreground">
                    {step.rationale}
                  </span>
                )}
              </div>
              <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          );
        })}
      </div>

      {/* Escape hatch */}
      <div className="border-t bg-muted/30 px-4 py-2 text-[10px] text-muted-foreground">
        Or just tell me in the chat what you'd like to change.
      </div>
    </div>
  );
}


/** JV-27/#6 — Match the platform's Verify & Fix chip so the popover only
 *  wraps that one entry. The backend labels it "Verify & Fix"; guard
 *  loosely on both label AND the shield-check icon in case the copy
 *  moves. */
function isVerifyAndFix(step: NextStep): boolean {
  return step.icon === "shield-check" || /^verify\s*&/i.test(step.label);
}

type ScopeKey = "all" | "page" | "critical";

interface VerifyScopePopoverProps {
  step: NextStep;
  Icon: LucideIcon;
  disabled?: boolean;
  onSend?: (message: string) => void;
  onDone: () => void;
}

function VerifyScopePopover({
  step, Icon, disabled, onSend, onDone,
}: VerifyScopePopoverProps) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState<ScopeKey>("all");
  const currentRoute = useVisualEditorStore((s) => s.currentRoute);

  const options: {
    key: ScopeKey; label: string; hint: string; Icon: LucideIcon; disabled?: boolean;
  }[] = [
    { key: "all",      label: "Entire app",     hint: "~15–25 min", Icon: Globe },
    { key: "page",     label: currentRoute ? `Current page (${currentRoute})` : "Current page",
      hint: "~1 min",         Icon: FileText,
      disabled: !currentRoute },
    { key: "critical", label: "Critical flows only", hint: "~5 min", Icon: Waypoints },
  ];

  const run = () => {
    const message = messageForScope(scope, currentRoute, step.message);
    onSend?.(message);
    onDone();
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          title={step.rationale ?? undefined}
          className="group inline-flex items-center gap-2 rounded-md border border-emerald-200 bg-white px-3 py-2 text-left text-xs shadow-sm transition-colors hover:border-emerald-400 hover:bg-emerald-50 disabled:opacity-50"
        >
          <Icon className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
          <div className="flex flex-1 flex-col overflow-hidden">
            <span className="font-medium text-foreground">{step.label}</span>
            {step.rationale && (
              <span className="truncate text-[10px] text-muted-foreground">
                {step.rationale}
              </span>
            )}
          </div>
          <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2" align="start">
        <div className="px-2 pt-1 pb-2 text-[11px] font-semibold text-foreground">
          What should I verify?
        </div>
        <div className="flex flex-col gap-1">
          {options.map((opt) => {
            const OI = opt.Icon;
            const active = scope === opt.key;
            return (
              <button
                key={opt.key}
                type="button"
                disabled={opt.disabled}
                onClick={() => setScope(opt.key)}
                className={`flex items-start gap-2 rounded-md border px-2.5 py-2 text-left text-xs transition-colors disabled:opacity-40 ${
                  active
                    ? "border-emerald-400 bg-emerald-50"
                    : "border-transparent hover:border-emerald-200 hover:bg-muted/40"
                }`}
              >
                <OI className="h-3.5 w-3.5 mt-0.5 shrink-0 text-emerald-600" />
                <div className="flex-1">
                  <div className="font-medium text-foreground">{opt.label}</div>
                  <div className="text-[10px] text-muted-foreground">
                    Estimated time: {opt.hint}
                  </div>
                </div>
                <span
                  aria-hidden
                  className={`h-3 w-3 mt-1 rounded-full border ${
                    active
                      ? "border-emerald-500 bg-emerald-500"
                      : "border-muted-foreground/40"
                  }`}
                />
              </button>
            );
          })}
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={run}
            className="rounded bg-emerald-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-emerald-700"
          >
            Run
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}

function messageForScope(
  scope: ScopeKey,
  currentRoute: string | null,
  fallback?: string,
): string {
  if (scope === "page" && currentRoute) {
    return `Verify only the current page: ${currentRoute}`;
  }
  if (scope === "critical") {
    return "Verify only the critical journeys.";
  }
  return fallback || "Verify the app and fix anything that's broken.";
}
