/**
 * Shared handle for the component being dragged from the palette.
 *
 * The HTML5 drag data (`dataTransfer.getData`) is only readable on `drop`, not
 * during `dragover`, so the drop indicator can't know the dragged component
 * type from the event. The palette stashes it here on dragstart (and clears on
 * dragend) so the canvas's `onDragOver` can resolve the true accepting target.
 */
let dragging: string | null = null;

export function setDraggingComponent(name: string | null): void {
  dragging = name;
}

export function getDraggingComponent(): string | null {
  return dragging;
}
