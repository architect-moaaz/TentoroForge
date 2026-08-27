/**
 * Data-bound GrapeJS blocks — DataTable, Form, Repeater, inputs
 */

import type { Editor } from "grapesjs";

export function registerDataBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  bm.add("data-table", {
    label: "Data Table",
    category: "Data",
    content: `<div class="w-full" data-component="DataTable" data-source="items">
      <table class="w-full border-collapse">
        <thead>
          <tr class="border-b">
            <th class="text-left p-2 text-sm font-medium text-muted-foreground">Name</th>
            <th class="text-left p-2 text-sm font-medium text-muted-foreground">Status</th>
            <th class="text-left p-2 text-sm font-medium text-muted-foreground">Date</th>
          </tr>
        </thead>
        <tbody>
          <tr class="border-b" data-repeat="items">
            <td class="p-2 text-sm" data-field="name">{{name}}</td>
            <td class="p-2 text-sm" data-field="status">{{status}}</td>
            <td class="p-2 text-sm" data-field="createdAt">{{createdAt}}</td>
          </tr>
        </tbody>
      </table>
    </div>`,
  });

  bm.add("form", {
    label: "Form",
    category: "Data",
    content: `<form class="space-y-4" data-component="Form" data-bind="state:form" data-action="mutate" data-action-source="createItem">
      <div class="space-y-2">
        <label class="text-sm font-medium">Name</label>
        <input type="text" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter name" data-bind="state:form.name" />
      </div>
      <div class="space-y-2">
        <label class="text-sm font-medium">Email</label>
        <input type="email" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter email" data-bind="state:form.email" />
      </div>
      <button type="submit" class="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground h-10 px-4 py-2 text-sm font-medium">Submit</button>
    </form>`,
  });

  bm.add("repeater", {
    label: "Repeater",
    category: "Data",
    content: `<div class="flex flex-col gap-4" data-repeat="items" data-repeat-key="id">
      <div class="p-4 border rounded-lg">
        <h4 class="font-medium" data-field="name">{{name}}</h4>
        <p class="text-sm text-muted-foreground" data-field="description">{{description}}</p>
      </div>
    </div>`,
  });

  bm.add("text-input", {
    label: "Text Input",
    category: "Data",
    content: `<div class="space-y-2">
      <label class="text-sm font-medium">Label</label>
      <input type="text" class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter value" data-bind="state:fieldName" />
    </div>`,
  });

  bm.add("textarea", {
    label: "Textarea",
    category: "Data",
    content: `<div class="space-y-2">
      <label class="text-sm font-medium">Label</label>
      <textarea class="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="Enter text" data-bind="state:fieldName" rows="3"></textarea>
    </div>`,
  });

  bm.add("select", {
    label: "Select",
    category: "Data",
    content: `<div class="space-y-2">
      <label class="text-sm font-medium">Label</label>
      <select class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" data-bind="state:fieldName">
        <option value="">Select...</option>
        <option value="option1">Option 1</option>
        <option value="option2">Option 2</option>
      </select>
    </div>`,
  });

  bm.add("checkbox", {
    label: "Checkbox",
    category: "Data",
    content: `<div class="flex items-center gap-2">
      <input type="checkbox" data-bind="state:checked" />
      <label class="text-sm font-medium">Checkbox label</label>
    </div>`,
  });

  bm.add("search-bar", {
    label: "Search Bar",
    category: "Data",
    content: `<div class="relative">
      <input type="text" class="flex h-10 w-full rounded-md border border-input bg-background pl-9 pr-3 py-2 text-sm" placeholder="Search..." data-bind="state:search" />
    </div>`,
  });
}
