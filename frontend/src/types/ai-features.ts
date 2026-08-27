// ---------------------------------------------------------------------------
// Smart Field Types
// ---------------------------------------------------------------------------

export type SmartFieldType =
  | "ai_classify"
  | "ai_classify_multi"
  | "ai_summarize"
  | "ai_sentiment"
  | "ai_extract"
  | "ai_generate"
  | "ai_translate"
  | "ai_score"
  | "ai_predict";

export const SMART_FIELD_TYPES: { value: SmartFieldType; label: string; description: string }[] = [
  { value: "ai_classify", label: "Classify", description: "Categorize text into one label" },
  { value: "ai_classify_multi", label: "Multi-Classify", description: "Categorize into multiple labels" },
  { value: "ai_summarize", label: "Summarize", description: "Generate a text summary" },
  { value: "ai_sentiment", label: "Sentiment", description: "Detect positive/negative/neutral" },
  { value: "ai_extract", label: "Extract", description: "Extract structured data from text" },
  { value: "ai_generate", label: "Generate", description: "Generate content from context" },
  { value: "ai_translate", label: "Translate", description: "Translate text to another language" },
  { value: "ai_score", label: "Score", description: "Score 0-100 based on criteria" },
  { value: "ai_predict", label: "Predict", description: "Predict a value from patterns" },
];

export type SmartFieldTrigger = "on_create" | "on_update" | "on_create_update" | "manual";

export const SMART_FIELD_TRIGGERS: { value: SmartFieldTrigger; label: string }[] = [
  { value: "on_create", label: "On Create" },
  { value: "on_update", label: "On Update" },
  { value: "on_create_update", label: "On Create/Update" },
  { value: "manual", label: "Manual" },
];

export interface SmartFieldConfig {
  type: SmartFieldType;
  source: string | string[];
  trigger: SmartFieldTrigger;
  labels?: string[];
  fields?: string[];
  maxLength?: number;
  targetLanguage?: string;
  prompt?: string;
  model?: "claude-haiku-4-5-20251001" | "claude-sonnet-4-6";
}

export const AI_MODELS: { value: string; label: string }[] = [
  { value: "claude-haiku-4-5-20251001", label: "Haiku (fast, low cost)" },
  { value: "claude-sonnet-4-6", label: "Sonnet (powerful)" },
];

// ---------------------------------------------------------------------------
// Semantic Search Types
// ---------------------------------------------------------------------------

export interface SemanticSearchConfig {
  model: string;
  embeddingColumn: string;
  sourceColumns: string[];
  searchRoute: string;
  embeddingModel?: string;
  dimensions?: number;
  hybridSearch?: boolean;
  keywordColumns?: string[];
}

// ---------------------------------------------------------------------------
// AI Component Types
// ---------------------------------------------------------------------------

export type AIComponentType =
  | "SmartFormField"
  | "InlineAssistant"
  | "DataInsightsPanel"
  | "SmartFilterBar"
  | "NaturalLanguageQuery";

export const AI_COMPONENT_TYPES: { value: AIComponentType; label: string; description: string }[] = [
  { value: "SmartFormField", label: "Smart Form Field", description: "Auto-suggest values based on context" },
  { value: "InlineAssistant", label: "Inline Assistant", description: "Writing helper for text areas" },
  { value: "DataInsightsPanel", label: "Data Insights", description: "Auto-generated insights from data" },
  { value: "SmartFilterBar", label: "Smart Filter Bar", description: "Natural language filtering" },
  { value: "NaturalLanguageQuery", label: "NL Query", description: "Ask questions about app data" },
];

export interface AIComponentConfig {
  type: AIComponentType;
  page?: string;
  component?: string;
  file?: string;
  model?: string;
  sourceFields?: string[];
  prompt?: string;
}

// ---------------------------------------------------------------------------
// AI Workflow Node Types
// ---------------------------------------------------------------------------

export type AIWorkflowNodeType =
  | "ai_classify"
  | "ai_extract"
  | "ai_decide"
  | "ai_generate";

export interface AIClassifyConfig {
  input?: string;
  labels?: string[];
  prompt?: string;
  confidenceThreshold?: number;
}

export interface AIExtractConfig {
  input?: string;
  fields?: { name: string; type: string }[];
  prompt?: string;
}

export interface AIDecideConfig {
  context?: string;
  prompt?: string;
  options?: string[];
  rules?: string[];
}

export interface AIGenerateConfig {
  context?: string;
  prompt?: string;
  tone?: string;
  maxLength?: number;
  maxTokens?: number;
}

// ---------------------------------------------------------------------------
// AI Rule Types
// ---------------------------------------------------------------------------

export type AIRuleType =
  | "content_moderation"
  | "similarity_check"
  | "ai_validation"
  | "ai_enrichment";

export const AI_RULE_TYPES: { value: AIRuleType; label: string; description: string }[] = [
  { value: "content_moderation", label: "Content Moderation", description: "LLM-based content policy enforcement" },
  { value: "similarity_check", label: "Similarity Check", description: "Detect near-duplicate records" },
  { value: "ai_validation", label: "AI Validation", description: "Complex validation via LLM" },
  { value: "ai_enrichment", label: "AI Enrichment", description: "Auto-enrich records with context" },
];

export type ModerationAction = "flag" | "reject" | "redact";
export type SimilarityAction = "warn" | "block" | "merge_suggest";

export interface ContentModerationConfig {
  field?: string;
  policy?: string;
  action?: ModerationAction;
}

export interface SimilarityCheckConfig {
  fields?: string[];
  threshold?: number;
  action?: SimilarityAction;
}

export interface AIValidationConfig {
  fields?: string[];
  prompt?: string;
  action?: "flag" | "reject";
}

export interface AIEnrichmentConfig {
  triggerField?: string;
  enrichFields?: string[];
  prompt?: string;
}

// ---------------------------------------------------------------------------
// Scheduled AI Task Types
// ---------------------------------------------------------------------------

export type ScheduledAIType =
  | "ai_summary_report"
  | "ai_anomaly_detection"
  | "ai_data_quality";

export interface ScheduledAIConfig {
  type: ScheduledAIType;
  schedule: string;
  dataQuery?: string;
  prompt?: string;
  deliverTo?: string;
  action?: string;
  tables?: string[];
}

// ---------------------------------------------------------------------------
// AI Configuration
// ---------------------------------------------------------------------------

export interface AIConfig {
  provider: "anthropic" | "openai";
  primaryModel: string;
  embeddingModel: string;
  costTrackingEnabled: boolean;
  monthlyBudget?: number;
  rateLimits?: {
    smartFields?: string;
    search?: string;
    generation?: string;
    nlQuery?: string;
  };
  fallback?: {
    onError: "skip" | "retry" | "default_value";
    retryAttempts?: number;
    retryDelayMs?: number;
  };
}

// ---------------------------------------------------------------------------
// AI Features Summary (from app-model)
// ---------------------------------------------------------------------------

export interface AIFeaturesSummary {
  smartFields: {
    model: string;
    field: string;
    type: SmartFieldType;
    source: string | string[];
    trigger: SmartFieldTrigger;
  }[];
  semanticSearch: SemanticSearchConfig[];
  aiComponents: AIComponentConfig[];
  workflowAINodes: {
    workflow: string;
    node: string;
    type: AIWorkflowNodeType;
  }[];
  aiRules: {
    id: string;
    type: AIRuleType;
    model: string;
    field?: string;
  }[];
  scheduledAI: ScheduledAIConfig[];
  config: AIConfig;
}

// ---------------------------------------------------------------------------
// Smart Field Test
// ---------------------------------------------------------------------------

export interface SmartFieldTestRequest {
  smartConfig: SmartFieldConfig;
  sampleData: Record<string, unknown>;
}

export interface SmartFieldTestResult {
  output: unknown;
  tokens_used: number;
  duration_ms: number;
  model_used: string;
  cost_usd: number;
}
