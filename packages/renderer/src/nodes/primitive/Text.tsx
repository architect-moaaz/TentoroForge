import type { ElementType } from "react";
import { Calendar, User as UserIcon, Clock, Flag, Tag as TagIcon, Mail } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";
import { resolveBinding } from "../../runtime/bindings";

// Metadata-prefix icons: when a Text content starts with a known label
// prefix ("Due:", "Assignee:", etc.) prepend a small Lucide icon so card
// metadata rows read as labelled metadata instead of bare text. The
// prefix is preserved in the visible text — this is purely additive.
const PREFIX_ICONS: Array<{ test: RegExp; icon: LucideIcon }> = [
  { test: /^(due|deadline)\s*:/i,                          icon: Calendar },
  { test: /^(submitted|created|updated|completed)\s*:/i,    icon: Clock },
  { test: /^(assignee|assigned\s*to|owner|created\s*by)\s*:/i, icon: UserIcon },
  { test: /^(priority|severity)\s*:/i,                      icon: Flag },
  { test: /^(category|tags?|type)\s*:/i,                     icon: TagIcon },
  { test: /^email\s*:/i,                                     icon: Mail },
];

function _matchPrefixIcon(text: string): LucideIcon | null {
  if (typeof text !== "string" || !text) return null;
  for (const { test, icon } of PREFIX_ICONS) {
    if (test.test(text)) return icon;
  }
  return null;
}

const ALLOWED_TEXT_TAGS = ["span", "p", "h1", "h2", "h3", "h4", "h5", "h6", "label", "strong", "em"] as const;
type TextTag = (typeof ALLOWED_TEXT_TAGS)[number];

// ISO 8601 timestamp inline pattern: detects `2024-02-15T23:59:59Z` etc.
// anywhere in a string, with or without milliseconds and timezone. Used to
// catch the common "Due: <ISO>" / "Updated: <ISO>" schema patterns where the
// timestamp is embedded in user-facing prose, not the entire content.
const ISO_TS_INLINE = /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b/g;
// Plain date inline: 2024-02-15
const ISO_DATE_INLINE = /\b\d{4}-\d{2}-\d{2}\b/g;
// Snake/kebab status keys: in_progress, on_hold, in-review.
// Only humanise when the WHOLE string is a single token — humanising
// `"foo_bar baz"` mid-prose would be too aggressive.
const SNAKE_FULL = /^[a-z][a-z0-9]+(?:[_-][a-z0-9]+)+$/;

function _formatIsoToken(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // "Feb 15, 2024" — short month, no leading zero, full year. Locale-stable
  // ("en-US") so SSR and CSR produce identical text.
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/**
 * Smart content auto-formatting for Text content. Catches the most common
 * "looks like engineer copy" patterns in LLM-emitted schemas:
 *
 *   "Due: 2024-02-15T23:59:59Z"  →  "Due: Feb 15, 2024"
 *   "2024-02-15"                 →  "Feb 15, 2024"
 *   "in_progress"                →  "In progress"
 *
 * Applied generically at the Text-node level — no schema or LLM change
 * required.
 */
function humanize(content: string): string {
  if (typeof content !== "string" || content.length === 0) return content;
  // Inline ISO replacement — catches both pure dates and embedded dates.
  // Process the longer timestamp pattern first so we don't double-match
  // the YYYY-MM-DD prefix as a plain date.
  let out = content.replace(ISO_TS_INLINE, (m) => _formatIsoToken(m));
  out = out.replace(ISO_DATE_INLINE, (m) => _formatIsoToken(m));
  // Whole-string snake-case key → titlecase. Only applies if no other
  // transformation already changed the string (we don't want to humanise
  // "Updated Feb 15, 2024" because of the trailing token-like fragment).
  if (out === content && SNAKE_FULL.test(content.trim())) {
    const parts = content.trim().split(/[_-]/);
    return parts
      .map((p, i) => (i === 0 ? p.charAt(0).toUpperCase() + p.slice(1) : p))
      .join(" ");
  }
  return out;
}

export function Text({ node, ctx }: { node: any; ctx: any }) {
  const raw = node.props?.as ?? "span";
  const Tag: ElementType = (ALLOWED_TEXT_TAGS as readonly string[]).includes(raw) ? (raw as TextTag) : "span";
  const rawContent =
    node.props?.content !== undefined
      ? node.props.content
      : node.bind
      ? String(resolveBinding(node.bind, ctx) ?? "")
      : "";
  const content = humanize(String(rawContent));
  const slotProps = applyStyleSlot(node.style);
  // Auto-prepend a metadata icon for known label-prefixed content
  // ("Due: …", "Assignee: …", "Priority: …", "Submitted: …"). Adds
  // scannability without requiring schemas to specify icons themselves.
  // Only applies when the Tag is an inline span/p — not headings.
  const PrefixIcon = (Tag === "span" || Tag === "p") ? _matchPrefixIcon(content) : null;
  // Merge schema-level className (carries Figma color/font cues like text-[#6e2574])
  // with any PrefixIcon layout class. Schema className wins for color/font; the
  // icon flex wrapper is added when a prefix icon is present.
  const schemaCn: string | undefined = node.props?.className;
  const combinedCn = [
    PrefixIcon ? "inline-flex items-center gap-1.5" : undefined,
    schemaCn,
  ].filter(Boolean).join(" ") || undefined;

  return (
    <Tag
      data-node-id={node.id}
      style={{ fontFamily: "var(--font-body, inherit)", ...resolveStyle(node.style), ...slotProps.style }}
      data-motion={slotProps["data-motion"]}
      className={combinedCn}
    >
      {PrefixIcon && <PrefixIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" aria-hidden="true" strokeWidth={2} />}
      {content}
    </Tag>
  );
}
