import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useUrlState } from "../../style/useUrlState";
import type { FilterFieldType } from "./FilterBuilder.schema";

type Clause = { field: string; op: string; value: string };

type Props = {
  fields: FilterFieldType[];
  paramKey?: string;
  combinator?: "AND" | "OR";
  emptyLabel?: string;
  onApplyWorkflow?: string;
  style?: StyleSlotT;
  className?: string;
};

const DEFAULT_OPS: Record<string, string[]> = {
  string:  ["eq", "neq", "contains", "startsWith", "endsWith"],
  number:  ["eq", "neq", "gt", "gte", "lt", "lte"],
  boolean: ["eq"],
  date:    ["eq", "before", "after"],
  enum:    ["eq", "neq"],
};

/**
 * FilterBuilder — a compact chip-list expression builder.
 *
 * Clauses are held in local state and serialised to `?<paramKey>=` on
 * Apply. The serialisation is a compact JSON encoded via URIComponent —
 * enough to survive a page reload without depending on a schema-aware
 * URL grammar. Deserialises on mount so refresh preserves the query.
 */
export function FilterBuilder({
  fields,
  paramKey = "filter",
  combinator: initialCombinator = "AND",
  emptyLabel = "Add a filter…",
  onApplyWorkflow,
  style,
  className,
}: Props): React.ReactElement {
  const styleProps = resolveStyle(style);
  const [encoded, setEncoded] = useUrlState(paramKey, "");
  const [combinator, setCombinator] = React.useState<"AND" | "OR">(initialCombinator);
  const [clauses, setClauses] = React.useState<Clause[]>(() => decode(encoded).clauses);

  React.useEffect(() => {
    const parsed = decode(encoded);
    setCombinator(parsed.combinator || initialCombinator);
    setClauses(parsed.clauses);
    // Intentional: sync on mount + on external URL changes only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [encoded]);

  const fieldByName = React.useMemo(() => {
    const m: Record<string, FilterFieldType> = {};
    for (const f of fields) m[f.name] = f;
    return m;
  }, [fields]);

  const addClause = () => {
    const first = fields[0];
    if (!first) return;
    const ops = first.operators?.length ? first.operators : DEFAULT_OPS[first.type] ?? DEFAULT_OPS.string;
    setClauses((c) => [...c, { field: first.name, op: ops[0], value: "" }]);
  };

  const removeClause = (idx: number) =>
    setClauses((c) => c.filter((_, i) => i !== idx));

  const patchClause = (idx: number, patch: Partial<Clause>) =>
    setClauses((c) => c.map((cl, i) => (i === idx ? { ...cl, ...patch } : cl)));

  const apply = () => {
    const enc = encode({ combinator, clauses });
    setEncoded(enc);
    if (onApplyWorkflow && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("forge:workflow", {
          detail: { workflow: onApplyWorkflow, input: { filter: { combinator, clauses } } },
        }),
      );
    }
  };

  const clear = () => {
    setClauses([]);
    setEncoded("");
  };

  return (
    <div
      data-forge-filter-builder
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--border, hsl(0 0% 90%))",
        borderRadius: "var(--radius-md, 0.5rem)",
        background: "var(--card, white)",
        color: "var(--card-foreground, hsl(0 0% 15%))",
        ...styleProps,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: "0.8125rem", color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
          Combine with
        </span>
        <select
          value={combinator}
          onChange={(e) => setCombinator(e.target.value as "AND" | "OR")}
          aria-label="Combinator"
          style={selectStyle}
        >
          <option value="AND">AND</option>
          <option value="OR">OR</option>
        </select>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={apply} style={primaryBtn} data-forge-filter-apply>
          Apply
        </button>
        <button type="button" onClick={clear} style={ghostBtn}>
          Clear
        </button>
      </div>

      {clauses.length === 0 ? (
        <div
          role="button"
          tabIndex={0}
          onClick={addClause}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && addClause()}
          style={{
            padding: "10px 12px",
            border: "1px dashed var(--border, hsl(0 0% 85%))",
            borderRadius: "var(--radius-sm, 0.25rem)",
            color: "var(--muted-foreground, hsl(0 0% 45%))",
            cursor: "pointer",
            fontSize: "0.875rem",
          }}
        >
          {emptyLabel}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {clauses.map((cl, i) => {
            const f = fieldByName[cl.field] ?? fields[0];
            const ops = f.operators?.length ? f.operators : DEFAULT_OPS[f.type] ?? DEFAULT_OPS.string;
            return (
              <div
                key={i}
                data-forge-filter-clause
                style={{
                  display: "flex",
                  gap: 6,
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >
                <select
                  value={cl.field}
                  onChange={(e) => patchClause(i, { field: e.target.value, op: (fieldByName[e.target.value]?.operators ?? DEFAULT_OPS[fieldByName[e.target.value]?.type ?? "string"] ?? DEFAULT_OPS.string)[0], value: "" })}
                  aria-label="Field"
                  style={selectStyle}
                >
                  {fields.map((ff) => (
                    <option key={ff.name} value={ff.name}>
                      {ff.label ?? ff.name}
                    </option>
                  ))}
                </select>
                <select
                  value={cl.op}
                  onChange={(e) => patchClause(i, { op: e.target.value })}
                  aria-label="Operator"
                  style={selectStyle}
                >
                  {ops.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
                {renderValueControl(f, cl.value, (v) => patchClause(i, { value: v }))}
                <button
                  type="button"
                  onClick={() => removeClause(i)}
                  aria-label="Remove clause"
                  style={{ ...ghostBtn, padding: "4px 8px" }}
                >
                  ✕
                </button>
              </div>
            );
          })}
          <button
            type="button"
            onClick={addClause}
            style={{ ...ghostBtn, alignSelf: "flex-start" }}
          >
            + Add clause
          </button>
        </div>
      )}
    </div>
  );
}

function renderValueControl(
  f: FilterFieldType,
  value: string,
  onChange: (v: string) => void,
): React.ReactElement {
  if (f.type === "boolean") {
    return (
      <select value={value || "true"} onChange={(e) => onChange(e.target.value)} style={selectStyle}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (f.type === "enum") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} style={selectStyle}>
        <option value="">Select…</option>
        {(f.options ?? []).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  }
  const inputType = f.type === "number" ? "number" : f.type === "date" ? "date" : "text";
  return (
    <input
      type={inputType}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Value"
      style={inputStyle}
    />
  );
}

const selectStyle: React.CSSProperties = {
  padding: "4px 8px",
  borderRadius: "var(--radius-sm, 0.25rem)",
  border: "1px solid var(--border, hsl(0 0% 85%))",
  background: "var(--background, white)",
  color: "var(--foreground, hsl(0 0% 15%))",
  fontSize: "0.8125rem",
};

const inputStyle: React.CSSProperties = {
  ...selectStyle,
  minWidth: 140,
};

const primaryBtn: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: "var(--radius-sm, 0.25rem)",
  border: "none",
  background: "var(--primary, hsl(210 60% 45%))",
  color: "var(--primary-foreground, white)",
  cursor: "pointer",
  fontSize: "0.8125rem",
};

const ghostBtn: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: "var(--radius-sm, 0.25rem)",
  border: "1px solid var(--border, hsl(0 0% 85%))",
  background: "transparent",
  color: "var(--foreground, hsl(0 0% 15%))",
  cursor: "pointer",
  fontSize: "0.8125rem",
};

// ─────────────────────────────────────────────────────────────
// Serialisation

export function encode(expr: {
  combinator: "AND" | "OR";
  clauses: Clause[];
}): string {
  if (!expr.clauses.length) return "";
  try {
    return encodeURIComponent(JSON.stringify(expr));
  } catch {
    return "";
  }
}

export function decode(raw: string): {
  combinator: "AND" | "OR";
  clauses: Clause[];
} {
  if (!raw) return { combinator: "AND", clauses: [] };
  try {
    const parsed = JSON.parse(decodeURIComponent(raw));
    if (
      parsed &&
      (parsed.combinator === "AND" || parsed.combinator === "OR") &&
      Array.isArray(parsed.clauses)
    ) {
      const clauses = parsed.clauses.filter(
        (c: unknown): c is Clause =>
          !!c &&
          typeof (c as Clause).field === "string" &&
          typeof (c as Clause).op === "string" &&
          typeof (c as Clause).value === "string",
      );
      return { combinator: parsed.combinator, clauses };
    }
  } catch {
    /* fall through */
  }
  return { combinator: "AND", clauses: [] };
}
