import { create } from "zustand";
import type {
  AIConfig,
  SemanticSearchConfig,
  AIComponentConfig,
  ScheduledAIConfig,
} from "@/types/ai-features";

interface AIFeaturesState {
  config: AIConfig;
  semanticSearch: SemanticSearchConfig[];
  aiComponents: AIComponentConfig[];
  scheduledAI: ScheduledAIConfig[];
  isLoading: boolean;

  setConfig: (config: AIConfig) => void;
  setSemanticSearch: (items: SemanticSearchConfig[]) => void;
  setAIComponents: (items: AIComponentConfig[]) => void;
  setScheduledAI: (items: ScheduledAIConfig[]) => void;
  setLoading: (loading: boolean) => void;
  setAll: (data: {
    config?: AIConfig;
    semanticSearch?: SemanticSearchConfig[];
    aiComponents?: AIComponentConfig[];
    scheduledAI?: ScheduledAIConfig[];
  }) => void;
  reset: () => void;
}

const DEFAULT_CONFIG: AIConfig = {
  provider: "anthropic",
  primaryModel: "claude-haiku-4-5-20251001",
  embeddingModel: "text-embedding-3-small",
  costTrackingEnabled: true,
  monthlyBudget: 50,
};

export const useAIFeaturesStore = create<AIFeaturesState>((set) => ({
  config: DEFAULT_CONFIG,
  semanticSearch: [],
  aiComponents: [],
  scheduledAI: [],
  isLoading: false,

  setConfig: (config) => set({ config }),
  setSemanticSearch: (items) => set({ semanticSearch: items }),
  setAIComponents: (items) => set({ aiComponents: items }),
  setScheduledAI: (items) => set({ scheduledAI: items }),
  setLoading: (loading) => set({ isLoading: loading }),

  setAll: (data) =>
    set({
      config: data.config ?? DEFAULT_CONFIG,
      semanticSearch: data.semanticSearch ?? [],
      aiComponents: data.aiComponents ?? [],
      scheduledAI: data.scheduledAI ?? [],
    }),

  reset: () =>
    set({
      config: DEFAULT_CONFIG,
      semanticSearch: [],
      aiComponents: [],
      scheduledAI: [],
      isLoading: false,
    }),
}));
