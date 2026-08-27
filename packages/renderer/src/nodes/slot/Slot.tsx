// Used only when a layout was NOT applied via applyLayout.
// Logs a warning for unfilled slots and returns null.
export function Slot({ node }: { node: any }) {
  console.warn(`[renderer] unfilled slot '${node.props.name}'`);
  return null;
}
