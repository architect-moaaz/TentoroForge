import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * SplitView — Spec E Wave 3 master-detail layout.
 *
 * Two columns: a scrollable list on the left, a scrollable detail
 * pane on the right. The currently selected id is mirrored to a URL
 * query param (`syncKey`, default "selected") so deep-links preserve
 * the selection.
 *
 * Composition: SplitView is a container with two named slots. In JSON
 * schemas it is authored with `children: [<listNode>, <detailNode>]`
 * — the first two children take the master/detail positions in order.
 */
export const SplitViewProps = z
  .object({
    /** URL query key used to sync the selected id. Default: "selected". */
    syncKey: z.string().default("selected"),
    /** Fixed pixel width for the master list column. */
    masterWidth: z.number().int().min(160).max(600).default(320),
    /** Empty-state text for when nothing is selected. */
    emptyText: z.string().optional(),
    /** Stacks the two panes below 768px when true (the default). */
    responsive: z.boolean().optional(),
    /**
     * Restores the pre-fix behaviour where the detail pane stays empty until
     * `?<syncKey>=` carries a selection. Off by default: the editor never puts
     * that param on the preview URL, so gating on it made the second child and
     * everything inside it invisible (docs/editor-audit/containment.md #2 —
     * 117 of 133 child pairs failed).
     */
    requireSelection: z.boolean().optional(),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type SplitViewPropsType = z.infer<typeof SplitViewProps>;
