import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * Pagination — supports both the minimal `Page X of Y` rendering (back-compat)
 * and a full controls bar with prev/next chevrons + page-size selector + item
 * count, matching the "Lines per page  1-10 of 14" pattern common in admin
 * dashboards.
 *
 * Back-compat: `currentPage` + `totalPages` alone keeps the legacy text-only
 * rendering. Supplying `totalItems` switches to the range-of-total format.
 * Supplying `pageSize` AND `pageSizeOptions` adds the per-page <select>.
 * Supplying `onPageChange` enables clickable chevrons.
 */
export const PaginationProps = z
  .object({
    currentPage: z.number().int().min(1),
    totalPages: z.number().int().min(1),
    /** Total item count — when supplied, renders "1-10 of 100" instead of
     *  "page X of Y". */
    totalItems: z.number().int().min(0).optional(),
    /** Items shown per page. Required to compute the "1-10" half of the
     *  range string when `totalItems` is supplied. */
    pageSize: z.number().int().min(1).optional(),
    /** Available page sizes for the per-page selector. When provided AND
     *  `onPageSizeChange` is wired, renders a <select> next to the count. */
    pageSizeOptions: z.array(z.number().int().min(1)).optional(),
    /** Label for the page-size selector. Defaults to "Lines per page". */
    pageSizeLabel: z.string().optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type PaginationPropsType = z.infer<typeof PaginationProps>;
