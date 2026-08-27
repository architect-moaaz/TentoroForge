import type { Registry } from "@tentoroforge/library";
import { usePaletteItems } from "./usePaletteItems";
import { PaletteItem } from "./PaletteItem";

/** Special Slot entry injected into palette when in layout-editing mode. */
const SLOT_ITEM = { name: "Slot", category: "Layout" };

const CATEGORY_ORDER = [
  "layout", "interactive", "form", "static",
  "data", "feedback", "navigation", "motion", "custom",
];

function categoryRank(category: string): number {
  const idx = CATEGORY_ORDER.indexOf(category.toLowerCase());
  return idx === -1 ? CATEGORY_ORDER.length : idx;
}

/**
 * Component palette — same chrome as the WorkflowEditor's NodePalette:
 * 240px wide, single-toned bg-muted/20 column, plain bordered category
 * headers, gradient-tile rows with title + description.
 */
export function Palette({
  registry,
  layoutMode = false,
}: {
  registry: Registry;
  layoutMode?: boolean;
}) {
  const grouped = usePaletteItems(registry);

  const groups: Record<string, Array<{ name: string; category: string }>> = layoutMode
    ? { Layout: [SLOT_ITEM], ...grouped }
    : { ...grouped };

  const orderedEntries = Object.entries(groups).sort(
    ([a], [b]) => categoryRank(a) - categoryRank(b)
  );

  // Header + scroll wrapper are rendered by the parent (Editor.tsx) so the
  // column chrome matches the Pages header and is collapsible from there.
  return (
    <div className="flex flex-col">
      {orderedEntries.map(([category, items]) => (
        <div key={category}>
          <div className="border-b border-gray-100 px-4 py-2">
            <span
              data-testid="palette-category-heading"
              className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground"
            >
              {category}
            </span>
          </div>
          {items.map((it: { name: string }) => (
            <PaletteItem key={it.name} libraryName={it.name} />
          ))}
        </div>
      ))}
    </div>
  );
}
