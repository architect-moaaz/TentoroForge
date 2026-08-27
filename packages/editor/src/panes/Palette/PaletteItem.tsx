import { useDraggable } from "../../dnd/useDraggable";
import { metaFor } from "./paletteMeta";

/**
 * Palette card — exactly matches the WorkflowEditor's NodePalette item
 * chrome: gradient h-9/w-9 icon tile, white 16×16 icon, text-sm title +
 * truncated text-xs description, muted-row hover.
 */
export function PaletteItem({ libraryName }: { libraryName: string }) {
  const { setNodeRef, attributes, listeners, isDragging } = useDraggable({
    id: `palette:${libraryName}`,
    data: { kind: "palette", libraryName },
  });
  const { icon: Icon, description, gradient } = metaFor(libraryName);
  return (
    <div
      ref={setNodeRef}
      {...attributes}
      {...listeners}
      data-palette-item={libraryName}
      className={
        "flex cursor-grab items-center gap-3 px-3 py-2.5 hover:bg-muted/50 active:cursor-grabbing select-none " +
        (isDragging ? "opacity-50" : "")
      }
    >
      <div
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ${gradient}`}
        aria-hidden="true"
      >
        <Icon className="h-4 w-4 text-white" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium text-slate-800">{libraryName}</div>
        <div className="truncate text-xs text-muted-foreground">{description}</div>
      </div>
    </div>
  );
}
