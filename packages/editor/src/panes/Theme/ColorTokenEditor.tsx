export function ColorTokenEditor({ name, value, onChange }: { name: string; value: string; onChange: (v: string) => void }) {
  const isHex = /^#[0-9a-fA-F]{6}$/.test(value);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
      <input
        type="color"
        aria-label={`${name} color picker`}
        value={isHex ? value : "#000000"}
        onInput={(e) => onChange((e.target as HTMLInputElement).value)}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 28, height: 24, padding: 0, border: "1px solid #e5e7eb", borderRadius: 2, cursor: "pointer" }}
      />
      <span style={{ fontSize: 12, fontFamily: "monospace", flex: 1 }}>{name}</span>
      <input
        aria-label={name}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 100, fontFamily: "monospace", fontSize: 12, padding: "2px 4px", border: "1px solid #e5e7eb", borderRadius: 2 }}
      />
    </div>
  );
}
