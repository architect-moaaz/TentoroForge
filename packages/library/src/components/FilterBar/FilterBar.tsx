import * as React from "react";
import { z } from "zod";
import type { FilterBarNode } from "@tentoroforge/schema";
import { useUrlState } from "../../style/useUrlState";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";

type Props = z.infer<typeof FilterBarNode>["props"];

function FilterChipDropdown({ filter }: { filter: Props["chips"][number] }) {
  const [value, setValue] = useUrlState(filter.key, filter.defaultValue ?? "");
  const [open, setOpen] = React.useState(false);
  const current = filter.options.find((o) => o.value === value)?.label ?? "Any";
  const radiusScale = useRadiusScale();

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex h-8 items-center gap-1.5 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card px-2.5 text-xs font-medium hover:bg-muted/50`}
      >
        <span className="text-muted-foreground">{filter.label}:</span>
        <span className="text-foreground">{current}</span>
        <span className="opacity-60">▾</span>
      </button>
      {open && (
        <div className={`absolute left-0 top-full mt-1 min-w-[160px] ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-popover py-1 shadow-md z-10`}>
          <button
            type="button"
            onClick={() => { setValue(filter.defaultValue ?? ""); setOpen(false); }}
            className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-muted ${!value ? "font-semibold" : ""}`}
          >
            Any
          </button>
          {filter.options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => { setValue(opt.value); setOpen(false); }}
              className={`block w-full px-3 py-1.5 text-left text-xs hover:bg-muted ${value === opt.value ? "font-semibold text-foreground" : "text-muted-foreground"}`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function FilterBar({ chips, savedViews, showSearch }: Props) {
  const [search, setSearch] = useUrlState("q", "");
  const radiusScale = useRadiusScale();

  return (
    <div className={`flex flex-wrap items-center gap-2 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card p-2`}>
      {showSearch && (
        <input
          type="text"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={`h-8 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-background px-2.5 text-xs flex-1 min-w-[180px]`}
        />
      )}
      {chips.map((chip, i) => (
        // Fallback key when the schema author omits chip.key — LLM-composed
        // schemas often ship chips as `{label, value}` without a key, which
        // collapsed every React key to "" and triggered a duplicate-keys
        // warning. label+index is stable enough for render identity.
        <FilterChipDropdown
          key={chip.key || `${chip.label ?? "chip"}-${i}`}
          filter={chip}
        />
      ))}
      {savedViews && savedViews.length > 0 && (
        <div className="ml-auto">
          <select
            onChange={(e) => {
              const view = savedViews.find((v) => v.id === e.target.value);
              if (!view) return;
              const params = new URLSearchParams();
              for (const [k, v] of Object.entries(view.filters)) params.set(k, v);
              const newUrl = `${window.location.pathname}?${params.toString()}`;
              window.history.replaceState({}, "", newUrl);
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
            className={`h-8 ${RADIUS_SURFACE_CLASS[radiusScale]} border border-border bg-card px-2 text-xs`}
            defaultValue=""
          >
            <option key="__saved_views_placeholder" value="" disabled>Saved views…</option>
            {savedViews.map((v, i) => (
              <option key={v.id ?? `view-${i}`} value={v.id}>{v.label}</option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
