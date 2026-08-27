"use client";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { buildDataInstruction } from "@/lib/instruction-builder";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { ImpactAnalysis } from "./ImpactAnalysis";
import { SchemaChangeProgress } from "./SchemaChangeProgress";
import type { AppModel } from "@/types/app-model";

interface DeleteConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  target: {
    type: "model" | "field";
    table: string;
    field?: string;
  };
  appModel: AppModel;
  onComplete?: () => void;
}

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  projectId,
  target,
  appModel,
  onComplete,
}: DeleteConfirmDialogProps) {
  const { applyChange, isApplying, progress, error } = useSchemaChange();

  const handleDelete = async () => {
    const instruction =
      target.type === "model"
        ? buildDataInstruction({ type: "delete_model", name: target.table })
        : buildDataInstruction({
            type: "delete_field",
            table: target.table,
            fieldName: target.field!,
          });

    await applyChange(projectId, instruction, () => {
      onComplete?.();
      onOpenChange(false);
    });
  };

  const label =
    target.type === "model"
      ? `model "${target.table}"`
      : `field "${target.field}" from "${target.table}"`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete {target.type === "model" ? "Model" : "Field"}</DialogTitle>
          <DialogDescription>
            Are you sure you want to delete {label}? This action will modify the
            schema and related code.
          </DialogDescription>
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
            <ImpactAnalysis
              appModel={appModel}
              tableName={target.table}
              fieldName={target.field}
            />

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button variant="destructive" onClick={handleDelete}>
                Delete
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
