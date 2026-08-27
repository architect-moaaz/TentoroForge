import type { DataEditorAction } from "@/types/app-model";
import type { SmartFieldConfig } from "@/types/ai-features";

/**
 * Converts a visual data editor action into a natural language instruction
 * that the code_editor agent can execute.
 */
export function buildDataInstruction(action: DataEditorAction): string {
  switch (action.type) {
    case "add_model": {
      const fields = action.fields
        .map((f) => {
          const parts = [`"${f.name}" of type ${f.type}`];
          if (f.primaryKey) parts.push("(primary key)");
          if (f.nullable) parts.push("(nullable)");
          if (f.unique) parts.push("(unique)");
          return parts.join(" ");
        })
        .join(", ");
      return `Add a new Drizzle database model/table called "${action.name}" to the schema file (src/db/schema.ts). It should have the following columns: ${fields}. Also create the corresponding TypeScript types and any needed API routes for CRUD operations on this model.`;
    }

    case "delete_model":
      return `Remove the "${action.name}" database model/table from the Drizzle schema file (src/db/schema.ts). Also remove any related API routes, page references, and components that reference this model. Clean up any foreign key references from other tables that point to "${action.name}".`;

    case "add_field": {
      const f = action.field;
      const parts = [`Add a new column "${f.name}" of type ${f.type} to the "${action.table}" table in the Drizzle schema (src/db/schema.ts).`];
      if (f.nullable) parts.push("Make it nullable.");
      if (f.unique) parts.push("Add a unique constraint.");
      if (f.default) parts.push(`Set default value to ${f.default}.`);
      if (f.references) {
        parts.push(
          `Add a foreign key reference to "${f.references.table}"."${f.references.column}".`,
        );
      }
      if (f.smart) {
        parts.push(buildSmartFieldInstruction(f.name, f.smart, action.table));
      }
      parts.push(
        "Update any TypeScript types, API routes, and components that use this table to include the new field.",
      );
      return parts.join(" ");
    }

    case "edit_field": {
      const f = action.field;
      const changes: string[] = [];
      if (f.name !== action.oldName) changes.push(`rename to "${f.name}"`);
      changes.push(`type: ${f.type}`);
      if (f.nullable !== undefined) changes.push(f.nullable ? "nullable" : "not nullable");
      if (f.unique !== undefined) changes.push(f.unique ? "unique" : "not unique");
      if (f.default !== undefined) changes.push(`default: ${f.default}`);
      let smartPart = "";
      if (f.smart) {
        smartPart = " " + buildSmartFieldInstruction(f.name, f.smart, action.table);
      }
      return `Modify the "${action.oldName}" column in the "${action.table}" table in the Drizzle schema (src/db/schema.ts). Apply these changes: ${changes.join(", ")}. Update any TypeScript types and references accordingly.${smartPart}`;
    }

    case "delete_field":
      return `Remove the "${action.fieldName}" column from the "${action.table}" table in the Drizzle schema (src/db/schema.ts). Update any TypeScript types, API routes, and components that reference this field.`;

    case "add_relation": {
      const fk = action.foreignKey || `${action.target.toLowerCase()}_id`;
      return `Add a ${action.relationType} relationship from "${action.source}" to "${action.target}" in the Drizzle schema (src/db/schema.ts). Add a foreign key column "${fk}" to the "${action.source}" table referencing "${action.target}".id. Set up the Drizzle relations() configuration for both tables.`;
    }

    case "delete_relation":
      return `Remove the relationship between "${action.source}" and "${action.target}" by removing the foreign key column "${action.foreignKey}" from "${action.source}" in the Drizzle schema (src/db/schema.ts). Clean up the relations() configuration for both tables.`;

    case "add_enum":
      return `Create a new PostgreSQL enum type called "${action.name}" in the Drizzle schema (src/db/schema.ts) with values: ${action.values.map((v) => `"${v}"`).join(", ")}. Use pgEnum() from drizzle-orm/pg-core.`;

    case "edit_enum":
      return `Update the "${action.name}" enum in the Drizzle schema (src/db/schema.ts) to have these values: ${action.values.map((v) => `"${v}"`).join(", ")}. Update any columns that use this enum type.`;

    case "add_index": {
      const cols = action.columns.map((c) => `"${c}"`).join(", ");
      const uniqueStr = action.unique ? "unique " : "";
      return `Add a ${uniqueStr}index on columns ${cols} to the "${action.table}" table in the Drizzle schema (src/db/schema.ts).`;
    }

    default:
      return `Apply data model change: ${JSON.stringify(action)}`;
  }
}

function buildSmartFieldInstruction(
  fieldName: string,
  config: SmartFieldConfig,
  tableName: string,
): string {
  const parts: string[] = [];
  parts.push(`This field "${fieldName}" is a Smart Field (AI-powered) of type "${config.type}".`);

  const source = Array.isArray(config.source)
    ? config.source.join(", ")
    : config.source;
  if (source) parts.push(`Source field(s): ${source}.`);

  parts.push(`Trigger: ${config.trigger}.`);
  parts.push(`Model: ${config.model || "claude-haiku-4-5-20251001"}.`);

  switch (config.type) {
    case "ai_classify":
    case "ai_classify_multi":
      if (config.labels?.length) {
        parts.push(`Classification labels: [${config.labels.join(", ")}].`);
      }
      break;
    case "ai_summarize":
      if (config.maxLength) parts.push(`Max length: ${config.maxLength} characters.`);
      break;
    case "ai_extract":
      if (config.fields?.length) {
        parts.push(`Extract fields: [${config.fields.join(", ")}].`);
      }
      break;
    case "ai_translate":
      if (config.targetLanguage) parts.push(`Target language: ${config.targetLanguage}.`);
      break;
  }

  if (config.prompt) parts.push(`Custom prompt: "${config.prompt}".`);

  parts.push(
    `Implement this as an async smart field computation in the ${tableName} service: after record creation/update, call the LLM to compute this field value and update the record. Use the Anthropic SDK (claude-haiku for classification/extraction, claude-sonnet for generation). The field should show a sparkle indicator in the UI.`,
  );

  return parts.join(" ");
}
