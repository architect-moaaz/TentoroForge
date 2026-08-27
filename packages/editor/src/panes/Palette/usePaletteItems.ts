import type { Registry } from "@tentoroforge/library";

export function usePaletteItems(registry: Registry) {
  const items = registry.list();
  const grouped: Record<string, typeof items> = {};
  for (const item of items) {
    const cat = item.category;
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(item);
  }
  return grouped;
}
