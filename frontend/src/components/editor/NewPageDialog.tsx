"use client";
import * as React from "react";
import {
  Plus, Trash2, LayoutGrid, Square, SquareDashed, FormInput,
  PanelLeft, PanelTop, LayoutDashboard, List as ListIcon, Columns2,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  scaffoldPage,
  slugify,
  pageKindMeta,
  PAGE_KINDS,
  type LayoutPreset,
  type PageKind,
  type ScaffoldFieldKind,
  type ScaffoldNavItem,
  type ScaffoldedPage,
} from "@/lib/page-scaffold";

interface FieldRow {
  key: string;
  label: string;
  kind: ScaffoldFieldKind;
  required: boolean;
}

const KIND_OPTIONS: Array<{ value: ScaffoldFieldKind; label: string }> = [
  { value: "text", label: "Text" },
  { value: "email", label: "Email" },
  { value: "number", label: "Number" },
  { value: "textarea", label: "Long text" },
  { value: "select", label: "Dropdown" },
  { value: "checkbox", label: "Checkbox" },
  { value: "date", label: "Date" },
  { value: "switch", label: "Switch" },
];

/** Icon per page kind. Keyed by PageKind so PAGE_KINDS stays the single
 *  source of truth for WHICH kinds exist — this map only decorates them. */
const KIND_ICON: Record<PageKind, React.ComponentType<{ size?: number }>> = {
  blank: SquareDashed,
  form: FormInput,
  sidebar: PanelLeft,
  navbar: PanelTop,
  dashboard: LayoutDashboard,
  list: ListIcon,
  detail: Columns2,
};

let rowSeq = 0;
const mkRow = (label: string, kind: ScaffoldFieldKind, required = false): FieldRow => ({
  key: `f${++rowSeq}`, label, kind, required,
});

/**
 * Turn the project's existing routes into nav entries for the sidebar / top-nav
 * kinds, so a new shell page links to pages that actually exist rather than to
 * three invented placeholders. The dialog only receives routes (PagePicker
 * passes ids + routes), so the label is derived from the last path segment.
 */
function navItemsFromRoutes(routes: string[]): ScaffoldNavItem[] | undefined {
  const seen = new Set<string>();
  const items: ScaffoldNavItem[] = [];
  for (const route of routes) {
    // Parameterised routes ("/items/[id]") are not destinations a nav rail can
    // link to without an id, so they are skipped rather than emitted broken.
    if (!route || route.includes("[") || seen.has(route)) continue;
    seen.add(route);
    const seg = route.split("/").filter(Boolean).pop();
    const label = !seg
      ? "Home"
      : seg.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
    items.push({ label, route });
    if (items.length === 5) break;
  }
  return items.length > 0 ? items : undefined;
}

export interface NewPageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existingPageIds: string[];
  existingRoutes: string[];
  onCreate: (page: ScaffoldedPage) => void;
}

/**
 * "New Page → Kind → options" dialog. Collects a title, the KIND of page to
 * build, and whatever extra options that kind needs, then builds a valid Page
 * via `scaffoldPage` and hands it to `onCreate` (the caller dispatches
 * `addPage` + persists + activates).
 *
 * Which options render is driven entirely by `pageKindMeta(kind)` rather than
 * by a hardcoded form: the field editor used to render unconditionally, which
 * is why every page the dialog could produce had a Name/Email form in it.
 */
export function NewPageDialog({
  open, onOpenChange, existingPageIds, existingRoutes, onCreate,
}: NewPageDialogProps) {
  const [title, setTitle] = React.useState("");
  const [kind, setKind] = React.useState<PageKind>("blank");
  const [layout, setLayout] = React.useState<LayoutPreset>("centered");
  const [heading, setHeading] = React.useState(true);
  const [submitLabel, setSubmitLabel] = React.useState("Submit");
  const [fields, setFields] = React.useState<FieldRow[]>(() => [
    mkRow("Name", "text", true),
    mkRow("Email", "email", true),
  ]);

  // Reset to a clean slate every time the dialog opens.
  React.useEffect(() => {
    if (open) {
      setTitle("");
      setKind("blank");
      setLayout("centered");
      setHeading(true);
      setSubmitLabel("Submit");
      setFields([mkRow("Name", "text", true), mkRow("Email", "email", true)]);
    }
  }, [open]);

  const meta = pageKindMeta(kind);
  const trimmed = title.trim();
  const previewSlug = slugify(trimmed) || "page";
  // A page with no form has no field rows to validate — gating "Create" on them
  // would leave the button dead for every non-form kind.
  const fieldsOk = !meta.hasForm || (fields.length > 0 && fields.every((f) => f.label.trim()));
  const canCreate = trimmed.length > 0 && fieldsOk;

  const updateField = (key: string, patch: Partial<FieldRow>) =>
    setFields((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const removeField = (key: string) =>
    setFields((rows) => rows.filter((r) => r.key !== key));
  const addField = () => setFields((rows) => [...rows, mkRow("", "text", false)]);

  const handleCreate = () => {
    if (!canCreate) return;
    const page = scaffoldPage({
      title: trimmed,
      kind,
      layout,
      heading,
      submitLabel,
      fields: fields.map((f) => ({ label: f.label.trim(), kind: f.kind, required: f.required })),
      navItems: meta.hasNav ? navItemsFromRoutes(existingRoutes) : undefined,
      existingPageIds,
      existingRoutes,
    });
    onCreate(page);
    onOpenChange(false);
  };

  const renderKindButton = (k: typeof PAGE_KINDS[number]) => {
    const Icon = KIND_ICON[k.kind];
    const active = kind === k.kind;
    return (
      <button
        key={k.kind}
        type="button"
        onClick={() => setKind(k.kind)}
        aria-pressed={active}
        title={k.description}
        className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${active ? "border-foreground ring-1 ring-foreground/30" : "hover:bg-muted"}`}
      >
        <Icon size={15} /> {k.label}
      </button>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New page</DialogTitle>
          <DialogDescription>
            Pick what kind of page to create. You can edit everything after.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-1">
          {/* Title */}
          <div className="space-y-1.5">
            <Label htmlFor="np-title">Page title</Label>
            <Input
              id="np-title"
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
              placeholder="e.g. Contact us"
            />
            <p className="text-[11px] text-muted-foreground">
              Route: <code className="font-mono">/{previewSlug}</code>
            </p>
          </div>

          {/* Page kind — layouts you fill in yourself */}
          <div className="space-y-1.5">
            <Label>Layout</Label>
            <div className="grid grid-cols-2 gap-2">
              {PAGE_KINDS.filter((k) => k.group === "layout").map(renderKindButton)}
            </div>
          </div>

          {/* Page kind — pre-populated templates */}
          <div className="space-y-1.5">
            <Label>Start from a template</Label>
            <div className="grid grid-cols-3 gap-2">
              {PAGE_KINDS.filter((k) => k.group === "template").map(renderKindButton)}
            </div>
          </div>

          <p className="text-[11px] text-muted-foreground">{meta.description}</p>

          {/* Form-page width. Only the form kind branches on it. */}
          {meta.hasLayoutPreset && (
            <div className="space-y-1.5">
              <Label>Form width</Label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setLayout("centered")}
                  aria-pressed={layout === "centered"}
                  className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${layout === "centered" ? "border-foreground ring-1 ring-foreground/30" : "hover:bg-muted"}`}
                >
                  <Square size={15} /> Centered card
                </button>
                <button
                  type="button"
                  onClick={() => setLayout("full")}
                  aria-pressed={layout === "full"}
                  className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm ${layout === "full" ? "border-foreground ring-1 ring-foreground/30" : "hover:bg-muted"}`}
                >
                  <LayoutGrid size={15} /> Full width
                </button>
              </div>
            </div>
          )}

          {/* Fields — only for kinds that actually emit a Form. */}
          {meta.hasForm && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label>Form fields</Label>
                <button
                  type="button"
                  onClick={addField}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                >
                  <Plus size={13} /> Add field
                </button>
              </div>
              <div className="space-y-2">
                {fields.map((f) => (
                  <div key={f.key} className="flex items-center gap-2">
                    <Input
                      value={f.label}
                      onChange={(e) => updateField(f.key, { label: e.target.value })}
                      placeholder="Field label"
                      className="h-8 flex-1"
                    />
                    <Select value={f.kind} onValueChange={(v) => updateField(f.key, { kind: v as ScaffoldFieldKind })}>
                      <SelectTrigger className="h-8 w-28 shrink-0">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {KIND_OPTIONS.map((o) => (
                          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <label className="flex items-center gap-1 text-[11px] text-muted-foreground shrink-0" title="Required">
                      <input
                        type="checkbox"
                        checked={f.required}
                        onChange={(e) => updateField(f.key, { required: e.target.checked })}
                      />
                      Req
                    </label>
                    <button
                      type="button"
                      onClick={() => removeField(f.key)}
                      disabled={fields.length === 1}
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-red-500 hover:text-white disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
                      aria-label="Remove field"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Nav preview — the links the sidebar / top-nav kinds will contain. */}
          {meta.hasNav && (
            <div className="space-y-1.5">
              <Label>Navigation links</Label>
              <p className="text-[11px] text-muted-foreground">
                {(navItemsFromRoutes(existingRoutes) ?? [
                  { label: "Overview", route: "/" },
                  { label: "Reports", route: "/" },
                  { label: "Settings", route: "/" },
                ])
                  .map((i) => i.label)
                  .join(" · ")}
              </p>
            </div>
          )}

          {/* Options */}
          <div className="grid grid-cols-2 gap-3">
            {meta.hasForm && (
              <div className="space-y-1.5">
                <Label htmlFor="np-submit">Submit button</Label>
                <Input
                  id="np-submit"
                  value={submitLabel}
                  onChange={(e) => setSubmitLabel(e.target.value)}
                  className="h-8"
                />
              </div>
            )}
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input type="checkbox" checked={heading} onChange={(e) => setHeading(e.target.checked)} />
              Show page heading
            </label>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={!canCreate}>Create page</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
