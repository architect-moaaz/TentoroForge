export function ScalarTokenEditor({ name, value, onChange }: { name: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
      <span style={{ fontSize: 12, fontFamily: "monospace", flex: 1 }}>{name}</span>
      <input
        aria-label={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 120, fontFamily: "monospace", fontSize: 12, padding: "2px 4px", border: "1px solid #e5e7eb", borderRadius: 2 }}
      />
    </div>
  );
}
