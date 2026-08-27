import { create } from "zustand";
import type { AppModel, TableModel } from "@/types/app-model";

interface DataModelState {
  appModel: AppModel | null;
  selectedTable: string | null;
  isLoading: boolean;
  error: string | null;

  setAppModel: (model: AppModel | null) => void;
  setSelectedTable: (tableName: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  getTable: (name: string) => TableModel | undefined;
  reset: () => void;
}

export const useDataModelStore = create<DataModelState>((set, get) => ({
  appModel: null,
  selectedTable: null,
  isLoading: false,
  error: null,

  setAppModel: (model) => set({ appModel: model, error: null }),

  setSelectedTable: (tableName) => set({ selectedTable: tableName }),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error, isLoading: false }),

  getTable: (name) => {
    const { appModel } = get();
    return appModel?.database.tables.find((t) => t.name === name);
  },

  reset: () =>
    set({
      appModel: null,
      selectedTable: null,
      isLoading: false,
      error: null,
    }),
}));
