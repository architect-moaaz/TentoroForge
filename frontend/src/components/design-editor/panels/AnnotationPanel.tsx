"use client";

/**
 * Annotation Panel — displays and edits data-* attributes of the
 * selected element in the GrapeJS editor.
 */

import { useEffect, useState } from "react";
import type { Editor, Component as GjsComponent } from "grapesjs";

interface AnnotationPanelProps {
  editor: Editor | null;
}

interface AnnotationData {
  slot?: string;
  entity?: string;
  source?: string;
  bind?: string;
  action?: string;
  actionTo?: string;
  actionSource?: string;
  repeat?: string;
  visible?: string;
  component?: string;
  modalId?: string;
}

export function AnnotationPanel({ editor }: AnnotationPanelProps) {
  const [selected, setSelected] = useState<GjsComponent | null>(null);
  const [annotations, setAnnotations] = useState<AnnotationData>({});

  useEffect(() => {
    if (!editor) return;

    const onSelect = (component: GjsComponent) => {
      setSelected(component);
      setAnnotations(extractAnnotations(component));
    };

    const onDeselect = () => {
      setSelected(null);
      setAnnotations({});
    };

    editor.on("component:selected", onSelect);
    editor.on("component:deselected", onDeselect);

    return () => {
      editor.off("component:selected", onSelect);
      editor.off("component:deselected", onDeselect);
    };
  }, [editor]);

  const updateAnnotation = (attr: string, value: string) => {
    if (!selected) return;
    if (value) {
      selected.addAttributes({ [attr]: value });
    } else {
      selected.removeAttributes([attr]);
    }
    setAnnotations(extractAnnotations(selected));
  };

  if (!selected) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Select an element to edit its annotations
      </div>
    );
  }

  const tag = selected.get("tagName") || "div";
  const classes = selected.getClasses().join(" ");

  return (
    <div className="p-4 space-y-4">
      <div>
        <h3 className="text-sm font-semibold mb-2">Element</h3>
        <p className="text-xs text-muted-foreground">
          &lt;{tag}&gt; {classes && <span className="font-mono">.{classes.split(" ")[0]}</span>}
        </p>
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-semibold">Annotations</h3>

        <AnnotationField
          label="Slot Type"
          attr="data-slot"
          value={annotations.slot}
          onChange={updateAnnotation}
          type="select"
          options={["", "entity-table", "entity-form", "entity-detail", "stat-cards", "crud-actions", "auth-form", "search-bar", "recent-items", "empty-state"]}
        />

        <AnnotationField
          label="Entity"
          attr="data-entity"
          value={annotations.entity}
          onChange={updateAnnotation}
        />

        <AnnotationField
          label="Data Source"
          attr="data-source"
          value={annotations.source}
          onChange={updateAnnotation}
        />

        <AnnotationField
          label="State Binding"
          attr="data-bind"
          value={annotations.bind}
          onChange={updateAnnotation}
          placeholder="state:fieldName"
        />

        <AnnotationField
          label="Action"
          attr="data-action"
          value={annotations.action}
          onChange={updateAnnotation}
          type="select"
          options={["", "navigate", "mutate", "setState", "openModal", "closeModal", "toast"]}
        />

        {annotations.action === "navigate" && (
          <AnnotationField
            label="Navigate To"
            attr="data-action-to"
            value={annotations.actionTo}
            onChange={updateAnnotation}
            placeholder="/path"
          />
        )}

        {annotations.action === "mutate" && (
          <AnnotationField
            label="Mutation Source"
            attr="data-action-source"
            value={annotations.actionSource}
            onChange={updateAnnotation}
          />
        )}

        <AnnotationField
          label="Repeat"
          attr="data-repeat"
          value={annotations.repeat}
          onChange={updateAnnotation}
          placeholder="dataSourceName"
        />

        <AnnotationField
          label="Visible When"
          attr="data-visible"
          value={annotations.visible}
          onChange={updateAnnotation}
          placeholder="state:condition"
        />

        <AnnotationField
          label="Component"
          attr="data-component"
          value={annotations.component}
          onChange={updateAnnotation}
          type="select"
          options={["", "Stack", "Row", "Grid", "DataTable", "Form", "Card", "Tabs", "Accordion", "Chart", "StatCard", "EmptyState"]}
        />

        <AnnotationField
          label="Modal ID"
          attr="data-modal-id"
          value={annotations.modalId}
          onChange={updateAnnotation}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field component
// ---------------------------------------------------------------------------

interface AnnotationFieldProps {
  label: string;
  attr: string;
  value?: string;
  onChange: (attr: string, value: string) => void;
  placeholder?: string;
  type?: "text" | "select";
  options?: string[];
}

function AnnotationField({ label, attr, value, onChange, placeholder, type = "text", options }: AnnotationFieldProps) {
  if (type === "select" && options) {
    return (
      <div>
        <label className="text-xs text-muted-foreground">{label}</label>
        <select
          className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
          value={value || ""}
          onChange={(e) => onChange(attr, e.target.value)}
        >
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt || "(none)"}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div>
      <label className="text-xs text-muted-foreground">{label}</label>
      <input
        type="text"
        className="mt-1 w-full rounded-md border border-input bg-background px-2 py-1 text-sm"
        value={value || ""}
        placeholder={placeholder}
        onChange={(e) => onChange(attr, e.target.value)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function extractAnnotations(component: GjsComponent): AnnotationData {
  const attrs = component.getAttributes();
  return {
    slot: attrs["data-slot"],
    entity: attrs["data-entity"],
    source: attrs["data-source"],
    bind: attrs["data-bind"],
    action: attrs["data-action"],
    actionTo: attrs["data-action-to"],
    actionSource: attrs["data-action-source"],
    repeat: attrs["data-repeat"],
    visible: attrs["data-visible"],
    component: attrs["data-component"],
    modalId: attrs["data-modal-id"],
  };
}
