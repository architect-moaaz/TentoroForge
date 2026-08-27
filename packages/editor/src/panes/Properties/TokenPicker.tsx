type TokenGroups = Record<string, Record<string, string> | string | Record<string, any>>;

export function TokenPicker({
  groupKey,
  value,
  onChange,
  label,
  tokens,
}: {
  groupKey: string;
  value: string | undefined;
  onChange: (v: string | undefined) => void;
  label: string;
  tokens: TokenGroups;
}) {
  const group = (typeof tokens[groupKey] === "object" && tokens[groupKey] !== null)
    ? (tokens[groupKey] as Record<string, string>)
    : {};
  const options = Object.keys(group);
  return (
    <div style={{ marginBottom: 8 }}>
      <label
        htmlFor={`style-${label}`}
        style={{ display: "block", fontSize: 12, marginBottom: 4 }}
      >
        {label}
      </label>
      <select
        id={`style-${label}`}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        style={{ width: "100%" }}
      >
        <option value="">—</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
    </div>
  );
}
