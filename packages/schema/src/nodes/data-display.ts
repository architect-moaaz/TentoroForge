import { z } from "zod";

const DataGridColumn = z.object({
  key: z.string(),
  label: z.string(),
  width: z.union([z.number(), z.string()]).optional(),
  sortable: z.boolean().optional(),
  frozen: z.boolean().optional(),
  align: z.enum(["left", "center", "right"]).optional(),
  // A custom cell renderer: a structured { component, props } slot OR a bare
  // string (a format token / component name the LLM emits).
  render: z
    .union([
      z.string(),
      z.object({
        component: z.string(),
        props: z.record(z.any()).optional(),
      }),
    ])
    .optional(),
});

export const DataGridNode = z.object({
  id: z.string().optional(),
  type: z.literal("DataGrid"),
  props: z.object({
    columns: z.array(DataGridColumn).default([]),
    // Accept a binding string ("{{invoices}}") as well as a literal array — the
    // schema is validated before the Engine resolves data bindings.
    rows: z.union([z.string(), z.array(z.record(z.any()))]).default([]), // open shape — row keys match column.key
    rowKey: z.string().default("id"), // identifies a row's primary key
    virtualise: z.boolean().optional(), // default: auto when rows > 100
    selectable: z.boolean().optional(),
    expandable: z.boolean().optional(),
    rowActions: z
      .array(
        z.object({
          label: z.string(),
          action: z.object({
            type: z.literal("workflow"),
            workflow: z.string(),
          }),
        })
      )
      .optional(),
    className: z.string().optional(),
    style: z.record(z.unknown()).optional(),
  }),
});

export type DataGridColumn = z.infer<typeof DataGridColumn>;
export type DataGridNodeType = z.infer<typeof DataGridNode>;

const TimelineEntry = z.object({
  id: z.string().optional(),
  timestamp: z.string(),     // ISO 8601
  actor: z.string().optional(),
  // Status is documented as the canonical enum but accept any string so that
  // domain-specific values ("submitted", "in-review", …) and Mustache
  // templates ("{{item.status}}") parse through. The Timeline component
  // defaults to a neutral indicator when the value isn't one of the
  // canonical five.
  status: z.union([
    z.enum(["pending", "approved", "rejected", "info", "completed"]),
    z.string().min(1),
  ]).optional(),
  title: z.string(),
  detail: z.string().optional(),
});

export const TimelineNode = z.object({
  id: z.string().optional(),
  type: z.literal("Timeline"),
  props: z.object({
    entries: z.union([z.array(TimelineEntry), z.string().min(1)]).default([]),
    orientation: z.enum(["vertical", "horizontal"]).optional(),  // default vertical
    className: z.string().optional(),
    style: z.record(z.unknown()).optional(),
  }),
});
