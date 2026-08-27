"use client";

/**
 * FormFieldEditor — edits formBinding for approval/user_task nodes.
 *
 * Compact field list + popup dialog for editing each field.
 */

import { useState } from "react";
import { Plus, Trash2, GripVertical, Eye, EyeOff, Lock, Unlock, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import type { FormBinding, FormField, ProcessVariable } from "@/types/workflow";

interface FormFieldEditorProps {
  formBinding: FormBinding;
  processVariables: ProcessVariable[];
  entityFields?: string[];
  onChange: (binding: FormBinding) => void;
}

const INPUT_TYPES: FormField["inputType"][] = [
  "text", "number", "select", "textarea", "date", "checkbox", "radio", "email", "file",
];

export function FormFieldEditor({
  formBinding,
  processVariables,
  entityFields = [],
  onChange,
}: FormFieldEditorProps) {
  const [showPreview, setShowPreview] = useState(false);
  const [editingField, setEditingField] = useState<{ idx: number; field: FormField } | null>(null);

  const updateField = (idx: number, updates: Partial<FormField>) => {
    const updated = [...formBinding.fields];
    updated[idx] = { ...updated[idx], ...updates };
    onChange({ ...formBinding, fields: updated });
  };

  const addField = () => {
    const newField: FormField = { name: "", label: "", inputType: "text", required: false };
    const newFields = [...formBinding.fields, newField];
    onChange({ ...formBinding, fields: newFields });
    setEditingField({ idx: newFields.length - 1, field: newField });
  };

  const removeField = (idx: number) => {
    onChange({
      ...formBinding,
      fields: formBinding.fields.filter((_, i) => i !== idx),
    });
  };

  const autoFillFromEntity = () => {
    if (entityFields.length === 0) return;
    const existing = new Set(formBinding.fields.map((f) => f.name));
    const newFields: FormField[] = entityFields
      .filter((f) => !existing.has(f) && !["id", "createdAt", "updatedAt"].includes(f))
      .map((f) => ({
        name: f,
        label: f.replace(/([A-Z])/g, " $1").replace(/^./, (s) => s.toUpperCase()).trim(),
        inputType: "text" as const,
        source: f,
        readOnly: true,
        required: false,
      }));
    onChange({ ...formBinding, fields: [...formBinding.fields, ...newFields] });
  };

  const saveEditingField = () => {
    if (!editingField) return;
    updateField(editingField.idx, editingField.field);
    setEditingField(null);
  };

  return (
    <div className="space-y-3">
      {/* Title & Description */}
      <div>
        <Label className="text-[10px]" htmlFor="wf-form-title">Form Title</Label>
        <Input
          id="wf-form-title"
          className="h-7 text-xs"
          placeholder="Review & Approve"
          value={formBinding.title || ""}
          onChange={(e) => onChange({ ...formBinding, title: e.target.value })}
        />
      </div>
      <div>
        <Label className="text-[10px]" htmlFor="wf-description">Description</Label>
        <Input
          id="wf-description"
          className="h-7 text-xs"
          placeholder="Review the details and take action"
          value={formBinding.description || ""}
          onChange={(e) => onChange({ ...formBinding, description: e.target.value })}
        />
      </div>

      {/* Fields header */}
      <div className="flex items-center justify-between">
        <Label className="text-xs font-semibold">Form Fields ({formBinding.fields.length})</Label>
        <div className="flex gap-1">
          {entityFields.length > 0 && (
            <Button variant="outline" size="sm" className="h-6 px-2 text-[10px]" onClick={autoFillFromEntity}>
              Auto-fill
            </Button>
          )}
          <Button variant="default" size="sm" className="h-6 px-2 text-[10px]" onClick={addField}>
            <Plus className="h-3 w-3 mr-0.5" /> Add
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0"
            onClick={() => setShowPreview(!showPreview)}
          >
            {showPreview ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
          </Button>
        </div>
      </div>

      {formBinding.fields.length === 0 && (
        <p className="text-[10px] text-muted-foreground py-2 text-center">
          No form fields. Click "Add" or "Auto-fill" to add fields.
        </p>
      )}

      {/* Compact field list */}
      <div className="space-y-1">
        {formBinding.fields.map((field, idx) => (
          <div
            key={idx}
            className="flex items-center gap-1.5 rounded-lg border bg-muted/20 px-2 py-1.5 group hover:bg-muted/40 transition-colors"
          >
            <GripVertical className="h-3 w-3 text-muted-foreground shrink-0 cursor-grab" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium truncate">{field.label || field.name || "(unnamed)"}</span>
                <span className="text-[9px] text-muted-foreground px-1 py-0.5 rounded bg-muted shrink-0">
                  {field.inputType}
                </span>
                {field.readOnly && <Lock className="h-2.5 w-2.5 text-amber-500 shrink-0" />}
                {field.required && <span className="text-[9px] text-red-500 shrink-0">*</span>}
              </div>
              {field.source && (
                <span className="text-[9px] text-muted-foreground font-mono">{field.source}</span>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100"
              onClick={() => setEditingField({ idx, field: { ...field } })}
            >
              <Pencil className="h-3 w-3 text-muted-foreground" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100"
              onClick={() => removeField(idx)}
            >
              <Trash2 className="h-3 w-3 text-muted-foreground" />
            </Button>
          </div>
        ))}
      </div>

      {/* Button labels */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-[10px]" htmlFor="wf-submit-label">Submit Label</Label>
          <Input
            id="wf-submit-label"
            className="h-7 text-xs"
            placeholder="Approve"
            value={formBinding.submitLabel || ""}
            onChange={(e) => onChange({ ...formBinding, submitLabel: e.target.value })}
          />
        </div>
        <div>
          <Label className="text-[10px]" htmlFor="wf-reject-label">Reject Label</Label>
          <Input
            id="wf-reject-label"
            className="h-7 text-xs"
            placeholder="Reject"
            value={formBinding.rejectLabel || ""}
            onChange={(e) => onChange({ ...formBinding, rejectLabel: e.target.value })}
          />
        </div>
      </div>

      {/* Preview */}
      {showPreview && formBinding.fields.length > 0 && (
        <div className="rounded-xl border bg-background p-4 space-y-3">
          <div>
            <p className="text-sm font-semibold">{formBinding.title || "Task Form"}</p>
            {formBinding.description && (
              <p className="text-[11px] text-muted-foreground mt-0.5">{formBinding.description}</p>
            )}
          </div>
          {formBinding.fields.map((field, idx) => (
            <div key={idx} className="space-y-1">
              <label className="text-[11px] font-medium flex items-center gap-1">
                {field.label || field.name}
                {field.required && <span className="text-red-500">*</span>}
                {field.readOnly && <Lock className="h-2.5 w-2.5 text-muted-foreground" />}
              </label>
              {field.inputType === "textarea" ? (
                <div className="h-14 rounded-lg border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
                  {field.readOnly ? `{{${field.source || field.name}}}` : field.placeholder || "Enter text..."}
                </div>
              ) : field.inputType === "checkbox" ? (
                <label className="flex items-center gap-2 text-[11px]">
                  <input type="checkbox" disabled className="rounded" />
                  {field.label || field.name}
                </label>
              ) : (
                <div className="h-8 rounded-lg border bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
                  {field.readOnly ? `{{${field.source || field.name}}}` : field.placeholder || `Enter ${field.inputType}...`}
                </div>
              )}
            </div>
          ))}
          <div className="flex gap-2 pt-2">
            <div className="h-8 rounded-lg bg-primary px-4 py-1.5 text-xs text-primary-foreground font-medium">
              {formBinding.submitLabel || "Submit"}
            </div>
            {formBinding.rejectLabel && (
              <div className="h-8 rounded-lg border border-destructive/50 px-4 py-1.5 text-xs text-destructive font-medium">
                {formBinding.rejectLabel}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Field edit dialog */}
      <Dialog open={!!editingField} onOpenChange={(open) => { if (!open) setEditingField(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base">
              {editingField?.field.name ? `Edit: ${editingField.field.label || editingField.field.name}` : "Add Form Field"}
            </DialogTitle>
          </DialogHeader>
          {editingField && (
            <div className="space-y-4 py-2">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs" htmlFor="wf-field-name">Field Name</Label>
                  <Input
                    id="wf-field-name"
                    className="mt-1 h-8 text-sm font-mono"
                    placeholder="fieldName"
                    value={editingField.field.name}
                    onChange={(e) => setEditingField({ ...editingField, field: { ...editingField.field, name: e.target.value } })}
                    autoFocus
                  />
                </div>
                <div>
                  <Label className="text-xs" htmlFor="wf-label">Label</Label>
                  <Input
                    id="wf-label"
                    className="mt-1 h-8 text-sm"
                    placeholder="Display Label"
                    value={editingField.field.label}
                    onChange={(e) => setEditingField({ ...editingField, field: { ...editingField.field, label: e.target.value } })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">Input Type</Label>
                  <Select
                    value={editingField.field.inputType}
                    onValueChange={(v) => setEditingField({ ...editingField, field: { ...editingField.field, inputType: v as FormField["inputType"] } })}
                  >
                    <SelectTrigger className="mt-1 h-8 text-sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INPUT_TYPES.map((t) => (
                        <SelectItem key={t} value={t} className="text-sm">{t}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs" htmlFor="wf-placeholder">Placeholder</Label>
                  <Input
                    id="wf-placeholder"
                    className="mt-1 h-8 text-sm"
                    placeholder="Enter value..."
                    value={editingField.field.placeholder || ""}
                    onChange={(e) => setEditingField({ ...editingField, field: { ...editingField.field, placeholder: e.target.value } })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs">Source (pre-fill from)</Label>
                  <Select
                    value={editingField.field.source || "__none__"}
                    onValueChange={(v) => setEditingField({ ...editingField, field: { ...editingField.field, source: v === "__none__" ? undefined : v } })}
                  >
                    <SelectTrigger className="mt-1 h-8 text-sm">
                      <SelectValue placeholder="No pre-fill" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__" className="text-sm text-muted-foreground">No pre-fill</SelectItem>
                      {processVariables.map((pv) => (
                        <SelectItem key={pv.name} value={pv.name} className="text-sm">{pv.name}</SelectItem>
                      ))}
                      {entityFields.filter(f => !processVariables.some(pv => pv.name === f)).map((f) => (
                        <SelectItem key={f} value={f} className="text-sm">{f} (entity)</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs">Target (write to)</Label>
                  <Select
                    value={editingField.field.target || "__none__"}
                    onValueChange={(v) => setEditingField({ ...editingField, field: { ...editingField.field, target: v === "__none__" ? undefined : v } })}
                  >
                    <SelectTrigger className="mt-1 h-8 text-sm">
                      <SelectValue placeholder="No write-back" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__" className="text-sm text-muted-foreground">No write-back</SelectItem>
                      {processVariables.map((pv) => (
                        <SelectItem key={pv.name} value={pv.name} className="text-sm">{pv.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="flex items-center gap-6 pt-1">
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editingField.field.readOnly || false}
                    onChange={(e) => setEditingField({ ...editingField, field: { ...editingField.field, readOnly: e.target.checked } })}
                    className="rounded"
                  />
                  <Lock className="h-3.5 w-3.5 text-amber-500" />
                  Read-only
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editingField.field.required || false}
                    onChange={(e) => setEditingField({ ...editingField, field: { ...editingField.field, required: e.target.checked } })}
                    className="rounded"
                  />
                  <span className="text-red-500 font-bold">*</span>
                  Required
                </label>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setEditingField(null)}>
              Cancel
            </Button>
            <Button size="sm" onClick={saveEditingField}>
              Save Field
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
