/**
 * Slot GrapeJS blocks — PlaceholderSlot blocks for entity-bound areas
 */

import type { Editor } from "grapesjs";

export function registerSlotBlocks(editor: Editor): void {
  const bm = editor.BlockManager;

  bm.add("slot-entity-table", {
    label: "Entity Table Slot",
    category: "Slots",
    content: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="entity-table" data-entity="Entity">
      <span class="text-sm text-muted-foreground">Entity Table Slot</span>
    </div>`,
  });

  bm.add("slot-entity-form", {
    label: "Entity Form Slot",
    category: "Slots",
    content: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="entity-form" data-entity="Entity">
      <span class="text-sm text-muted-foreground">Entity Form Slot</span>
    </div>`,
  });

  bm.add("slot-entity-detail", {
    label: "Entity Detail Slot",
    category: "Slots",
    content: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="entity-detail" data-entity="Entity">
      <span class="text-sm text-muted-foreground">Entity Detail Slot</span>
    </div>`,
  });

  bm.add("slot-stat-cards", {
    label: "Stat Cards Slot",
    category: "Slots",
    content: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="stat-cards" data-entity="Entity">
      <span class="text-sm text-muted-foreground">Stat Cards Slot</span>
    </div>`,
  });

  bm.add("slot-crud-actions", {
    label: "CRUD Actions Slot",
    category: "Slots",
    content: `<div class="min-h-[60px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="crud-actions" data-entity="Entity">
      <span class="text-sm text-muted-foreground">CRUD Actions Slot</span>
    </div>`,
  });

  bm.add("slot-auth-form", {
    label: "Auth Form Slot",
    category: "Slots",
    content: `<div class="min-h-[200px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="auth-form">
      <span class="text-sm text-muted-foreground">Auth Form Slot</span>
    </div>`,
  });

  bm.add("slot-search-bar", {
    label: "Search Bar Slot",
    category: "Slots",
    content: `<div class="min-h-[40px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="search-bar">
      <span class="text-sm text-muted-foreground">Search Bar Slot</span>
    </div>`,
  });

  bm.add("slot-recent-items", {
    label: "Recent Items Slot",
    category: "Slots",
    content: `<div class="min-h-[100px] border-2 border-dashed border-muted-foreground/30 rounded-lg p-4 flex items-center justify-center" data-slot="recent-items" data-entity="Entity">
      <span class="text-sm text-muted-foreground">Recent Items Slot</span>
    </div>`,
  });
}
