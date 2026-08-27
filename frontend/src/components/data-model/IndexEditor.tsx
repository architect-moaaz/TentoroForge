"use client";

import { useState, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import type { AppModel } from "@/types/app-model";

interface IndexEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  tableName: string;
  appModel: AppModel;
  onComplete?: () => void;
}

export function IndexEditor({
  open,
  onOpenChange,
  projectId,
  tableName,
  appModel,
  onComplete,
}: IndexEditorProps) {
  const [selectedColumns, setSelectedColumns] = useState<string[]>([]);
  const [isUnique, setIsUnique] = useState(false);

  const { applyChange, isApplying, progress, error } = useSchemaChange();

  const table = useMemo(
    () => appModel.database.tables.find((t) => t.name === tableName),
    [appModel, tableName],
  );

  const columns = table?.columns ?? [];
  const existingIndexes = table?.indexes ?? [];

  const toggleColumn = (colName: string) => {
    setSelectedColumns((prev) =>
      prev.includes(colName)
        ? prev.filter((c) => c !== colName)
        : [...prev, colName],
    );
  };

  const handleSubmit = async () => {
    if (selectedColumns.length === 0) return;

    const instruction = buildDataInstruction({
      type: "add_index",
      table: tableName,
      columns: selectedColumns,
      unique: isUnique,
    });

    await applyChange(projectId, instruction, () => {
      onComplete?.();
      onOpenChange(false);
      setSelectedColumns([]);
      setIsUnique(false);
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Index to {tableName}</DialogTitle>
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
              {/* Existing indexes */}
              {existingIndexes.length > 0 && (
                <div>
                  <Label className="mb-1">Existing Indexes</Label>
                  <div className="space-y-1">
                    {existingIndexes.map((idx, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-xs text-muted-foreground"
                      >
                        {idx.unique && (
                          <Badge variant="outline" className="text-[10px]">
                            unique
                          </Badge>
                        )}
                        <span className="font-mono">
                          ({idx.columns.join(", ")})
                        </span>
                        {idx.name && (
                          <span className="text-[10px]">{idx.name}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Column selection */}
              <div>
                <Label className="mb-1">Select Columns</Label>
                <div className="flex flex-wrap gap-1.5">
                  {columns.map((col) => (
                    <button
                      key={col.name}
                      className={`rounded-md border px-2 py-1 text-xs transition-colors ${
                        selectedColumns.includes(col.name)
                          ? "border-blue-500 bg-blue-50 text-blue-700"
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                      onClick={() => toggleColumn(col.name)}
                    >
                      {col.name}
                    </button>
                  ))}
                </div>
              </div>

              <label className="flex items-center gap-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={isUnique}
                  onChange={(e) => setIsUnique(e.target.checked)}
                />
                Unique Index
              </label>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={selectedColumns.length === 0}
              >
                Create Index
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
