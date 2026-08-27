"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Pencil, Minus, Loader2, Save } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import type { FieldAccessMatrix as FieldAccessMatrixType } from "@/types/rules";
import type { AppModel } from "@/types/app-model";

interface FieldAccessMatrixProps {
  projectId: string;
  orgId: string;
}

type CellState = "view" | "edit" | "hidden";

function nextState(current: CellState): CellState {
  switch (current) {
    case "edit":
      return "view";
    case "view":
      return "hidden";
    case "hidden":
      return "edit";
  }
}

const CELL_ICONS: Record<CellState, typeof Eye> = {
  view: Eye,
  edit: Pencil,
  hidden: Minus,
};

const CELL_COLORS: Record<CellState, string> = {
  edit: "bg-green-100 text-green-700",
  view: "bg-blue-100 text-blue-700",
  hidden: "bg-gray-100 text-gray-400",
};

export function FieldAccessMatrix({ projectId, orgId }: FieldAccessMatrixProps) {
  const queryClient = useQueryClient();
  const { applyChange, isApplying, progress } = useSchemaChange();
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [cells, setCells] = useState<Record<string, CellState>>({});
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Fetch app model for table names
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];

  // Fetch matrix for selected model
  const { data: matrix, isLoading: matrixLoading } = useQuery({
    queryKey: ["project", projectId, "field-access-matrix", selectedModel],
    queryFn: () =>
      api.get<FieldAccessMatrixType>(
        `/api/projects/${projectId}/field-access/matrix?model_name=${selectedModel}`,
      ),
    enabled: !!selectedModel,
  });

  // Sync matrix data to local cell state
  useEffect(() => {
    if (!matrix) return;
    const newCells: Record<string, CellState> = {};
    for (const cell of matrix.cells) {
      const key = `${cell.field_name}:${cell.target_id}`;
      if (!cell.can_view) {
        newCells[key] = "hidden";
      } else if (!cell.can_edit) {
        newCells[key] = "view";
      } else {
        newCells[key] = "edit";
      }
    }
    setCells(newCells);
    setIsDirty(false);
  }, [matrix]);

  // Auto-select first model
  useEffect(() => {
    if (modelNames.length > 0 && !selectedModel) {
      setSelectedModel(modelNames[0]);
    }
  }, [modelNames, selectedModel]);

  const getCellState = (field: string, targetId: string): CellState => {
    return cells[`${field}:${targetId}`] || "edit";
  };

  const toggleCell = (field: string, targetId: string) => {
    const key = `${field}:${targetId}`;
    const current = cells[key] || "edit";
    setCells({ ...cells, [key]: nextState(current) });
    setIsDirty(true);
  };

  const handleSave = async () => {
    if (!matrix || !selectedModel) return;
    setIsSaving(true);

    try {
      // Save each cell as a field access policy
      for (const field of matrix.fields) {
        for (const target of matrix.targets) {
          const state = getCellState(field, target.id);
          await api.post(`/api/projects/${projectId}/field-access`, {
            model_name: selectedModel,
            field_name: field,
            target_type: target.type,
            target_id: target.id,
            can_view: state !== "hidden",
            can_edit: state === "edit",
          });
        }
      }

      setIsDirty(false);
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "field-access-matrix"],
      });
    } catch (err) {
      console.error("Failed to save field access:", err);
    } finally {
      setIsSaving(false);
    }
  };

  const handleApply = async () => {
    await applyChange(projectId, "Apply field access RBAC middleware", () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "app-model"],
      });
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Select value={selectedModel} onValueChange={setSelectedModel}>
          <SelectTrigger className="h-8 w-[200px] text-xs">
            <SelectValue placeholder="Select model..." />
          </SelectTrigger>
          <SelectContent>
            {modelNames.map((m) => (
              <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="ml-auto flex gap-2">
          {isDirty && (
            <Button
              size="sm"
              className="h-8 text-xs"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <Save className="mr-1 h-3 w-3" />
              )}
              Save
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            onClick={handleApply}
            disabled={isApplying || isDirty}
          >
            {isApplying ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : null}
            Apply RBAC
          </Button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Pencil className="h-3 w-3 text-green-600" /> Edit
        </span>
        <span className="flex items-center gap-1">
          <Eye className="h-3 w-3 text-blue-600" /> View only
        </span>
        <span className="flex items-center gap-1">
          <Minus className="h-3 w-3 text-gray-400" /> Hidden
        </span>
      </div>

      {matrixLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : matrix && matrix.targets.length > 0 ? (
        <div className="overflow-auto rounded-md border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/30">
                <th className="sticky left-0 bg-muted/30 px-3 py-2 text-left font-medium text-muted-foreground">
                  Field
                </th>
                {matrix.targets.map((t) => (
                  <th
                    key={t.id}
                    className="px-3 py-2 text-center font-medium text-muted-foreground"
                  >
                    {t.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.fields.map((field) => (
                <tr key={field} className="border-b">
                  <td className="sticky left-0 bg-white px-3 py-2 font-medium">
                    {field}
                  </td>
                  {matrix.targets.map((target) => {
                    const state = getCellState(field, target.id);
                    const Icon = CELL_ICONS[state];
                    return (
                      <td key={target.id} className="px-3 py-2 text-center">
                        <button
                          type="button"
                          className={`inline-flex items-center justify-center rounded p-1 ${CELL_COLORS[state]}`}
                          onClick={() => toggleCell(field, target.id)}
                          title={`${state} — click to change`}
                        >
                          <Icon className="h-3 w-3" />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : selectedModel ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          No roles found. Create roles in org settings first.
        </p>
      ) : null}

      {/* Apply progress */}
      {isApplying && (
        <div className="rounded-md border bg-muted/20 p-3">
          <div className="flex items-center gap-2 text-xs">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span>{progress.status || "Applying RBAC..."}</span>
          </div>
        </div>
      )}
    </div>
  );
}
