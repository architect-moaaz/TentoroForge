"use client";
import * as React from "react";
import { Plus, Trash2, LayoutGrid, Square } from "lucide-react";
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
  type LayoutPreset,
  type ScaffoldFieldKind,
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

let rowSeq = 0;
const mkRow = (label: string, kind: ScaffoldFieldKind, required = false): FieldRow => ({
  key: `f${++rowSeq}`, label, kind, required,
});

export interface NewPageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  existingPageIds: string[];
  existingRoutes: string[];
  onCreate: (page: ScaffoldedPage) => void;
}

/**
 * "New Page → Layout → Form" dialog. Collects a title, a layout preset, and a
 * set of form fields, then builds a valid Page via `scaffoldPage` and hands it
 * to `onCreate` (the caller dispatches `addPage` + persists + activates).
 */
export function NewPageDialog({
  open, onOpenChange, existingPageIds, existingRoutes, onCreate,
}: NewPageDialogProps) {
  const [title, setTitle] = React.useState("");
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
      setLayout("centered");
      setHeading(true);
      setSubmitLabel("Submit");
      setFields([mkRow("Name", "text", true), mkRow("Email", "email", true)]);
    }
  }, [open]);

  const trimmed = title.trim();
  const previewSlug = slugify(trimmed) || "page";
  const canCreate = trimmed.length > 0 && fields.length > 0 && fields.every((f) => f.label.trim());

  const updateField = (key: string, patch: Partial<FieldRow>) =>
    setFields((rows) => rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const removeField = (key: string) =>
    setFields((rows) => rows.filter((r) => r.key !== key));
  const addField = () => setFields((rows) => [...rows, mkRow("", "text", false)]);

  const handleCreate = () => {
    if (!canCreate) return;
    const page = scaffoldPage({
      title: trimmed,
      layout,
      heading,
      submitLabel,
      fields: fields.map((f) => ({ label: f.label.trim(), kind: f.kind, required: f.required })),
      existingPageIds,
      existingRoutes,
    });
    onCreate(page);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>New page</DialogTitle>
          <DialogDescription>
            Creates a page with a layout and a form. You can edit everything after.
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

          {/* Layout preset */}
          <div className="space-y-1.5">
            <Label>Layout</Label>
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

          {/* Fields */}
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

          {/* Options */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="np-submit">Submit button</Label>
              <Input
                id="np-submit"
                value={submitLabel}
                onChange={(e) => setSubmitLabel(e.target.value)}
                className="h-8"
              />
            </div>
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
