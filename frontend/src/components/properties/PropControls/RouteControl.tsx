"use client";
import * as React from "react";
import { useEditorStore } from "@/lib/editor-store";

/**
 * Route-aware text field.
 *
 * WHY it exists: four separate audit entries asked for the same thing in
 * different words — "I wanted a picker listing the project's real routes (the
 * editor already lists them in the Pages rail)" (Redirect), "no route picker —
 * the editor knows this project's routes and does not offer them" (Link),
 * "a route picker for `target` instead of free text" (NavLink), "lets me type
 * `{"type":"navigate","to":"/anything"}` with no validation that the route
 * exists" (CommandPalette). Every destination in the editor is a free-text box
 * the user has to type from memory, and a typo is indistinguishable from a
 * working link until the page is previewed.
 *
 * WHY it activates on the VALUE's shape rather than the prop's name: nothing in
 * `PropDescriptor` says "this string is a route" (there is no such
 * `ControlType`), and a list of prop names — navigate / to / target / href — is
 * exactly the thing that rots the moment a component adds a fifth. A string
 * that starts with `/` IS a route in this schema: internal destinations are
 * root-relative and everything else (a `#anchor`, an `https://` URL, ordinary
 * label text) is not. Same argument RowsControl makes for reading a row's shape
 * instead of being told it, and it is live the moment this file lands rather
 * than after another package is rebuilt.
 *
 * When the registry does grow a `control: "route"` descriptor, `RouteControl`
 * below is what it will resolve to — see CONTROL_BY_TYPE. Until then the field
 * is reached through TextControl's shape check.
 *
 * It never rewrites what the user typed. The route list is a `<datalist>`
 * suggestion and the mismatch notice is advisory text: an external URL, a route
 * that has not been created yet, and a templated path are all legitimate values
 * a picker must not clobber.
 */

const labelCls = "flex flex-col gap-1 text-sm";
const labelText = "text-xs uppercase tracking-wide text-muted-foreground";
const inputCls = "border rounded px-2 py-1 text-sm bg-background";

/**
 * A root-relative path — the shape every internal destination in this schema
 * takes. `"/"` alone is excluded on purpose: it is also the default value of
 * ordinary text props (a Breadcrumb separator, for one), and flagging that as a
 * broken route would be noise on a prop that has nothing to do with routing.
 */
export function looksLikeRoute(v: unknown): v is string {
  return typeof v === "string" && v.length > 1 && v.startsWith("/");
}

/** The routes this project actually has, from the live edit store. */
export function useProjectRoutes(): string[] {
  const artifacts = useEditorStore((s) => s.artifacts);
  return React.useMemo(() => {
    const pages = ((artifacts as any)?.navFlow?.pages ?? []) as Array<{
      route?: string;
    }>;
    const out = new Set<string>();
    for (const p of pages) if (typeof p?.route === "string" && p.route) out.add(p.route);
    return [...out].sort();
  }, [artifacts]);
}

/**
 * Does `value` reach one of `routes`?
 *
 * Dynamic segments count: `/items/42` reaches the page whose route is
 * `/items/[id]`, which is how the renderer resolves it, so the editor must not
 * call it broken.
 */
export function routeExists(routes: readonly string[], value: string): boolean {
  const path = value.split("?")[0].split("#")[0].replace(/\/+$/, "") || "/";
  for (const route of routes) {
    const r = route.replace(/\/+$/, "") || "/";
    if (r === path) return true;
    const pattern = r
      .split("/")
      .map((seg) =>
        /^\[.*\]$/.test(seg)
          ? "[^/]+"
          : seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      )
      .join("/");
    if (new RegExp(`^${pattern}$`).test(path)) return true;
  }
  return false;
}

let uid = 0;

/**
 * The two advisory bits a route-valued field gets: the project's routes as
 * `<datalist>` suggestions, and a notice when the value reaches no page.
 *
 * Split out as a hook so the same treatment can hang off any input — the whole
 * control below, and one cell of the row editor — without either of them
 * re-implementing it or giving up its own typing/commit behaviour.
 */
export function useRouteHints(value: string): {
  listId: string | undefined;
  datalist: React.ReactNode;
  warning: React.ReactNode;
} {
  const routes = useProjectRoutes();
  const id = React.useMemo(() => `routes-${++uid}`, []);
  if (!routes.length) return { listId: undefined, datalist: null, warning: null };
  const unknown = looksLikeRoute(value) && !routeExists(routes, value);
  return {
    listId: id,
    datalist: (
      <datalist id={id} data-route-suggestions="">
        {routes.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
    ),
    warning: unknown ? (
      // Advisory, never corrective. The route may simply not have been created
      // yet, and rewriting or refusing the value would be worse than a typo.
      <span data-route-warning="" className="text-[11px] text-amber-700">
        No page in this project has the route “{value}”.
      </span>
    ) : null,
  };
}

/**
 * The input itself, without a surrounding <label> — so it can be dropped into
 * a row editor as well as used as a whole control.
 */
export function RouteField({
  value,
  onChange,
  ariaLabel,
  placeholder,
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  ariaLabel?: string;
  placeholder?: string;
  className?: string;
}) {
  const { listId, datalist, warning } = useRouteHints(value);
  return (
    <>
      <input
        type="text"
        list={listId}
        aria-label={ariaLabel}
        className={className ?? inputCls}
        value={value}
        placeholder={placeholder ?? ""}
        onChange={(e) => onChange(e.target.value)}
      />
      {datalist}
      {warning}
    </>
  );
}

export function RouteControl({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: any;
  onChange: (v: any) => void;
  placeholder?: string;
}) {
  return (
    <label className={labelCls}>
      <span className={labelText}>{label}</span>
      <RouteField
        value={typeof value === "string" ? value : (value ?? "")}
        onChange={onChange}
        ariaLabel={label}
        placeholder={placeholder ?? "/route or https://…"}
      />
    </label>
  );
}
