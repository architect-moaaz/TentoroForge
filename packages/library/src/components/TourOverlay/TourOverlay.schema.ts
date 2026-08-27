import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * TourOverlay — Spec E Wave 3 onboarding tour.
 *
 * Renders nothing until triggered. Each step points at a target CSS
 * selector and floats a titled popover. Dismissal (Skip or reaching
 * the last step) persists to localStorage under `storageKey` so the
 * tour never re-triggers for the same user on the same device.
 */
const TourStep = z
  .object({
    target: z.string().min(1),           // CSS selector for the highlighted element
    title:  z.string().min(1),
    body:   z.string().optional(),
    placement: z.enum(["top", "bottom", "left", "right", "auto"]).default("auto"),
  })
  .strict();

export const TourOverlayProps = z
  .object({
    steps: z.array(TourStep).min(1),
    /** localStorage key used to record dismissal. */
    storageKey: z.string().default("forge-tour-default"),
    /** When true, the tour auto-opens on mount (default: true). */
    autoStart: z.boolean().default(true),
    /** Optional custom next / done labels. */
    nextLabel: z.string().optional(),
    doneLabel: z.string().optional(),
    skipLabel: z.string().optional(),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type TourOverlayPropsType = z.infer<typeof TourOverlayProps>;
export type TourStepType = z.infer<typeof TourStep>;
