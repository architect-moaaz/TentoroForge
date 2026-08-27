"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AppModel, ColumnModel, EnumModel } from "@/types/app-model";

/**
 * Canonical data-model source for the platform: reads the SAME
 * `/api/projects/{id}/app-model` that the Data Model editor + ERD + decision
 * autocomplete use. Exposes models, typed fields, and enums so any editor can
 * bind its field pickers / type logic to the project's real schema.
 *
 * 404s before an app is generated (or before a data model is defined) — we
 * don't retry, and callers fall back to free-text field entry.
 */
export interface ProjectDataModel {
  appModel: AppModel | null;
  /** Entity/table names. */
  models: string[];
  /** model name -> typed columns. */
  fieldsByModel: Record<string, ColumnModel[]>;
  enums: EnumModel[];
  /** Enum values for a column type that names an enum (else null). */
  enumValuesForType: (type: string | undefined) => string[] | null;
  /** Typed columns for one model (empty if unknown). */
  getFields: (model: string | null | undefined) => ColumnModel[];
  /** True once a usable data model is present. */
  hasModel: boolean;
  isLoading: boolean;
  isError: boolean;
}

export function useProjectDataModel(projectId: string): ProjectDataModel {
  const query = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
    retry: false,
    staleTime: 30_000,
  });

  return useMemo(() => {
    const appModel = query.data ?? null;
    const tables = appModel?.database?.tables ?? [];
    const enums = appModel?.database?.enums ?? [];

    const fieldsByModel: Record<string, ColumnModel[]> = {};
    for (const t of tables) {
      fieldsByModel[t.name] = Array.isArray(t.columns) ? t.columns : [];
    }

    const enumValuesForType = (type: string | undefined): string[] | null => {
      if (!type) return null;
      const lower = type.toLowerCase();
      const e = enums.find((en) => en.name === type || en.name.toLowerCase() === lower);
      return e ? e.values : null;
    };

    const getFields = (model: string | null | undefined): ColumnModel[] =>
      model ? fieldsByModel[model] ?? [] : [];

    return {
      appModel,
      models: tables.map((t) => t.name),
      fieldsByModel,
      enums,
      enumValuesForType,
      getFields,
      hasModel: tables.length > 0,
      isLoading: query.isLoading,
      isError: query.isError,
    };
  }, [query.data, query.isLoading, query.isError]);
}
