"use client";

/**
 * Data Binding Panel — browse entities from app-model.json and bind
 * fields to the selected GrapeJS element.
 */

import { useEffect, useState, useCallback } from "react";
import type { Editor, Component as GjsComponent } from "grapesjs";
import { Database, Table2, Plus, Link2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

interface DataBindingPanelProps {
  editor: Editor | null;
  projectId: string;
}

interface EntityInfo {
  name: string;
  table?: string;
  fields: FieldInfo[];
}

interface FieldInfo {
  name: string;
  type: string;
  primaryKey?: boolean;
  nullable?: boolean;
}

export function DataBindingPanel({ editor, projectId }: DataBindingPanelProps) {
  const [entities, setEntities] = useState<EntityInfo[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<GjsComponent | null>(null);

  // Track selected element in editor
  useEffect(() => {
    if (!editor) return;
    const onSelect = (c: GjsComponent) => setSelected(c);
    const onDeselect = () => setSelected(null);
    editor.on("component:selected", onSelect);
    editor.on("component:deselected", onDeselect);
    return () => {
      editor.off("component:selected", onSelect);
      editor.off("component:deselected", onDeselect);
    };
  }, [editor]);

  // Load entities from app-model or DB tables
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        // Try app-model first
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/app-model`);
        if (res.ok) {
          const data = await res.json();
          const entityMap = data.entities || {};
          const parsed: EntityInfo[] = Object.keys(entityMap).map((name) => ({
            name,
            table: entityMap[name]?.table,
            fields: [],
          }));

          // Also try to load DB tables for field info
          const tablesRes = await fetch(`${API_BASE}/api/projects/${projectId}/db/tables`);
          if (tablesRes.ok) {
            const tables = await tablesRes.json();
            const withFields = parsed.map((e) => {
              const tableData = (tables.tables || []).find(
                (t: any) => t.name === e.table || t.name === e.name.toLowerCase() + "s",
              );
              return {
                ...e,
                fields: tableData?.columns?.map((c: any) => ({
                  name: c.name,
                  type: c.type,
                  primaryKey: c.primaryKey,
                  nullable: c.nullable,
                })) || [],
              };
            });
            setEntities(withFields);
          } else {
            setEntities(parsed);
          }
        } else {
          // Fallback: try IR manifest for entity data
          const irRes = await fetch(`${API_BASE}/api/projects/${projectId}/ir`);
          if (irRes.ok) {
            const ir = await irRes.json();
            const sources = ir.dataSources || {};
            const irEntities: EntityInfo[] = Object.keys(sources)
              .filter((k) => sources[k]?.method === "GET" && !k.includes("dashboard") && !k.includes("auth"))
              .map((k) => ({
                name: k.charAt(0).toUpperCase() + k.slice(1).replace(/s$/, ""),
                table: k,
                fields: [
                  { name: "id", type: "integer", primaryKey: true },
                  { name: "name", type: "text" },
                  { name: "status", type: "text" },
                  { name: "created_at", type: "timestamp" },
                ],
              }));
            if (irEntities.length > 0) {
              setEntities(irEntities);
            }
          }

          // Last fallback: extract from design HTML annotations
          if (entities.length === 0) {
            const designRes = await fetch(`${API_BASE}/api/projects/${projectId}/design`);
            if (designRes.ok) {
              const design = await designRes.json();
              const entityNames = new Set<string>();
              for (const page of design.pages || []) {
                const matches = page.html?.matchAll(/data-entity="([^"]+)"/g) || [];
                for (const m of matches) {
                  entityNames.add(m[1]);
                }
              }
              if (entityNames.size > 0) {
                setEntities(
                  Array.from(entityNames).map((name) => ({
                    name,
                    fields: [
                      { name: "id", type: "integer", primaryKey: true },
                      { name: "name", type: "text" },
                      { name: "email", type: "text" },
                      { name: "status", type: "text" },
                      { name: "created_at", type: "timestamp" },
                    ],
                  })),
                );
              }
            }
          }
        }
      } catch (err) {
        console.warn("Failed to load entities:", err);
      }
      setLoading(false);
    }
    load();
  }, [projectId]);

  const activeEntity = entities.find((e) => e.name === selectedEntity);

  // Bind a field to the selected element
  const bindField = useCallback(
    (field: string, bindType: "bind" | "field" | "repeat") => {
      if (!selected) return;
      if (bindType === "bind") {
        selected.addAttributes({ "data-bind": `state:form.${field}` });
      } else if (bindType === "field") {
        selected.addAttributes({ "data-field": field });
      } else if (bindType === "repeat") {
        selected.addAttributes({ "data-repeat": selectedEntity.toLowerCase() + "s" });
      }
    },
    [selected, selectedEntity],
  );

  // Insert a pre-built form for the entity
  const insertForm = useCallback(() => {
    if (!editor || !activeEntity) return;
    const fields = activeEntity.fields
      .filter((f) => !f.primaryKey && f.name !== "id" && f.name !== "created_at" && f.name !== "updated_at")
      .map(
        (f) =>
          `<div class="space-y-2">
  <label class="text-sm font-medium">${f.name.charAt(0).toUpperCase() + f.name.slice(1).replace(/_/g, " ")}</label>
  <input type="${f.type === "integer" ? "number" : f.type === "boolean" ? "checkbox" : "text"}" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter ${f.name.replace(/_/g, " ")}" data-bind="state:form.${f.name}" data-entity="${activeEntity.name}" data-field="${f.name}" />
</div>`,
      )
      .join("\n");

    const formHtml = `<form class="space-y-4 p-4 border rounded-lg" data-component="Form" data-bind="state:form" data-entity="${activeEntity.name}" data-action="mutate" data-action-source="create${activeEntity.name}">
${fields}
<button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium w-full" data-action="mutate" data-action-source="create${activeEntity.name}">Create ${activeEntity.name}</button>
</form>`;

    editor.addComponents(formHtml);
  }, [editor, activeEntity]);

  // Insert a pre-built data table for the entity
  const insertTable = useCallback(() => {
    if (!editor || !activeEntity) return;
    const headers = activeEntity.fields
      .filter((f) => f.name !== "created_at" && f.name !== "updated_at")
      .slice(0, 6)
      .map((f) => `<th class="text-left p-2 text-sm font-medium text-muted-foreground">${f.name.charAt(0).toUpperCase() + f.name.slice(1).replace(/_/g, " ")}</th>`)
      .join("\n");

    const cells = activeEntity.fields
      .filter((f) => f.name !== "created_at" && f.name !== "updated_at")
      .slice(0, 6)
      .map((f) => `<td class="p-2 text-sm" data-field="${f.name}">{{${f.name}}}</td>`)
      .join("\n");

    const tableHtml = `<div class="w-full border rounded-lg" data-component="DataTable" data-source="${activeEntity.name.toLowerCase()}s" data-entity="${activeEntity.name}">
<table class="w-full border-collapse">
<thead><tr class="border-b">${headers}</tr></thead>
<tbody><tr class="border-b hover:bg-muted/50" data-repeat="${activeEntity.name.toLowerCase()}s">${cells}</tr></tbody>
</table>
</div>`;

    editor.addComponents(tableHtml);
  }, [editor, activeEntity]);

  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground">Loading entities...</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
          <Database className="h-4 w-4" /> Data Entities
        </h3>

        <select
          className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
          value={selectedEntity}
          onChange={(e) => setSelectedEntity(e.target.value)}
        >
          <option value="">Select entity...</option>
          {entities.map((e) => (
            <option key={e.name} value={e.name}>
              {e.name} {e.table ? `(${e.table})` : ""}
            </option>
          ))}
        </select>
      </div>

      {activeEntity && (
        <>
          {/* Quick actions */}
          <div className="flex gap-2">
            <button
              onClick={insertForm}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium hover:bg-muted"
            >
              <Plus className="h-3 w-3" /> Form
            </button>
            <button
              onClick={insertTable}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium hover:bg-muted"
            >
              <Table2 className="h-3 w-3" /> Table
            </button>
          </div>

          {/* Field list */}
          <div>
            <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Fields
            </h4>
            <div className="space-y-1">
              {activeEntity.fields.map((field) => (
                <div
                  key={field.name}
                  className="flex items-center justify-between rounded-md px-2 py-1.5 hover:bg-muted group"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-xs font-mono bg-muted px-1 rounded">
                      {field.type.slice(0, 4)}
                    </span>
                    <span className="text-sm truncate">{field.name}</span>
                    {field.primaryKey && (
                      <span className="text-[10px] text-muted-foreground">PK</span>
                    )}
                  </div>
                  {selected && (
                    <button
                      onClick={() => bindField(field.name, "bind")}
                      className="opacity-0 group-hover:opacity-100 text-xs text-primary hover:underline"
                      title={`Bind ${field.name} to selected element`}
                    >
                      <Link2 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {!selected && (
            <p className="text-xs text-muted-foreground italic">
              Select an element in the canvas to bind fields
            </p>
          )}
        </>
      )}

      {entities.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No entities found. Generate the app first to create data models.
        </p>
      )}
    </div>
  );
}
