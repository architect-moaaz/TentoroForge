"use client";
import * as React from "react";

/**
 * The raw-JSON textarea, lifted out of JsonControl so BOTH the JSON control and
 * the repeating-row editor's "edit as JSON" escape hatch can use it without the
 * two importing each other (index.tsx -> RowsControl -> JsonControl -> RowsControl
 * is a module cycle; a shared leaf module is not).
 *
 * WHY commit-on-blur and parse-or-refuse: the value is dispatched into the
 * schema, and editor-store pushes one undo entry per dispatch. Committing per
 * keystroke would push an undo entry for every character AND write each
 * half-typed fragment (`{"ty`) into the schema as a real prop value. The draft
 * lives locally, is validated on blur, and only a parseable value reaches the
 * store; an unparseable one is shown as an error and left uncommitted.
 */
export function RawJsonEditor({
  label, value, onChange, rows = 4, placeholder,
}: {
  label: string;
  value: unknown;
  onChange: (v: unknown) => void;
  rows?: number;
  placeholder?: string;
}) {
  const committed = React.useMemo(
    () => (value === undefined || value === null ? "" : JSON.stringify(value, null, 2)),
    [value],
  );
  const [draft, setDraft] = React.useState(committed);
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    setDraft(committed);
    setError(null);
  }, [committed]);

  const commit = () => {
    if (draft === committed) return;
    const t = draft.trim();
    if (t === "") {
      setError(null);
      onChange(undefined);
      return;
    }
    try {
      const parsed = JSON.parse(t);
      setError(null);
      onChange(parsed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Invalid JSON");
    }
  };

  return (
    <>
      <textarea
        rows={rows}
        aria-label={`${label} JSON`}
        className="border rounded px-2 py-1 text-xs bg-background font-mono"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setDraft(committed);
            setError(null);
            (e.target as HTMLTextAreaElement).blur();
          }
        }}
        placeholder={placeholder ?? '{"type": "SideNav", "props": {}}'}
      />
      {error && (
        <span role="alert" className="text-[11px] text-destructive">
          Not saved — {error}
        </span>
      )}
    </>
  );
}
