import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const AvatarNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Avatar"),
  props: z.object({
    src:    z.string().min(1).optional(),
    // photoUrl: Unsplash/CDN image URL for the avatar. Use z.string().optional()
    // rather than z.string().url() so that relative paths (/static/img/x.jpg)
    // work too — important for offline dev and local asset serving.
    photoUrl: z.string().min(1).optional(),
    // Default to "User" so that `{type:"Avatar",props:{}}` — the minimal form
    // the LLM sometimes emits — still renders an initials avatar rather than
    // the "⚠ invalid props" placeholder. The Avatar component derives initials
    // from whatever string is here, so "User" → "U" circle is a safe fallback.
    name:   z.string().default("User"),
    // Default to "md" for the same reason — LLM often omits size.
    size:   z.enum(["xs", "sm", "md", "lg", "xl"]).default("md"),
    // Omit `status` to render no status indicator. No "none" sentinel needed
    // here — unlike Motion's redundant `"none"` enum value, this slot uses
    // undefined as the "absent" signal. Accept string here too since LLM-
    // generated schemas commonly bind `status` to a Mustache template
    // (`{{item.status}}`) that resolves at render time.
    status: z.union([z.enum(["online", "offline", "away", "busy"]), z.string().min(1)]).optional(),
    className: z.string().optional(),
    style: z.record(z.unknown()).optional(),
  }),  // removed .strict() — unknown keys from LLM pass through to the renderer
  style: StyleSlot.optional(),
});  // removed outer .strict() — forward-compat with new top-level fields
export type AvatarNodeT = z.infer<typeof AvatarNode>;

export const KeyValueListNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("KeyValueList"),
  props: z.object({
    items: z.array(z.object({
      label: z.string().min(1),
      // value can be empty — the renderer handles empty-state UI
      // (greyed dash, "Not set", etc.). label stays .min(1).
      value: z.string(),
      copyable: z.boolean().optional(),
    }).strict()).min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type KeyValueListNodeT = z.infer<typeof KeyValueListNode>;

export const SkeletonNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Skeleton"),
  props: z.object({
    variant: z.enum(["rect", "circle", "text"]),
    lines:   z.number().int().positive().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict()
  .refine(
    (n) => n.props.lines === undefined || n.props.variant === "text",
    {
      message: "Skeleton.lines is only valid when variant is 'text'",
      path: ["props", "lines"],
    },
  );
export type SkeletonNodeT = z.infer<typeof SkeletonNode>;

// ── Wave 4 — data display ────────────────────────────────────────────────

export const TagNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Tag"),
  props: z.object({
    label:     z.string().min(1),
    variant:   z.enum(["default", "primary", "accent", "success", "warning", "danger"]).optional(),
    removable: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TagNodeT = z.infer<typeof TagNode>;

export const StatNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Stat"),
  props: z.object({
    label:   z.string().min(1),
    value:   z.string().min(1),
    delta:   z.string().optional(),
    trend:   z.enum(["up", "down", "neutral"]).optional(),
    caption: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type StatNodeT = z.infer<typeof StatNode>;

export const DescriptionListNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("DescriptionList"),
  props: z.object({
    items: z.array(z.object({
      term:        z.string().min(1),
      description: z.string(),
    }).strict()).min(1),
    orientation: z.enum(["vertical", "horizontal"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type DescriptionListNodeT = z.infer<typeof DescriptionListNode>;

export const ListNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("List"),
  props: z.object({
    items: z.array(z.object({
      title:    z.string().min(1),
      subtitle: z.string().optional(),
      icon:     z.string().optional(),
    }).strict()).min(1),
    divided: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ListNodeT = z.infer<typeof ListNode>;

export const SegmentedControlNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("SegmentedControl"),
  props: z.object({
    name:    z.string().min(1),
    label:   z.string().optional(),
    options: z.array(z.object({
      value: z.string(),
      label: z.string(),
    }).strict()).min(1),
    bind: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SegmentedControlNodeT = z.infer<typeof SegmentedControlNode>;

// Recursive nested node shape reused by Tree and Cascader.
const TreeItemSchema: z.ZodType<{ label: string; value?: string; children?: unknown[] }> = z.lazy(() =>
  z.object({
    label:    z.string().min(1),
    value:    z.string().optional(),
    children: z.array(TreeItemSchema).optional(),
  }).strict()
);

export const TreeNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Tree"),
  props: z.object({
    items: z.array(TreeItemSchema).min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TreeNodeT = z.infer<typeof TreeNode>;

export const TransferNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Transfer"),
  props: z.object({
    options: z.array(z.object({
      value: z.string(),
      label: z.string(),
    }).strict()).min(1),
    selected: z.array(z.string()).optional(),
    titles:   z.array(z.string()).optional(),
    bind:     z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type TransferNodeT = z.infer<typeof TransferNode>;

const CascaderItemSchema: z.ZodType<{ value: string; label: string; children?: unknown[] }> = z.lazy(() =>
  z.object({
    value:    z.string(),
    label:    z.string(),
    children: z.array(CascaderItemSchema).optional(),
  }).strict()
);

export const CascaderNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Cascader"),
  props: z.object({
    options:     z.array(CascaderItemSchema).min(1),
    placeholder: z.string().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CascaderNodeT = z.infer<typeof CascaderNode>;
