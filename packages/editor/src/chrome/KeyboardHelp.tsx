const SHORTCUTS: [string, string][] = [
  ["Cmd+S", "Save"],
  ["Cmd+Z", "Undo"],
  ["Cmd+Shift+Z", "Redo"],
  ["Cmd+P", "Page switcher"],
  ["Cmd+D", "Toggle diff"],
  ["Cmd+T", "Toggle theme"],
  ["Cmd+I", "Toggle AI sidebar"],
  ["Cmd+C / X / V", "Copy / Cut / Paste"],
  ["Delete / Backspace", "Delete selection"],
  ["Shift+Click", "Add to selection"],
  ["?", "Show this help"],
];

export function KeyboardHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-label="Keyboard shortcuts"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 3000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: 24,
          width: 480,
          maxWidth: "90vw",
          boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
        }}
      >
        <h3 style={{ margin: "0 0 16px", fontSize: 16 }}>Keyboard shortcuts</h3>
        <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
          <tbody>
            {SHORTCUTS.map(([key, desc]) => (
              <tr key={key}>
                <td style={{ padding: "4px 12px 4px 0", width: "45%" }}>
                  <kbd style={{ fontFamily: "monospace", background: "#f3f4f6", padding: "2px 6px", borderRadius: 3, border: "1px solid #e5e7eb" }}>
                    {key}
                  </kbd>
                </td>
                <td style={{ padding: "4px 0", color: "#374151" }}>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p style={{ margin: "16px 0 0", fontSize: 12, color: "#9ca3af", textAlign: "center" }}>
          Press <kbd>Esc</kbd> or click outside to close
        </p>
      </div>
    </div>
  );
}
