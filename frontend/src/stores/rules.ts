import { create } from "zustand";
import type { Rule, RuleType } from "@/types/rules";

interface RulesState {
  rules: Rule[];
  selectedRule: Rule | null;
  isLoading: boolean;
  error: string | null;
  filterType: RuleType | null;
  filterModel: string | null;

  setRules: (rules: Rule[]) => void;
  setSelectedRule: (rule: Rule | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setFilterType: (type: RuleType | null) => void;
  setFilterModel: (model: string | null) => void;
  addRule: (rule: Rule) => void;
  updateRule: (rule: Rule) => void;
  removeRule: (id: string) => void;
  reset: () => void;
}

export const useRulesStore = create<RulesState>((set) => ({
  rules: [],
  selectedRule: null,
  isLoading: false,
  error: null,
  filterType: null,
  filterModel: null,

  setRules: (rules) => set({ rules, error: null }),
  setSelectedRule: (rule) => set({ selectedRule: rule }),
  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error, isLoading: false }),
  setFilterType: (type) => set({ filterType: type }),
  setFilterModel: (model) => set({ filterModel: model }),

  addRule: (rule) =>
    set((state) => ({ rules: [rule, ...state.rules] })),

  updateRule: (rule) =>
    set((state) => ({
      rules: state.rules.map((r) => (r.id === rule.id ? rule : r)),
      selectedRule: state.selectedRule?.id === rule.id ? rule : state.selectedRule,
    })),

  removeRule: (id) =>
    set((state) => ({
      rules: state.rules.filter((r) => r.id !== id),
      selectedRule: state.selectedRule?.id === id ? null : state.selectedRule,
    })),

  reset: () =>
    set({
      rules: [],
      selectedRule: null,
      isLoading: false,
      error: null,
      filterType: null,
      filterModel: null,
    }),
}));
