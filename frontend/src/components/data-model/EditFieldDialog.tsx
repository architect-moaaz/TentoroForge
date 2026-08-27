"use client";

import { useState, useEffect, useMemo } from "react";
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
import type { AppModel, ColumnModel } from "@/types/app-model";
import type { SmartFieldConfig } from "@/types/ai-features";
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import { SmartFieldEditor } from "./SmartFieldEditor";

interface EditFieldDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  tableName: string;
  columnName?: string; // undefined = add mode
  appModel: AppModel;
  onComplete?: () => void;
}

export function EditFieldDialog({
  open,
  onOpenChange,
  projectId,
  tableName,
  columnName,
  appModel,
  onComplete,
}: EditFieldDialogProps) {
  const isEdit = !!columnName;
  const existingColumn = useMemo(() => {
    if (!columnName) return null;
    const table = appModel.database.tables.find((t) => t.name === tableName);
    return table?.columns.find((c) => c.name === columnName) ?? null;
  }, [appModel, tableName, columnName]);

  const [name, setName] = useState("");
  const [type, setType] = useState("text");
  const [typeLength, setTypeLength] = useState("");
  const [nullable, setNullable] = useState(true);
  const [unique, setUnique] = useState(false);
  const [defaultValue, setDefaultValue] = useState("");
  const [refTable, setRefTable] = useState("");
  const [refColumn, setRefColumn] = useState("id");
  const [smartConfig, setSmartConfig] = useState<SmartFieldConfig | undefined>(undefined);

  // Types that support a length/precision parameter
  const TYPES_WITH_LENGTH = ["varchar", "char", "numeric", "decimal"];

  const { applyChange, isApplying, progress, error } = useSchemaChange();

  // Get field names for the current table (for smart field source picker)
  const currentTableFields = useMemo(() => {
    const table = appModel.database.tables.find((t) => t.name === tableName);
    return table?.columns.map((c) => c.name).filter((n) => n !== columnName) ?? [];
  }, [appModel, tableName, columnName]);

  // Parse a type string like "varchar(255)" into { base: "varchar", length: "255" }
  const parseType = (raw: string) => {
    const match = raw.match(/^(\w+)\((.+)\)$/);
    if (match) return { base: match[1], length: match[2] };
    return { base: raw, length: "" };
  };

  // Initialize from existing column in edit mode
  useEffect(() => {
    if (existingColumn) {
      const parsed = parseType(existingColumn.type);
      setName(existingColumn.name);
      setType(parsed.base);
      setTypeLength(parsed.length);
      setNullable(existingColumn.nullable ?? false);
      setUnique(existingColumn.unique ?? false);
      setDefaultValue(existingColumn.default ?? "");
      setRefTable(existingColumn.references?.table ?? "");
      setRefColumn(existingColumn.references?.column ?? "id");
      setSmartConfig(existingColumn.smart);
    } else {
      setName("");
      setType("text");
      setTypeLength("");
      setNullable(true);
      setUnique(false);
      setDefaultValue("");
      setRefTable("");
      setRefColumn("id");
      setSmartConfig(undefined);
    }
  }, [existingColumn]);

  const otherTables = appModel.database.tables
    .filter((t) => t.name !== tableName)
    .map((t) => t.name);

  const handleSubmit = async () => {
    if (!name.trim()) return;

    // Recombine base type with length: "varchar" + "255" → "varchar(255)"
    const fullType = typeLength && TYPES_WITH_LENGTH.includes(type)
      ? `${type}(${typeLength})`
      : type;

    const field = {
      name: name.trim(),
      type: fullType,
      nullable,
      unique,
      default: defaultValue || undefined,
      references: refTable ? { table: refTable, column: refColumn } : undefined,
      smart: smartConfig,
    };

    const instruction = isEdit
      ? buildDataInstruction({
          type: "edit_field",
          table: tableName,
          oldName: columnName!,
          field,
        })
      : buildDataInstruction({
          type: "add_field",
          table: tableName,
          field,
        });

    await applyChange(projectId, instruction, () => {
      onComplete?.();
      onOpenChange(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {isEdit ? `Edit Field: ${columnName}` : `Add Field to ${tableName}`}
          </DialogTitle>
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
            <div className="space-y-3">
              <div>
                <Label>Field Name</Label>
                <Input
                  placeholder="e.g. title, email"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>

              <div>
                <Label>Type</Label>
                <div className="flex gap-2">
                  <Select value={type} onValueChange={(v) => { setType(v); if (!TYPES_WITH_LENGTH.includes(v)) setTypeLength(""); }}>
                    <SelectTrigger className={TYPES_WITH_LENGTH.includes(type) ? "flex-1" : ""}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {DRIZZLE_COLUMN_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {TYPES_WITH_LENGTH.includes(type) && (
                    <Input
                      value={typeLength}
                      onChange={(e) => setTypeLength(e.target.value)}
                      placeholder="255"
                      className="w-20"
                    />
                  )}
                </div>
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={nullable}
                    onChange={(e) => setNullable(e.target.checked)}
                  />
                  Nullable
                </label>
                <label className="flex items-center gap-1.5 text-sm">
                  <input
                    type="checkbox"
                    checked={unique}
                    onChange={(e) => setUnique(e.target.checked)}
                  />
                  Unique
                </label>
              </div>

              <div>
                <Label>Default Value</Label>
                <Input
                  placeholder="Optional"
                  value={defaultValue}
                  onChange={(e) => setDefaultValue(e.target.value)}
                />
              </div>

              <div>
                <Label>References (Foreign Key)</Label>
                <div className="flex gap-2">
                  <Select value={refTable || "__none__"} onValueChange={(v) => setRefTable(v === "__none__" ? "" : v)}>
                    <SelectTrigger className="flex-1">
                      <SelectValue placeholder="None" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">None</SelectItem>
                      {otherTables.map((t) => (
                        <SelectItem key={t} value={t}>
                          {t}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {refTable && (
                    <Input
                      value={refColumn}
                      onChange={(e) => setRefColumn(e.target.value)}
                      placeholder="column"
                      className="w-24"
                    />
                  )}
                </div>
              </div>

              {/* Smart Field (AI) */}
              <SmartFieldEditor
                config={smartConfig}
                onChange={setSmartConfig}
                fieldNames={currentTableFields}
                projectId={projectId}
              />
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={!name.trim()}>
                {isEdit ? "Update Field" : "Add Field"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
