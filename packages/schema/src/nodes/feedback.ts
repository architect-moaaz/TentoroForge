import { z } from "zod";
import { StyleSlot } from "../style-slot";

export const ProgressNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Progress"),
  props: z.object({
    label:     z.string().optional(),
    value:     z.number(),
    max:       z.number().optional(),
    variant:   z.enum(["bar", "circular"]).optional(),
    showValue: z.boolean().optional(),
    bind:      z.string().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type ProgressNodeT = z.infer<typeof ProgressNode>;

export const SpinnerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Spinner"),
  props: z.object({
    label: z.string().optional(),
    size:  z.enum(["sm", "md", "lg"]).optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type SpinnerNodeT = z.infer<typeof SpinnerNode>;

export const BannerNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("Banner"),
  props: z.object({
    variant:     z.enum(["info", "success", "warning", "error"]).optional(),
    title:       z.string().optional(),
    message:     z.string().min(1),
    dismissible: z.boolean().optional(),
  }).strict(),
  style: StyleSlot.optional(),
}).strict();
export type BannerNodeT = z.infer<typeof BannerNode>;
