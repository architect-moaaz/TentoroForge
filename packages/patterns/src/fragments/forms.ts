/**
 * Form pattern fragments — generate IR for create/edit forms.
 */

import type { IRNode, FormFieldDef } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { inferInputType, inferTextInputType, toLabel, pluralize, slugify } from "../field-analysis.js";

// ---------------------------------------------------------------------------
// Modal Form
// ---------------------------------------------------------------------------

export function modalFormRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(pluralize(entity.name));
  return formBody(entity, config, slug, "single-column");
}

// ---------------------------------------------------------------------------
// Page Form
// ---------------------------------------------------------------------------

export function pageFormRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(pluralize(entity.name));

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    align: "center",
    children: [
      {
        node: "Stack",
        width: "640px",
        gap: "lg",
        children: [
          {
            node: "Row",
            justify: "between",
            align: "center",
            children: [
              { node: "Text", content: `Create ${entity.name}`, typography: "heading-2" as const } as IRNode,
              { node: "Text", content: "Fill in the details below", typography: "body-sm" as const } as IRNode,
            ],
          } as IRNode,
          formBody(entity, config, slug, "single-column"),
        ],
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Sectioned Form
// ---------------------------------------------------------------------------

export function sectionedFormRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(pluralize(entity.name));

  if (!config.fieldGroups || config.fieldGroups.length === 0) {
    return pageFormRoot(entity, config);
  }

  const sections = config.fieldGroups.map((group) => ({
    title: group.title,
    fields: group.fields.map((f) => buildFormField(f)),
  }));

  return {
    node: "Stack",
    gap: "lg",
    padding: "lg",
    align: "center",
    children: [
      {
        node: "Stack",
        width: "640px",
        gap: "lg",
        children: [
          { node: "Text", content: `Create ${entity.name}`, typography: "heading-2" as const } as IRNode,
          {
            node: "Form",
            bind: "state:form",
            onSubmit: {
              type: "sequence" as const,
              steps: [
                { type: "mutate" as const, source: `create${entity.name}` },
                { type: "toast" as const, variant: "success" as const, message: `${entity.name} created!` },
                { type: "navigate" as const, to: `/${slug}` },
              ],
            },
            layout: "sectioned" as const,
            sections,
            actions: [formActions(slug)],
          } as IRNode,
        ],
      } as IRNode,
    ],
  };
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function formBody(entity: EntitySpec, config: PatternConfig, slug: string, layout: string): IRNode {
  const fields = entity.fields
    .filter((f) => f.name !== "id" && f.name !== "createdAt" && f.name !== "updatedAt")
    .map((f) => buildFormField(f));

  return {
    node: "Form",
    bind: "state:form",
    onSubmit: {
      type: "sequence" as const,
      steps: [
        { type: "mutate" as const, source: `create${entity.name}` },
        { type: "toast" as const, variant: "success" as const, message: `${entity.name} created!` },
        { type: "navigate" as const, to: `/${slug}` },
      ],
    },
    layout: layout as any,
    fields,
    actions: [formActions(slug)],
  } as IRNode;
}

function buildFormField(field: any): FormFieldDef {
  const inputType = inferInputType(field);
  const result: FormFieldDef = {
    field: field.name,
    label: field.label || toLabel(field.name),
    required: field.required,
    node: inputType,
  };

  // Add type-specific props
  if (inputType === "TextInput") {
    (result as any).type = inferTextInputType(field);
    if (field.placeholder) (result as any).placeholder = field.placeholder;
  }
  if (inputType === "TextArea") {
    (result as any).rows = 4;
  }
  if (inputType === "RadioGroup" && field.values) {
    (result as any).options = field.values.map((v: string) => ({ value: v, label: toLabel(v) }));
    (result as any).direction = "row";
  }
  if (inputType === "Select" && field.values) {
    (result as any).options = field.values.map((v: string) => ({ value: v, label: toLabel(v) }));
  }
  if (inputType === "Select" && field.type === "relation" && field.relationTo) {
    (result as any).options = {
      source: slugify(pluralize(field.relationTo)),
      value: "id",
      label: "name",
    };
    (result as any).searchable = true;
  }
  if (inputType === "DatePicker" && field.name.toLowerCase().includes("due")) {
    (result as any).min = "{{today}}";
  }

  // Validation
  if (field.required) {
    result.validation = [{ rule: "required" as const }];
  }
  if (field.maxLength) {
    result.validation = [...(result.validation || []), { rule: "maxLength" as const, value: field.maxLength }];
  }

  return result;
}

function formActions(slug: string): IRNode {
  return {
    node: "Row",
    justify: "end",
    gap: "sm",
    children: [
      {
        node: "Button",
        label: "Cancel",
        variant: "ghost",
        action: { type: "navigate" as const, to: `/${slug}` },
      } as IRNode,
      {
        node: "Button",
        label: "Create",
        variant: "primary",
        icon: "plus",
        submit: true,
      } as IRNode,
    ],
  } as IRNode;
}
