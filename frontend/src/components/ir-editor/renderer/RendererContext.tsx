"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { RendererContext, IRNode, NodePath, ActionDef, TokenMap, FragmentDef } from "./types";
import { setByPath } from "./bindings";
import { executeAction } from "./actions";

const Ctx = createContext<RendererContext | null>(null);

export function useRendererContext(): RendererContext {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useRendererContext must be used within RendererProvider");
  return ctx;
}

interface RendererProviderProps {
  page: {
    state?: Record<string, { default?: unknown }>;
    modals?: Record<string, unknown>;
    root: IRNode;
  };
  tokens?: TokenMap;
  fragments?: Record<string, FragmentDef>;
  selectedPath: NodePath | null;
  hoveredPath: NodePath | null;
  onSelect: (path: NodePath) => void;
  onHover: (path: NodePath | null) => void;
  editable?: boolean;
  children: React.ReactNode;
}

export function RendererProvider({
  page,
  tokens,
  fragments,
  selectedPath,
  hoveredPath,
  onSelect,
  onHover,
  editable = true,
  children,
}: RendererProviderProps) {
  // Initialize page state from PageIR.state defaults
  const [state, setStateRaw] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    if (page.state) {
      for (const [key, def] of Object.entries(page.state)) {
        initial[key] = def.default ?? null;
      }
    }
    return initial;
  });

  const setState = useCallback((path: string, value: unknown) => {
    setStateRaw((prev) => setByPath(prev, path, value));
  }, []);

  // Modal state
  const [modalState, setModalState] = useState<Record<string, boolean>>(() => {
    const m: Record<string, boolean> = {};
    if (page.modals) {
      for (const name of Object.keys(page.modals)) {
        m[name] = false;
      }
    }
    return m;
  });

  const toggleModal = useCallback((name: string) => {
    setModalState((prev) => ({ ...prev, [name]: !prev[name] }));
  }, []);

  // Mock data sources
  const dataSources = useMemo(() => {
    const ds: Record<string, { data: unknown; isLoading: boolean; error: string | null }> = {};
    // Provide empty arrays as mock data for each source
    return ds;
  }, []);

  const onAction = useCallback(
    (action: ActionDef) => {
      executeAction(action, ctxRef.current);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const ctx: RendererContext = useMemo(
    () => ({
      state,
      setState,
      dataSources,
      tokens: tokens ?? {},
      fragments: fragments ?? {},
      modals: modalState,
      toggleModal,
      iteratorScope: null,
      onAction,
      selectedPath,
      hoveredPath,
      onSelect,
      onHover,
      editable,
    }),
    [state, setState, dataSources, tokens, fragments, modalState, toggleModal, onAction, selectedPath, hoveredPath, onSelect, onHover, editable],
  );

  // Keep a ref for the action callback to avoid stale closures
  const ctxRef = { current: ctx };

  return <Ctx.Provider value={ctx}>{children}</Ctx.Provider>;
}
