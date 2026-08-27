import type { DataBinding, PageDefinition } from "@/types/ui-editor";

interface ExtractedFormField {
  fieldName: string;
  type?: string;
  required?: boolean;
  processVariable?: string;
  helpText?: string;
  minLength?: string;
  maxLength?: string;
  min?: string;
  max?: string;
  pattern?: string;
  options?: string;
}

/**
 * Extract form field metadata from data-* attributes in GrapesJS HTML.
 */
function extractFormFields(html: string): ExtractedFormField[] {
  const fields: ExtractedFormField[] = [];
  const tagPattern = /(<[^>]*data-field-name=["'][^"']*["'][^>]*>)/gi;

  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(html)) !== null) {
    const tag = match[1];
    const nameMatch = /data-field-name=["']([^"']*)["']/i.exec(tag);
    if (!nameMatch) continue;

    const field: ExtractedFormField = { fieldName: nameMatch[1] };

    const attrMap: [string, keyof ExtractedFormField][] = [
      ["data-required", "required"],
      ["data-process-variable", "processVariable"],
      ["data-help-text", "helpText"],
      ["data-min-length", "minLength"],
      ["data-max-length", "maxLength"],
      ["data-min", "min"],
      ["data-max", "max"],
      ["data-pattern", "pattern"],
      ["data-options", "options"],
    ];

    for (const [attr, key] of attrMap) {
      const attrMatch = new RegExp(`${attr}=["']([^"']*)["']`, "i").exec(tag);
      if (attrMatch) {
        if (key === "required") {
          field.required = ["true", "1", "on"].includes(
            attrMatch[1].toLowerCase(),
          );
        } else {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (field as any)[key] = attrMatch[1];
        }
      }
    }

    // Detect input type
    const typeMatch = /type=["']([^"']*)["']/i.exec(tag);
    if (typeMatch) {
      field.type = typeMatch[1];
    } else if (/<textarea/i.test(tag)) {
      field.type = "textarea";
    } else if (/<select/i.test(tag)) {
      field.type = "select";
    }

    if (field.fieldName) fields.push(field);
  }

  return fields;
}

/**
 * Converts a page definition (from GrapesJS) into a natural language instruction
 * for the code_editor agent to implement in the generated application.
 */
export function buildUIInstruction(page: PageDefinition): string {
  const parts: string[] = [
    `Create or update the page component for route "${page.route}" (page name: "${page.name}").`,
    "",
  ];

  // HTML structure
  if (page.html) {
    parts.push("## Page HTML Structure");
    parts.push("Convert the following HTML to a React component using Tailwind CSS:");
    parts.push("```html");
    parts.push(page.html);
    parts.push("```");
    parts.push("");
  }

  // Custom CSS
  if (page.css) {
    parts.push("## Additional CSS");
    parts.push("Apply these custom styles (convert to Tailwind where possible):");
    parts.push("```css");
    parts.push(page.css);
    parts.push("```");
    parts.push("");
  }

  // Data bindings
  if (page.dataBindings && page.dataBindings.length > 0) {
    parts.push("## Data Bindings");
    for (const binding of page.dataBindings) {
      parts.push(bindingToText(binding));
    }
    parts.push("");
  }

  // ── Form Fields (extracted from data-* traits) ────────────────────
  const formFields = page.html ? extractFormFields(page.html) : [];
  if (formFields.length > 0) {
    parts.push("## Form Fields");
    parts.push(
      "The following form fields were detected in the HTML via data-* attributes.",
    );
    parts.push("Generate proper form handling for each field:");
    parts.push("");
    for (const f of formFields) {
      let desc = `- **${f.fieldName}**`;
      if (f.type) desc += ` (type: ${f.type})`;
      parts.push(desc);
      if (f.required) parts.push("  - Required: yes");
      if (f.processVariable)
        parts.push(`  - Process variable: \`${f.processVariable}\``);
      if (f.helpText) parts.push(`  - Help text: ${f.helpText}`);
      if (f.minLength) parts.push(`  - Min length: ${f.minLength}`);
      if (f.maxLength) parts.push(`  - Max length: ${f.maxLength}`);
      if (f.min) parts.push(`  - Min value: ${f.min}`);
      if (f.max) parts.push(`  - Max value: ${f.max}`);
      if (f.pattern) parts.push(`  - Validation pattern: \`${f.pattern}\``);
      if (f.options) parts.push(`  - Options: ${f.options}`);
    }
    parts.push("");

    parts.push("### Form Implementation Requirements");
    parts.push("- Use controlled inputs with React state or react-hook-form");
    parts.push(
      "- Add client-side validation based on the field constraints above",
    );
    parts.push(
      "- Fields with a `processVariable` are bound to workflow variables:",
    );
    parts.push(
      "  - Pre-populate from `task.input_data[processVariable]` if the page is opened from a workflow task",
    );
    parts.push(
      "  - On submit, include `{ [processVariable]: value }` in the POST body to `/api/tasks/:id/complete`",
    );
    parts.push("- Required fields must be validated before submission");
    parts.push("");
  }

  // Requirements
  parts.push("## Requirements");
  parts.push("1. Create a React component with proper TypeScript types");
  parts.push("2. Use existing UI components from the project where possible");
  parts.push(
    "3. Make all data tables/lists fetch from the appropriate API endpoints",
  );
  parts.push(
    "4. Add form submission handlers that POST/PUT to the correct API routes",
  );
  parts.push("5. Ensure the page is responsive (mobile, tablet, desktop)");
  parts.push("6. Add the route to the app navigation/routing");

  if (formFields.length > 0) {
    parts.push(
      "7. Implement form validation and submission as described in the Form Fields section above",
    );
  }

  return parts.join("\n");
}

function bindingToText(binding: DataBinding): string {
  switch (binding.bindingType) {
    case "display":
      return `- Display: Show \`${binding.modelName}.${binding.fieldName}\` in component "${binding.componentId}" field "${binding.field}"`;
    case "input":
      return `- Input: Bind input "${binding.componentId}" field "${binding.field}" to \`${binding.modelName}.${binding.fieldName}\``;
    case "list":
      return `- List: Render a list of \`${binding.modelName}\` records, showing \`${binding.fieldName}\` in each item`;
    case "conditional":
      return `- Conditional: Show/hide component "${binding.componentId}" based on \`${binding.modelName}.${binding.fieldName}\``;
    default:
      return `- Bind "${binding.componentId}" to \`${binding.modelName}.${binding.fieldName}\``;
  }
}

/**
 * Build an instruction for applying a specific component change.
 */
export function buildComponentChangeInstruction(
  pageName: string,
  route: string,
  changeDescription: string,
): string {
  return [
    `Update the page "${pageName}" at route "${route}":`,
    "",
    changeDescription,
    "",
    "Ensure the change follows existing patterns and maintains type safety.",
  ].join("\n");
}
