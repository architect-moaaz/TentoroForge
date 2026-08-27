"use client";
import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { OptimisticProviderPropsType } from "./OptimisticProvider.schema";

export interface OptimisticContextValue {
  resource: string | null;
  /** Merges intended patch into current optimistic state. */
  apply: (patch: Record<string, unknown>) => string; // returns entry id
  /** Confirms the intended state (removes pending marker). */
  confirm: (id: string) => void;
  /** Reverts a pending mutation by id (called on server error). */
  rollback: (id: string) => void;
  /** Current merged view of intended state (base + pending patches). */
  state: Record<string, unknown>;
  pending: Array<{ id: string; patch: Record<string, unknown> }>;
}

const noop = () => "";
const NoopContext: OptimisticContextValue = {
  resource: null,
  apply: noop,
  confirm: () => {},
  rollback: () => {},
  state: {},
  pending: [],
};

const OptimisticCtx = React.createContext<OptimisticContextValue>(NoopContext);

/**
 * Hook for children to observe optimistic state. Safe outside a
 * provider (returns the noop context).
 */
export function useOptimisticState(): OptimisticContextValue {
  return React.useContext(OptimisticCtx);
}

export interface OptimisticProviderProps extends OptimisticProviderPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
  /**
   * Base state the provider reflects when no pending patch is in
   * flight. Usually the current server-confirmed value.
   */
  base?: Record<string, unknown>;
}

let _idSeq = 0;
const nextId = () => `opt_${Date.now().toString(36)}_${(_idSeq++).toString(36)}`;

export function OptimisticProvider({
  resource,
  toastOnRollback = true,
  timeoutMs = 15000,
  children,
  base,
  className,
}: OptimisticProviderProps): React.ReactElement {
  const [pending, setPending] = React.useState<
    Array<{ id: string; patch: Record<string, unknown>; startedAt: number }>
  >([]);
  const baseRef = React.useRef<Record<string, unknown>>(base ?? {});
  baseRef.current = base ?? baseRef.current;

  // Timeout guard — rollback anything the server hasn't confirmed.
  React.useEffect(() => {
    if (timeoutMs === 0 || pending.length === 0) return;
    const stale = pending.map((p) => {
      const wait = Math.max(0, timeoutMs - (Date.now() - p.startedAt));
      return setTimeout(() => {
        setPending((prev) => prev.filter((x) => x.id !== p.id));
        if (toastOnRollback && typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("forge:undo:push", {
              detail: {
                id: `rollback_${p.id}`,
                label: `Change reverted (timeout)`,
                undo: () => {},
              },
            }),
          );
        }
      }, wait);
    });
    return () => stale.forEach(clearTimeout);
  }, [pending, timeoutMs, toastOnRollback]);

  const state = React.useMemo(() => {
    return pending.reduce<Record<string, unknown>>(
      (acc, p) => ({ ...acc, ...p.patch }),
      { ...baseRef.current },
    );
  }, [pending]);

  const value = React.useMemo<OptimisticContextValue>(
    () => ({
      resource: resource ?? null,
      state,
      pending: pending.map(({ id, patch }) => ({ id, patch })),
      apply: (patch) => {
        const id = nextId();
        setPending((prev) => [...prev, { id, patch, startedAt: Date.now() }]);
        return id;
      },
      confirm: (id) => {
        setPending((prev) => prev.filter((x) => x.id !== id));
      },
      rollback: (id) => {
        setPending((prev) => prev.filter((x) => x.id !== id));
        if (toastOnRollback && typeof window !== "undefined") {
          window.dispatchEvent(
            new CustomEvent("forge:undo:push", {
              detail: {
                id: `rollback_${id}`,
                label: `Change reverted`,
                undo: () => {},
              },
            }),
          );
        }
      },
    }),
    [state, pending, resource, toastOnRollback],
  );

  return (
    <OptimisticCtx.Provider value={value}>
      <div
        data-forge-optimistic={resource ?? "root"}
        style={{ display: "contents" }}
        className={className}
      >
        {children}
      </div>
    </OptimisticCtx.Provider>
  );
}
