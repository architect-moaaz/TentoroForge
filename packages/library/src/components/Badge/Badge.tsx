import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity, useRadiusScale } from "../../theme/tokens-context";
import { formatValue } from "../../utils/formatValue";

/**
 * Badge — small status pill. Variants pick semantic background + foreground
 * tones from the project's globals.css HSL design tokens. Maps to shadcn's
 * tone scale (primary / success / destructive / warning / muted).
 *
 * Wave 2: radius.scale drives corner radius; density drives padding + text size.
 * Default radius.scale = "soft" → rounded-full (today's default, unchanged).
 * Default density = "comfortable" → px-2.5 py-0.5 text-xs (today's default).
 */
type Variant = "neutral" | "primary" | "accent" | "success" | "danger" | "warning";

// Variant classes use light-tinted backgrounds + darker text so all four
// tonal variants clear WCAG AA contrast (4.5:1 for small text) on the
// project's default light theme. The previous `bg-destructive/10
// text-destructive` pair sat at ~3.6:1 — fine at large sizes but a
// real fail for Badge which is rendered at 12px semibold (not "large
// text" by WCAG definition). Switching to a tinted error surface
// matches the success/warning treatment and lifts contrast above the
// AA threshold.
const VARIANT_CLASS: Record<Variant, string> = {
  // Neutral pills previously used `text-muted-foreground` on `bg-muted`, which
  // axe-core flagged at 4.34:1 contrast (below the 4.5:1 AA threshold for
  // small text). Switching to `text-foreground` clears AA while keeping the
  // muted chip surface — visually subtle, accessibility-correct.
  neutral: "bg-muted text-foreground border-border",
  // Brand primary: uses project's primary color scale via CSS vars.
  // Falls back to blue-100/blue-800 if --color-primary-* are not set.
  primary: "bg-[var(--color-primary-100,theme(colors.blue.100))] text-[var(--color-primary-800,theme(colors.blue.800))] border-[var(--color-primary-200,theme(colors.blue.200))]",
  // Accent — the second brand hue (terracotta on Morning Mist, sage on
  // Studio Blush). Composers opt in explicitly when a chip should read
  // as a secondary CTA / non-primary emphasis, so multi-signal pages
  // don't collapse to a single tone. Uses the shadcn `--accent` /
  // `--accent-foreground` CSS vars set by
  // ``services/design_compiler.derive_structural_tokens`` — those are
  // always present (synthesized via a +150° hue rotation from primary
  // when the palette omits an accent), so no fallback branch is needed.
  accent: "bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))] border-[hsl(var(--accent))]",
  // Status colors: semantic meaning must not shift with brand. Use fixed
  // success/warning/error palette vars (falling back to Tailwind defaults).
  success: "bg-[var(--color-success-100,theme(colors.emerald.100))] text-[var(--color-success-800,theme(colors.emerald.800))] border-[var(--color-success-200,theme(colors.emerald.200))]",
  danger:  "bg-[var(--color-error-100,theme(colors.red.100))] text-[var(--color-error-800,theme(colors.red.800))] border-[var(--color-error-200,theme(colors.red.200))]",
  warning: "bg-[var(--color-warning-100,theme(colors.amber.100))] text-[var(--color-warning-800,theme(colors.amber.800))] border-[var(--color-warning-200,theme(colors.amber.200))]",
};

// radius.scale → corner radius class.
// "soft" maps to rounded-full to preserve today's pill appearance (Badge has
// always been a full-radius pill). Sharp = small radius, round = full circle.
const RADIUS_CLASS: Record<"sharp" | "soft" | "round", string> = {
  sharp: "rounded-sm",
  soft:  "rounded-full",  // today's default — preserves existing pill appearance
  round: "rounded-full",
};

// density → padding + text size.
// "comfortable" matches today's px-2.5 py-0.5 text-xs exactly.
const DENSITY_PADDING: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "px-1.5 py-0.5 text-[10px]",
  comfortable: "px-2.5 py-0.5 text-xs",   // today's default
  spacious:    "px-3 py-1 text-xs",
};

const BASE_STATIC =
  "inline-flex items-center gap-1 border font-medium leading-tight whitespace-nowrap";

type Props = {
  content: string;
  variant?: Variant;
  style?: StyleSlotT;
};

// Semantic auto-variant inference: when the caller doesn't explicitly pick a
// variant (or passes the lazy default "neutral"), look at the content string
// and pick a tone that matches its meaning. Status pills and priority chips
// emitted by the generation pipeline rarely carry a variant prop — without
// this inference every "high" / "low" / "completed" / "critical" pill
// renders in the same muted grey, which the user perceives as a styling bug.
// Authors who DO specify a variant override this — explicit always wins.
const SEMANTIC_VARIANT_HINTS: Record<string, Variant> = {
  // success-toned (green): things that completed cleanly or are healthy
  completed: "success", complete: "success", done: "success",
  success: "success", succeeded: "success", approved: "success",
  active: "success", live: "success", published: "success",
  resolved: "success", low: "success", ok: "success", ready: "success",
  // danger-toned (red): blocking, urgent, or failure states
  critical: "danger", blocker: "danger", urgent: "danger", error: "danger",
  failed: "danger", failure: "danger", rejected: "danger", blocked: "danger",
  overdue: "danger", cancelled: "danger", canceled: "danger",
  // warning-toned (amber): elevated attention, in-flight, awaiting
  high: "warning", warning: "warning", pending: "warning",
  review: "warning", "in_review": "warning", "in-review": "warning",
  "on_hold": "warning", "on-hold": "warning", waiting: "warning",
  draft: "warning",
  // primary-toned (brand): in progress / actively worked
  "in_progress": "primary", "in-progress": "primary", working: "primary",
  medium: "primary", new: "primary", todo: "primary",
};

function _inferVariant(content: unknown): Variant {
  // `content` is typed string, but bound rows routinely pass a number/null (a
  // numeric status, a count) — coerce so `.toLowerCase()` never throws at render.
  const key = String(content ?? "").toLowerCase().trim();
  return SEMANTIC_VARIANT_HINTS[key] ?? "neutral";
}

// Mirror of the Text-component humaniser — status pills routinely arrive as
// snake/kebab keys ("in_progress", "on_hold") which look like raw enum values
// instead of user-facing labels. Capitalise the first word and replace
// separators with spaces. Mixed prose / single words pass through untouched.
const _SNAKE_RE = /^[a-z][a-z0-9]+(?:[_-][a-z0-9]+)+$/;
function _humanizeContent(content: unknown): string {
  // Non-strings (a Date object, a number, null) crash JSX if rendered directly
  // ("Objects are not valid as a React child") — coerce to a display string first.
  if (typeof content !== "string") return formatValue(content);
  if (!content) return content;
  const s = content.trim();
  if (!_SNAKE_RE.test(s)) return content;
  const parts = s.split(/[_-]/);
  return parts
    .map((p, i) => (i === 0 ? p.charAt(0).toUpperCase() + p.slice(1) : p))
    .join(" ");
}

export function Badge({ content, variant, style }: Props) {
  const radiusScale = useRadiusScale();
  const density = useDensity();
  // Resolve variant — EXPLICIT ALWAYS WINS, which is what the comment on
  // SEMANTIC_VARIANT_HINTS has always promised and what the code did not do.
  // Inference was checked first, so setting VARIANT to `danger` on a badge
  // reading "Active" produced a green pill: the control did nothing and said
  // nothing, and a designer could not override their own component.
  //   1. An explicit non-neutral caller variant wins outright.
  //   2. Otherwise infer from the content — LLM-generated schemas rarely carry
  //      a variant, and without inference every "high"/"low"/"completed" pill
  //      renders in the same muted grey.
  //   3. Inference returns "neutral" when the content isn't recognised, so
  //      unstyled custom labels still render as muted pills.
  const resolvedVariant: Variant =
    variant && variant !== "neutral" ? variant : _inferVariant(content);

  const className = [
    BASE_STATIC,
    RADIUS_CLASS[radiusScale],
    DENSITY_PADDING[density],
    VARIANT_CLASS[resolvedVariant] ?? VARIANT_CLASS.neutral,
  ].join(" ");

  // Tier M: semantic role + screen-reader-friendly label.
  // Status pills like "Pending" / "Approved" are meaningful state, not
  // decoration — `role="status"` lets assistive tech announce them as
  // such. Use `aria-label` so the original token ("in_progress") is
  // announced even though we render the humanised form ("In progress").
  const humanContent = _humanizeContent(content);
  return (
    <span
      className={className}
      role="status"
      aria-label={`Status: ${humanContent}`}
      style={resolveStyle(style)}
      {...useMotion(style?.motion)}
    >
      {humanContent}
    </span>
  );
}
