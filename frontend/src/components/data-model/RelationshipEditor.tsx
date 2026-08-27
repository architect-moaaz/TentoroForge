"use client";

import { useState } from "react";
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
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import type { AppModel } from "@/types/app-model";

interface RelationshipEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  sourceTable: string;
  appModel: AppModel;
  onComplete?: () => void;
}

type RelationType = "one-to-one" | "one-to-many" | "many-to-many";

export function RelationshipEditor({
  open,
  onOpenChange,
  projectId,
  sourceTable,
  appModel,
  onComplete,
}: RelationshipEditorProps) {
  const [targetTable, setTargetTable] = useState("");
  const [relationType, setRelationType] = useState<RelationType>("one-to-many");
  const [foreignKey, setForeignKey] = useState("");

  const { applyChange, isApplying, progress, error } = useSchemaChange();

  const otherTables = appModel.database.tables
    .filter((t) => t.name !== sourceTable)
    .map((t) => t.name);

  // Auto-suggest FK name
  const suggestedFK = targetTable
    ? `${targetTable.replace(/s$/, "")}_id`
    : "";

  const handleSubmit = async () => {
    if (!targetTable) return;

    const instruction = buildDataInstruction({
      type: "add_relation",
      source: sourceTable,
      target: targetTable,
      relationType,
      foreignKey: foreignKey || suggestedFK,
    });

    await applyChange(projectId, instruction, () => {
      onComplete?.();
      onOpenChange(false);
      setTargetTable("");
      setForeignKey("");
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Relationship from {sourceTable}</DialogTitle>
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
                <Label>Target Table</Label>
                <Select value={targetTable} onValueChange={setTargetTable}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select table" />
                  </SelectTrigger>
                  <SelectContent>
                    {otherTables.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label>Relation Type</Label>
                <Select
                  value={relationType}
                  onValueChange={(v) => setRelationType(v as RelationType)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="one-to-one">One-to-One (1:1)</SelectItem>
                    <SelectItem value="one-to-many">One-to-Many (1:N)</SelectItem>
                    <SelectItem value="many-to-many">Many-to-Many (N:M)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label>Foreign Key Column</Label>
                <Input
                  placeholder={suggestedFK || "e.g. user_id"}
                  value={foreignKey}
                  onChange={(e) => setForeignKey(e.target.value)}
                />
                {suggestedFK && !foreignKey && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Suggested: {suggestedFK}
                  </p>
                )}
              </div>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={!targetTable}>
                Create Relationship
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
