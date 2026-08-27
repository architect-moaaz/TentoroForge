import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

const ColumnDef = z
  .preprocess((v) => {
    // Fold ``header`` → ``label``. LLM page-composer output routinely uses
    // ``header`` (the natural-language word) instead of the ColumnDef's
    // canonical ``label``. Without this alias the whole ColumnDef fails
    // zod validation and the ``<th>`` renders the raw uppercased ``key``
    // (e.g. INSTRUCTORID, STARTTIME) which reads as broken output.
    // Also fold ``dataSource`` → nothing on the column (only meaningful at
    // the Table level) and ``binding`` → nothing (Table cells resolve via
    // ``key`` against the row).
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const o = { ...(v as Record<string, unknown>) };
      if (o.header != null && o.label == null) { o.label = o.header; }
      delete o.header;
      delete o.binding;
      return o;
    }
    return v;
  }, z.object({
    key: z.string().min(1),
    label: z.string().min(1),
    width: z.string().optional(),
    align: z.enum(["left", "center", "right"]).optional(),
    sortable: z.boolean().optional(),
    // Explicit cell renderer; when omitted the Table infers one from the values.
    // `"sensitive"` (Slice-4 encrypt-at-rest) renders the pre-computed masked
    // value the data engine returned; when `sensitiveEndpoint` is set AND the
    // row's `<key>` still equals the mask, an eye-toggle button fetches the
    // unmasked value from that endpoint and swaps it in for THIS row only.
    format: z.enum([
      "text", "badge", "date", "datetime", "currency", "number", "boolean",
      "url", "image", "sensitive",
    ]).optional(),
    /** Slice-4 — GET endpoint the eye toggle calls with `?unmask=<key>&id=<rowId>`.
     *  Example: `"/api/data/accounts"`. Only meaningful when `format:"sensitive"`;
     *  omit it (or set the caller's role outside `sensitiveReaders`) to render
     *  masked-only with no toggle. */
    sensitiveEndpoint: z.string().optional(),
    /** Optional — when the eye toggle should only render for a subset of
     *  users, the caller sets this from the session role. Client-side hint
     *  only; the server still enforces `readers`. */
    canUnmask: z.boolean().optional(),
  })
  .strict());

const RowAction = z
  .object({
    label: z.string(),
    icon: z.string().optional(),
    navigate: z.string().optional(), // deep-link template, e.g. "/guests/{id}"
    workflow: z.string().optional(), // dispatch a workflow with { id }
    variant: z.enum(["default", "danger"]).optional(),
  })
  .strict();

export const TableProps = z
  .object({
    // `columns` is often null in generated schemas — the rows/columns are
    // supplied at runtime via data bindings. Coerce null/undefined → [] so the
    // table renders (empty) in the editor instead of "⚠ invalid props".
    columns: z.preprocess((v) => (v == null ? [] : v), z.array(ColumnDef)),
    caption: z.string().optional(),
    title: z.string().optional(),
    // Row data. In the schema this is a binding string ("{{properties}}") that the
    // renderer interpolates to an array of row records before render — so allow
    // either form. The LLM consistently emits `rows`/`data` on list tables; without
    // this they were stripped by the strict schema → empty "No rows found" table.
    rows: z.unknown().optional(),
    data: z.unknown().optional(),

    // ── Modern data-table features (all optional; sensible defaults) ──────────
    searchable: z.boolean().optional(), // global search box (default on in data mode)
    pageSize: z.number().optional(), // rows per page; small sets render without a pager
    selectable: z.boolean().optional(), // checkbox column + select-all
    rowActions: z.array(RowAction).optional(), // per-row actions (View/Edit/Delete…)
    rowHref: z.string().optional(), // make each row a link, e.g. "/guests/{id}"
    striped: z.boolean().optional(),
    stickyHeader: z.boolean().optional(),
    emptyText: z.string().optional(),
    /** FIX-4 — hint sentence rendered under the empty-state headline. */
    emptyDescription: z.string().optional(),
    /** FIX-4 — CTA rendered under the description. Wire either a
     *  `navigate` destination or a `workflow` dispatch key. */
    emptyAction: z
      .object({
        label: z.string(),
        navigate: z.string().optional(),
        workflow: z.string().optional(),
      })
      .optional(),
    density: z.enum(["compact", "comfortable", "spacious"]).optional(),
    // Loading skeleton — the data-binding hook flips this true while the
    // fetch is in flight; the table renders a matching-dimension skeleton
    // so the layout doesn't shift on data arrival. Root-cause fix for CLS
    // (B-021.5 class): every data-bound library component honours isLoading.
    isLoading: z.boolean().optional(),
    skeletonRows: z.number().optional(),

    // ── Spec E Wave 1 — advanced interactions ────────────────────────────
    /**
     * When true, the Table renders drag handles per row and calls
     * `PATCH /api/data/:entity/reorder` on drop. Requires a `sortOrder`
     * column on the entity — the deterministic post-gen pass
     * `reorder_column_pass` adds it when this flag is set.
     */
    reorderable: z.boolean().optional(),
    /**
     * Selection mode. `"single"` renders a radio column and emits a
     * single-record selection event; `"multi"` renders a checkbox column
     * + a select-all header and, when combined with `bulkActions`,
     * surfaces the BulkActionBar. Omitted / unset = no selection.
     */
    selectionMode: z.enum(["single", "multi"]).optional(),
    /**
     * Bulk workflow actions surfaced by the BulkActionBar when
     * `selectionMode = "multi"` and one or more rows are checked.
     * Each entry is validated against the workflow catalog by the
     * `interaction_authority` post-gen pass.
     */
    bulkActions: z
      .array(
        z.object({
          label: z.string(),
          workflow: z.string(),
          variant: z.enum(["primary", "secondary", "ghost", "destructive"]).optional(),
        })
      )
      .optional(),

    // ── Spec E Wave 3 — inline table editing ─────────────────────────────
    /**
     * When populated, the listed column keys become click-to-edit inputs.
     * Save on blur or Enter; revert on Escape. Row-level dirty tracking
     * surfaces a "Save all" toolbar at the top of the table when any
     * changes are pending. Workflow dispatch on save is deferred to the
     * host — the Table emits a `forge:row:update` event carrying
     * `{entity?, id, patch}` that the runtime translates to a mutation.
     */
    editableColumns: z.array(z.string()).optional(),
    /** Optional workflow to fire when the user clicks "Save all". */
    editSaveWorkflow: z.string().optional(),

    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type TablePropsType = z.infer<typeof TableProps>;
export type ColumnDef = z.infer<typeof ColumnDef>;
export type RowActionDef = z.infer<typeof RowAction>;

// TableSortable is a lighter, client-sort-only table. It shares ColumnDef but
// keeps `onSort` (a callback/action ref the strict TableProps would reject) and
// is passthrough-tolerant of extra generated keys — so it renders instead of a
// "⚠ invalid props" placeholder. Registered in buildDefaultRegistry so the
// renderer knows the type (previously it fell through to "unknown component").
export const TableSortableProps = z
  .object({
    columns: z.preprocess((v) => (v == null ? [] : v), z.array(ColumnDef)),
    caption: z.string().optional(),
    onSort: z.unknown().optional(),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .passthrough();

export type TableSortablePropsType = z.infer<typeof TableSortableProps>;
