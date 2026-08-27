"use client";

import { useMemo } from "react";
import { AlertTriangle, Table2, Code, Globe, Component } from "lucide-react";
import type { AppModel } from "@/types/app-model";

interface ImpactAnalysisProps {
  appModel: AppModel;
  tableName: string;
  fieldName?: string;
}

interface ImpactItem {
  type: "table" | "route" | "page" | "component";
  name: string;
  detail: string;
}

export function ImpactAnalysis({
  appModel,
  tableName,
  fieldName,
}: ImpactAnalysisProps) {
  const impacts = useMemo(() => {
    const items: ImpactItem[] = [];

    // Find tables that reference this table via relations or FK columns
    for (const table of appModel.database.tables) {
      if (table.name === tableName) continue;
      for (const rel of table.relations ?? []) {
        if (rel.target === tableName) {
          items.push({
            type: "table",
            name: table.name,
            detail: `References via ${rel.foreignKey} (${rel.type})`,
          });
        }
      }
      for (const col of table.columns) {
        if (col.references?.table === tableName) {
          items.push({
            type: "table",
            name: table.name,
            detail: `FK: ${col.name} → ${tableName}`,
          });
        }
      }
    }

    // Find API routes that mention this table
    const tablePattern = tableName.toLowerCase();
    for (const route of appModel.api?.routes ?? []) {
      if (
        route.path.toLowerCase().includes(tablePattern) ||
        route.description.toLowerCase().includes(tablePattern)
      ) {
        items.push({
          type: "route",
          name: `${route.method} ${route.path}`,
          detail: route.description,
        });
      }
    }

    // Find pages
    for (const page of appModel.pages ?? []) {
      if (
        page.path.toLowerCase().includes(tablePattern) ||
        page.description.toLowerCase().includes(tablePattern)
      ) {
        items.push({
          type: "page",
          name: page.path,
          detail: page.description,
        });
      }
    }

    // Find components
    for (const comp of appModel.components ?? []) {
      if (
        comp.name.toLowerCase().includes(tablePattern) ||
        comp.description.toLowerCase().includes(tablePattern)
      ) {
        items.push({
          type: "component",
          name: comp.name,
          detail: comp.file,
        });
      }
    }

    return items;
  }, [appModel, tableName]);

  if (impacts.length === 0) return null;

  const iconMap = {
    table: Table2,
    route: Globe,
    page: Globe,
    component: Component,
  };

  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-amber-700">
        <AlertTriangle className="h-3.5 w-3.5" />
        {impacts.length} affected reference{impacts.length !== 1 ? "s" : ""}
      </div>
      <div className="space-y-1">
        {impacts.map((item, i) => {
          const Icon = iconMap[item.type];
          return (
            <div key={i} className="flex items-start gap-1.5 text-xs text-amber-800">
              <Icon className="mt-0.5 h-3 w-3 shrink-0" />
              <div>
                <span className="font-medium">{item.name}</span>
                <span className="text-amber-600"> — {item.detail}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
