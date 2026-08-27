/**
 * Wizard pattern — multi-step form with progress indicator.
 */

import type { IRNode, FormFieldDef } from "@tentoroforge/ir";
import type { EntitySpec, PatternConfig } from "../types.js";
import { groupFieldsByAffinity, inferInputType, inferTextInputType, toLabel, pluralize, slugify } from "../field-analysis.js";

export function wizardRoot(entity: EntitySpec, config: PatternConfig): IRNode {
  const slug = slugify(pluralize(entity.name));
  const groups = config.fieldGroups || groupFieldsByAffinity(entity);

  // Build step tabs
  const tabs = groups.map((group, i) => ({
    id: `step-${i}`,
    label: group.title,
    content: {
      node: "Stack",
      gap: "md",
      children: group.fields.map((field) => {
        const inputType = inferInputType(field);
        const fieldDef: Record<string, unknown> = {
          node: inputType,
          bind: `state:form.${field.name}`,
          label: field.label || toLabel(field.name),
        };
        if (inputType === "TextInput") {
          fieldDef.type = inferTextInputType(field);
        }
        if (inputType === "TextArea") {
          fieldDef.rows = 4;
        }
        if (inputType === "Select" && field.values) {
          fieldDef.options = field.values.map((v: string) => ({ value: v, label: toLabel(v) }));
        }
        if (inputType === "RadioGroup" && field.values) {
          fieldDef.options = field.values.map((v: string) => ({ value: v, label: toLabel(v) }));
          fieldDef.direction = "row";
        }
        return fieldDef as unknown as IRNode;
      }),
    } as IRNode,
  }));

  // Add review step
  tabs.push({
    id: "review",
    label: "Review",
    content: {
      node: "Stack",
      gap: "md",
      children: [
        { node: "Text", content: "Review your information", typography: "heading-3" as const } as IRNode,
        { node: "Text", content: "Please confirm the details below before submitting.", typography: "body-sm" as const } as IRNode,
        {
          node: "Card",
          padding: "md",
          children: groups.flatMap((group) =>
            group.fields.map((field) => ({
              node: "Row",
              justify: "between",
              padding: { y: "xs" as const },
              children: [
                { node: "Text", content: field.label || toLabel(field.name), typography: "caption" as const } as IRNode,
                { node: "Text", content: `{{state:form.${field.name}}}` } as IRNode,
              ],
            } as IRNode)),
          ),
        } as IRNode,
      ],
    } as IRNode,
  });

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
            node: "Tabs",
            defaultTab: "step-0",
            variant: "enclosed" as const,
            tabs,
          } as IRNode,
          {
            node: "Row",
            justify: "between",
            children: [
              { node: "Button", label: "Cancel", variant: "ghost", action: { type: "navigate" as const, to: `/${slug}` } } as IRNode,
              {
                node: "Button",
                label: "Submit",
                variant: "primary",
                action: {
                  type: "sequence" as const,
                  steps: [
                    { type: "mutate" as const, source: `create${entity.name}` },
                    { type: "toast" as const, variant: "success" as const, message: `${entity.name} created!` },
                    { type: "navigate" as const, to: `/${slug}` },
                  ],
                },
              } as IRNode,
            ],
          } as IRNode,
        ],
      } as IRNode,
    ],
  };
}
