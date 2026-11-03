"""A design held as the specification, built as drawn.

Forge used to hand a drawn frame to a page writer to re-author, and the
writer drifted from it however it was held (D3 pilot, 2026-10-28). Here the
drawing is converted, not re-authored:

1. `tsx` turns each frame's Figma node tree into React with the drawn values;
   `shell` lifts out the sidebar and top bar every frame shares and drops the
   prototype's own furniture; `components` makes each component the frames
   repeat into one React component; `params` turns the drawing's example
   content into typed props and its buttons into handlers — the view's
   CONTRACT (`contract`).
2. `flow` writes the journey the design draws, screen by screen, as a
   document the requirements are read from.
3. The data model and the processes are generated to back the contracts
   (`contract.digest` is put in front of those steps).
4. `binder` attaches a page to them: it writes `load.ts` and the page around
   the drawn view, never the view itself.

The pieces are stored in the Blueprint's `drawnViews`.
"""
