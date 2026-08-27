/**
 * Layout GrapeJS blocks — Stack, Row, Grid containers
 */

import type { Editor } from "grapesjs";

export function registerLayoutBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  bm.add("stack", {
    label: "Stack (Column)",
    category: "Layout",
    content: `<div class="flex flex-col gap-4 p-4" data-component="Stack">
      <p class="text-sm text-muted-foreground">Stack content</p>
    </div>`,
    media: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="2" width="16" height="6" rx="1"/><rect x="4" y="10" width="16" height="6" rx="1"/></svg>',
  });

  bm.add("row", {
    label: "Row",
    category: "Layout",
    content: `<div class="flex flex-row gap-4 items-center" data-component="Row">
      <div class="flex-1 p-2 border rounded">Column 1</div>
      <div class="flex-1 p-2 border rounded">Column 2</div>
    </div>`,
    media: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="8" height="16" rx="1"/><rect x="14" y="4" width="8" height="16" rx="1"/></svg>',
  });

  bm.add("grid-2", {
    label: "Grid (2 cols)",
    category: "Layout",
    content: `<div class="grid grid-cols-2 gap-4" data-component="Grid">
      <div class="p-4 border rounded">Item 1</div>
      <div class="p-4 border rounded">Item 2</div>
      <div class="p-4 border rounded">Item 3</div>
      <div class="p-4 border rounded">Item 4</div>
    </div>`,
    media: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="9" height="9" rx="1"/><rect x="13" y="2" width="9" height="9" rx="1"/><rect x="2" y="13" width="9" height="9" rx="1"/><rect x="13" y="13" width="9" height="9" rx="1"/></svg>',
  });

  bm.add("grid-3", {
    label: "Grid (3 cols)",
    category: "Layout",
    content: `<div class="grid grid-cols-3 gap-4" data-component="Grid">
      <div class="p-4 border rounded">Item 1</div>
      <div class="p-4 border rounded">Item 2</div>
      <div class="p-4 border rounded">Item 3</div>
    </div>`,
    media: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="1" y="4" width="6" height="16" rx="1"/><rect x="9" y="4" width="6" height="16" rx="1"/><rect x="17" y="4" width="6" height="16" rx="1"/></svg>',
  });

  bm.add("spacer", {
    label: "Spacer",
    category: "Layout",
    content: '<div class="h-6"></div>',
  });

  bm.add("divider", {
    label: "Divider",
    category: "Layout",
    content: '<hr class="border-border" />',
  });

  bm.add("section", {
    label: "Section",
    category: "Layout",
    content: `<section class="py-8 px-6">
      <h2 class="text-xl font-semibold mb-4">Section Title</h2>
      <div class="flex flex-col gap-4">
        <p class="text-sm text-muted-foreground">Section content goes here</p>
      </div>
    </section>`,
  });
}
