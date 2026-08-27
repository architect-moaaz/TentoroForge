import { z } from "zod";
import { StyleSlot } from "../style-slot";

// ── Wave 5 — heavy composite components ──────────────────────────────────

export const CalendarNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Calendar"),
  props: z.object({
    name:  z.string().min(1),
    value: z.string().optional(),
    bind:  z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CalendarNodeT = z.infer<typeof CalendarNode>;

export const KanbanNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Kanban"),
  props: z.object({
    columns: z.array(z.object({
      id:    z.string(),
      title: z.string(),
      cards: z.array(z.object({
        id:          z.string(),
        title:       z.string(),
        description: z.string().optional(),
      }).strict()).default([]),
    }).strict()).min(1),
    bind: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type KanbanNodeT = z.infer<typeof KanbanNode>;

export const ResourceTimelineNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("ResourceTimeline"),
  // Data-driven: resources/items are bindings, the rest are field-name strings.
  // Passthrough (not strict on props) so the many optional field props validate
  // without enumerating every one at the schema layer.
  props: z.object({
    resources: z.unknown().optional(),
    items: z.unknown().optional(),
    resourceIdField: z.string().optional(),
    resourceLabelField: z.string().optional(),
    resourceSubField: z.string().optional(),
    resourceGroupField: z.string().optional(),
    itemResourceField: z.string().optional(),
    startField: z.string().optional(),
    endField: z.string().optional(),
    titleField: z.string().optional(),
    subtitleField: z.string().optional(),
    statusField: z.string().optional(),
    itemHref: z.string().optional(),
    rangeStart: z.string().optional(),
    days: z.number().int().positive().optional(),
    emptyText: z.string().optional(),
    bind: z.string().optional(),
  }).passthrough(),
  style: StyleSlot.optional(),
}).strict();
export type ResourceTimelineNodeT = z.infer<typeof ResourceTimelineNode>;

export const RichTextEditorNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("RichTextEditor"),
  props: z.object({
    name:        z.string().min(1),
    label:       z.string().optional(),
    value:       z.string().optional(),
    placeholder: z.string().optional(),
    bind:        z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type RichTextEditorNodeT = z.infer<typeof RichTextEditorNode>;

export const CarouselNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Carousel"),
  props: z.object({
    items: z.array(z.object({
      image:   z.string().optional(),
      title:   z.string().optional(),
      caption: z.string().optional(),
    }).strict()).min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CarouselNodeT = z.infer<typeof CarouselNode>;

export const LightboxNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Lightbox"),
  props: z.object({
    images: z.array(z.object({
      src: z.string(),
      alt: z.string().optional(),
    }).strict()).min(1),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type LightboxNodeT = z.infer<typeof LightboxNode>;

export const CodeBlockNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("CodeBlock"),
  props: z.object({
    code:     z.string().min(1),
    language: z.string().optional(),
    showCopy: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type CodeBlockNodeT = z.infer<typeof CodeBlockNode>;

export const QRCodeNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("QRCode"),
  props: z.object({
    value: z.string().min(1),
    size:  z.number().int().positive().optional(),
    label: z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type QRCodeNodeT = z.infer<typeof QRCodeNode>;
