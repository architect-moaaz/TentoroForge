"use client";

import { useState } from "react";
import { Plus, X, Edit2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import type { AppModel, EnumModel } from "@/types/app-model";

interface EnumEditorProps {
  appModel: AppModel;
  projectId: string;
  onComplete?: () => void;
}

export function EnumEditor({ appModel, projectId, onComplete }: EnumEditorProps) {
  const enums = appModel.database?.enums ?? [];
  const [editingEnum, setEditingEnum] = useState<string | null>(null);
  const [enumName, setEnumName] = useState("");
  const [enumValues, setEnumValues] = useState<string[]>([]);
  const [newValue, setNewValue] = useState("");
  const [isAdding, setIsAdding] = useState(false);

  const { applyChange, isApplying, progress, error } = useSchemaChange();

  const startAdd = () => {
    setIsAdding(true);
    setEditingEnum(null);
    setEnumName("");
    setEnumValues([]);
    setNewValue("");
  };

  const startEdit = (e: EnumModel) => {
    setIsAdding(false);
    setEditingEnum(e.name);
    setEnumName(e.name);
    setEnumValues([...e.values]);
    setNewValue("");
  };

  const addValue = () => {
    const trimmed = newValue.trim();
    if (trimmed && !enumValues.includes(trimmed)) {
      setEnumValues([...enumValues, trimmed]);
      setNewValue("");
    }
  };

  const removeValue = (val: string) => {
    setEnumValues(enumValues.filter((v) => v !== val));
  };

  const handleSave = async () => {
    if (!enumName.trim() || enumValues.length === 0) return;

    const instruction = buildDataInstruction(
      isAdding
        ? { type: "add_enum", name: enumName.trim(), values: enumValues }
        : { type: "edit_enum", name: enumName.trim(), values: enumValues },
    );

    await applyChange(projectId, instruction, () => {
      onComplete?.();
      setEditingEnum(null);
      setIsAdding(false);
    });
  };

  const isEditing = isAdding || editingEnum !== null;

  if (isApplying) {
    return (
      <div className="relative p-4">
        <SchemaChangeProgress
          isApplying={isApplying}
          status={progress.status}
          filesChanged={progress.filesChanged}
          toolCalls={progress.toolCalls}
          error={error}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Enums</h3>
        {!isEditing && (
          <Button variant="outline" size="sm" onClick={startAdd}>
            <Plus className="mr-1 h-3 w-3" />
            Add Enum
          </Button>
        )}
      </div>

      {/* Existing enums */}
      {!isEditing &&
        enums.map((e) => (
          <div key={e.name} className="rounded-md border p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">{e.name}</span>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6"
                onClick={() => startEdit(e)}
              >
                <Edit2 className="h-3 w-3" />
              </Button>
            </div>
            <div className="flex flex-wrap gap-1">
              {e.values.map((v) => (
                <Badge key={v} variant="secondary" className="text-xs">
                  {v}
                </Badge>
              ))}
            </div>
          </div>
        ))}

      {enums.length === 0 && !isEditing && (
        <p className="text-xs text-muted-foreground">No enums defined yet.</p>
      )}

      {/* Edit/Add form */}
      {isEditing && (
        <div className="rounded-md border p-3 space-y-3">
          <div>
            <Label>Enum Name</Label>
            <Input
              value={enumName}
              onChange={(e) => setEnumName(e.target.value)}
              placeholder="e.g. status, role"
              disabled={!!editingEnum}
            />
          </div>
          <div>
            <Label>Values</Label>
            <div className="mb-2 flex flex-wrap gap-1">
              {enumValues.map((v) => (
                <Badge key={v} variant="secondary" className="text-xs">
                  {v}
                  <button
                    className="ml-1"
                    onClick={() => removeValue(v)}
                  >
                    <X className="h-2 w-2" />
                  </button>
                </Badge>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
                placeholder="Add value..."
                onKeyDown={(e) => e.key === "Enter" && addValue()}
              />
              <Button size="sm" variant="outline" onClick={addValue}>
                Add
              </Button>
            </div>
          </div>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setEditingEnum(null);
                setIsAdding(false);
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!enumName.trim() || enumValues.length === 0}
            >
              <Save className="mr-1 h-3 w-3" />
              Save
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
