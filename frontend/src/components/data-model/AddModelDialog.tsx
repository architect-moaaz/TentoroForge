"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
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
import { DRIZZLE_COLUMN_TYPES } from "@/types/app-model";
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { SchemaChangeProgress } from "./SchemaChangeProgress";

interface FieldRow {
  name: string;
  type: string;
  primaryKey: boolean;
  nullable: boolean;
  unique: boolean;
}

interface AddModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  onComplete?: () => void;
}

export function AddModelDialog({
  open,
  onOpenChange,
  projectId,
  onComplete,
}: AddModelDialogProps) {
  const [modelName, setModelName] = useState("");
  const [fields, setFields] = useState<FieldRow[]>([
    { name: "id", type: "serial", primaryKey: true, nullable: false, unique: false },
  ]);
  const { applyChange, isApplying, progress, error } = useSchemaChange();

  const addField = () => {
    setFields([
      ...fields,
      { name: "", type: "text", primaryKey: false, nullable: true, unique: false },
    ]);
  };

  const updateField = (idx: number, updates: Partial<FieldRow>) => {
    setFields(fields.map((f, i) => (i === idx ? { ...f, ...updates } : f)));
  };

  const removeField = (idx: number) => {
    setFields(fields.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {
    if (!modelName.trim()) return;
    const instruction = buildDataInstruction({
      type: "add_model",
      name: modelName.trim(),
      fields: fields.filter((f) => f.name.trim()),
    });
    await applyChange(projectId, instruction, () => {
      onComplete?.();
      onOpenChange(false);
      setModelName("");
      setFields([
        { name: "id", type: "serial", primaryKey: true, nullable: false, unique: false },
      ]);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add New Model</DialogTitle>
        </DialogHeader>

        {isApplying ? (
          <SchemaChangeProgress
            isApplying={isApplying}
            status={progress.status}
            filesChanged={progress.filesChanged}
            toolCalls={progress.toolCalls}
            error={error}
          />
        ) : (
          <>
            <div className="space-y-4">
              <div>
                <Label htmlFor="model-name">Model Name</Label>
                <Input
                  id="model-name"
                  placeholder="e.g. posts, categories"
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                />
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <Label>Fields</Label>
                  <Button variant="ghost" size="sm" onClick={addField}>
                    <Plus className="mr-1 h-3 w-3" />
                    Add Field
                  </Button>
                </div>
                <div className="space-y-2">
                  {fields.map((field, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <Input
                        placeholder="name"
                        value={field.name}
                        onChange={(e) => updateField(idx, { name: e.target.value })}
                        className="flex-1 text-sm"
                      />
                      <Select
                        value={field.type}
                        onValueChange={(v) => updateField(idx, { type: v })}
                      >
                        <SelectTrigger className="w-32 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {DRIZZLE_COLUMN_TYPES.map((t) => (
                            <SelectItem key={t} value={t} className="text-xs">
                              {t}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <label className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={field.primaryKey}
                          onChange={(e) =>
                            updateField(idx, { primaryKey: e.target.checked })
                          }
                        />
                        PK
                      </label>
                      <label className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={field.nullable}
                          onChange={(e) =>
                            updateField(idx, { nullable: e.target.checked })
                          }
                        />
                        Null
                      </label>
                      <label className="flex items-center gap-1 text-xs">
                        <input
                          type="checkbox"
                          checked={field.unique}
                          onChange={(e) =>
                            updateField(idx, { unique: e.target.checked })
                          }
                        />
                        Uniq
                      </label>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => removeField(idx)}
                        disabled={fields.length === 1}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={!modelName.trim()}>
                Create Model
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
