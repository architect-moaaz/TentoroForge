"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  Brain,
  Search,
  Settings2,
  BarChart3,
  Shield,
  Clock,
  Plus,
  X,
  Loader2,
  Save,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  AI_MODELS,
  AI_COMPONENT_TYPES,
  type AIConfig,
  type SemanticSearchConfig,
  type AIComponentConfig,
  type AIComponentType,
} from "@/types/ai-features";
import type { AppModel } from "@/types/app-model";

type SubTab = "overview" | "config" | "search" | "components" | "scheduled";

interface AIFeaturesPanelProps {
  projectId: string;
}

export function AIFeaturesPanel({ projectId }: AIFeaturesPanelProps) {
  const [subTab, setSubTab] = useState<SubTab>("overview");
  const queryClient = useQueryClient();

  const { data: aiConfig, isLoading } = useQuery({
    queryKey: ["project", projectId, "ai-config"],
    queryFn: () => api.get<{
      config: AIConfig;
      semanticSearch: SemanticSearchConfig[];
      aiComponents: AIComponentConfig[];
      scheduledAI: unknown[];
    }>(`/api/projects/${projectId}/ai-config`),
  });

  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
  });

  const modelNames = appModel?.database?.tables?.map((t) => t.name) ?? [];

  // Count smart fields across all tables
  const smartFieldCount =
    appModel?.database?.tables?.reduce(
      (acc, t) => acc + (t.columns?.filter((c) => c.smart)?.length ?? 0),
      0
    ) ?? 0;

  const tabs = [
    { id: "overview" as SubTab, label: "Overview", icon: BarChart3 },
    { id: "config" as SubTab, label: "Configuration", icon: Settings2 },
    { id: "search" as SubTab, label: "Semantic Search", icon: Search },
    { id: "components" as SubTab, label: "AI Components", icon: Brain },
  ];

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <Sparkles className="h-4 w-4 text-purple-600" />
        <span className="text-sm font-semibold">AI Features</span>
      </div>

      {/* Sub-tabs */}
      <div className="flex border-b px-4">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
                subTab === tab.id
                  ? "border-purple-500 text-purple-700"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setSubTab(tab.id)}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {subTab === "overview" && (
          <OverviewTab
            smartFieldCount={smartFieldCount}
            searchCount={aiConfig?.semanticSearch?.length ?? 0}
            componentCount={aiConfig?.aiComponents?.length ?? 0}
            config={aiConfig?.config}
          />
        )}
        {subTab === "config" && (
          <ConfigTab
            projectId={projectId}
            config={aiConfig?.config}
            onSaved={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectId, "ai-config"],
              })
            }
          />
        )}
        {subTab === "search" && (
          <SemanticSearchTab
            projectId={projectId}
            configs={aiConfig?.semanticSearch ?? []}
            modelNames={modelNames}
            onChanged={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectId, "ai-config"],
              })
            }
          />
        )}
        {subTab === "components" && (
          <AIComponentsTab
            projectId={projectId}
            components={aiConfig?.aiComponents ?? []}
            modelNames={modelNames}
            onChanged={() =>
              queryClient.invalidateQueries({
                queryKey: ["project", projectId, "ai-config"],
              })
            }
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({
  smartFieldCount,
  searchCount,
  componentCount,
  config,
}: {
  smartFieldCount: number;
  searchCount: number;
  componentCount: number;
  config?: AIConfig;
}) {
  const features = [
    {
      icon: Sparkles,
      label: "Smart Fields",
      count: smartFieldCount,
      color: "text-purple-600",
      bg: "bg-purple-50",
      description: "AI-computed data model fields",
    },
    {
      icon: Search,
      label: "Semantic Search",
      count: searchCount,
      color: "text-blue-600",
      bg: "bg-blue-50",
      description: "Meaning-based search with embeddings",
    },
    {
      icon: Brain,
      label: "AI Components",
      count: componentCount,
      color: "text-teal-600",
      bg: "bg-teal-50",
      description: "Smart UI components",
    },
    {
      icon: Shield,
      label: "AI Rules",
      count: 0,
      color: "text-orange-600",
      bg: "bg-orange-50",
      description: "Content moderation, similarity checks",
    },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {features.map((f) => {
          const Icon = f.icon;
          return (
            <div key={f.label} className={`rounded-lg border p-3 ${f.bg}`}>
              <div className="flex items-center gap-2">
                <Icon className={`h-4 w-4 ${f.color}`} />
                <span className="text-xs font-semibold">{f.label}</span>
                <Badge variant="secondary" className="ml-auto text-[10px]">
                  {f.count}
                </Badge>
              </div>
              <p className="mt-1 text-[10px] text-muted-foreground">{f.description}</p>
            </div>
          );
        })}
      </div>

      <Separator />

      <div className="rounded-lg border p-3">
        <div className="flex items-center gap-2 mb-2">
          <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold">Configuration</span>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground">
          <div>Provider: <span className="text-foreground">{config?.provider || "anthropic"}</span></div>
          <div>Model: <span className="text-foreground">{config?.primaryModel || "Haiku"}</span></div>
          <div>Embeddings: <span className="text-foreground">{config?.embeddingModel || "text-embedding-3-small"}</span></div>
          <div>Budget: <span className="text-foreground">${config?.monthlyBudget ?? 50}/mo</span></div>
          <div>Cost Tracking: <span className="text-foreground">{config?.costTrackingEnabled ? "Enabled" : "Disabled"}</span></div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Configuration Tab
// ---------------------------------------------------------------------------

function ConfigTab({
  projectId,
  config: initialConfig,
  onSaved,
}: {
  projectId: string;
  config?: AIConfig;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<AIConfig>(
    initialConfig ?? {
      provider: "anthropic",
      primaryModel: "claude-haiku-4-5-20251001",
      embeddingModel: "text-embedding-3-small",
      costTrackingEnabled: true,
      monthlyBudget: 50,
    }
  );
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (initialConfig) setConfig(initialConfig);
  }, [initialConfig]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await api.put(`/api/projects/${projectId}/ai-config`, config);
      onSaved();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-4 max-w-lg">
      <div>
        <Label className="text-xs">Primary AI Model</Label>
        <Select
          value={config.primaryModel}
          onValueChange={(v) => setConfig({ ...config, primaryModel: v })}
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AI_MODELS.map((m) => (
              <SelectItem key={m.value} value={m.value} className="text-xs">
                {m.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">Embedding Model</Label>
        <Input
          className="mt-1 h-8 text-xs"
          value={config.embeddingModel}
          onChange={(e) => setConfig({ ...config, embeddingModel: e.target.value })}
        />
      </div>

      <div>
        <Label className="text-xs">Monthly Budget (USD)</Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          value={config.monthlyBudget ?? ""}
          onChange={(e) =>
            setConfig({
              ...config,
              monthlyBudget: e.target.value ? parseFloat(e.target.value) : undefined,
            })
          }
        />
      </div>

      <div className="flex items-center gap-2">
        <Switch
          checked={config.costTrackingEnabled}
          onCheckedChange={(checked) =>
            setConfig({ ...config, costTrackingEnabled: checked })
          }
        />
        <Label className="text-xs">Enable cost tracking</Label>
      </div>

      <Separator />

      <div>
        <Label className="text-xs font-semibold">Error Handling</Label>
        <Select
          value={config.fallback?.onError || "skip"}
          onValueChange={(v) =>
            setConfig({
              ...config,
              fallback: {
                ...config.fallback,
                onError: v as "skip" | "retry" | "default_value",
              },
            })
          }
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="skip" className="text-xs">Skip (continue without AI result)</SelectItem>
            <SelectItem value="retry" className="text-xs">Retry (up to N attempts)</SelectItem>
            <SelectItem value="default_value" className="text-xs">Use default value</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Button size="sm" className="h-8 text-xs" onClick={handleSave} disabled={isSaving}>
        {isSaving ? <Loader2 className="h-3 w-3 mr-1 animate-spin" /> : <Save className="h-3 w-3 mr-1" />}
        Save Configuration
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Semantic Search Tab
// ---------------------------------------------------------------------------

function SemanticSearchTab({
  projectId,
  configs,
  modelNames,
  onChanged,
}: {
  projectId: string;
  configs: SemanticSearchConfig[];
  modelNames: string[];
  onChanged: () => void;
}) {
  const [isAdding, setIsAdding] = useState(false);
  const [newConfig, setNewConfig] = useState<Partial<SemanticSearchConfig>>({
    model: "",
    embeddingColumn: "embedding",
    sourceColumns: [],
    searchRoute: "",
    hybridSearch: true,
  });

  const handleAdd = async () => {
    if (!newConfig.model || !newConfig.sourceColumns?.length) return;
    try {
      await api.post(`/api/projects/${projectId}/ai-config/semantic-search`, {
        ...newConfig,
        searchRoute: newConfig.searchRoute || `/api/${newConfig.model?.toLowerCase()}/search`,
      });
      onChanged();
      setIsAdding(false);
      setNewConfig({
        model: "",
        embeddingColumn: "embedding",
        sourceColumns: [],
        searchRoute: "",
        hybridSearch: true,
      });
    } catch {
      // ignore
    }
  };

  const handleDelete = async (modelName: string) => {
    await api.delete(
      `/api/projects/${projectId}/ai-config/semantic-search/${modelName}`
    );
    onChanged();
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-semibold">Semantic Search Configurations</h3>
          <p className="text-[10px] text-muted-foreground">
            Enable meaning-based search on your data models using embeddings.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={() => setIsAdding(true)}
        >
          <Plus className="h-3 w-3 mr-1" />
          Add
        </Button>
      </div>

      {configs.map((c) => (
        <div key={c.model} className="rounded-lg border p-3 space-y-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Search className="h-3.5 w-3.5 text-blue-600" />
              <span className="text-xs font-semibold">{c.model}</span>
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => handleDelete(c.model)}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
          <div className="text-[10px] text-muted-foreground">
            Source: {c.sourceColumns.join(", ")} | Route: {c.searchRoute}
            {c.hybridSearch ? " | Hybrid" : ""}
          </div>
        </div>
      ))}

      {configs.length === 0 && !isAdding && (
        <p className="text-xs text-muted-foreground text-center py-6">
          No semantic search configured. Add one to enable AI-powered search.
        </p>
      )}

      {isAdding && (
        <div className="rounded-lg border p-3 space-y-3 bg-blue-50/30">
          <div>
            <Label className="text-xs">Model</Label>
            <Select
              value={newConfig.model || ""}
              onValueChange={(v) => setNewConfig({ ...newConfig, model: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder="Select model..." />
              </SelectTrigger>
              <SelectContent>
                {modelNames.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Source Columns (comma-separated)</Label>
            <Input
              className="mt-1 h-8 text-xs"
              placeholder="name, description"
              value={newConfig.sourceColumns?.join(", ") || ""}
              onChange={(e) =>
                setNewConfig({
                  ...newConfig,
                  sourceColumns: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                })
              }
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              checked={newConfig.hybridSearch ?? true}
              onCheckedChange={(checked) =>
                setNewConfig({ ...newConfig, hybridSearch: checked })
              }
            />
            <Label className="text-xs">Hybrid search (semantic + keyword)</Label>
          </div>
          <div className="flex gap-2">
            <Button size="sm" className="h-7 text-xs" onClick={handleAdd}>
              Add Search
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => setIsAdding(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Components Tab
// ---------------------------------------------------------------------------

function AIComponentsTab({
  projectId,
  components,
  modelNames,
  onChanged,
}: {
  projectId: string;
  components: AIComponentConfig[];
  modelNames: string[];
  onChanged: () => void;
}) {
  const [isAdding, setIsAdding] = useState(false);
  const [newComponent, setNewComponent] = useState<Partial<AIComponentConfig>>({
    type: "NaturalLanguageQuery",
  });

  const handleAdd = async () => {
    if (!newComponent.type) return;
    try {
      await api.post(`/api/projects/${projectId}/ai-config/components`, newComponent);
      onChanged();
      setIsAdding(false);
      setNewComponent({ type: "NaturalLanguageQuery" });
    } catch {
      // ignore
    }
  };

  const handleDelete = async (idx: number) => {
    await api.delete(`/api/projects/${projectId}/ai-config/components/${idx}`);
    onChanged();
  };

  const COMPONENT_ICONS: Record<string, string> = {
    SmartFormField: "text-purple-600",
    InlineAssistant: "text-blue-600",
    DataInsightsPanel: "text-teal-600",
    SmartFilterBar: "text-amber-600",
    NaturalLanguageQuery: "text-green-600",
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs font-semibold">AI-Assisted Components</h3>
          <p className="text-[10px] text-muted-foreground">
            Add intelligent UI components to the generated app.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={() => setIsAdding(true)}
        >
          <Plus className="h-3 w-3 mr-1" />
          Add
        </Button>
      </div>

      {components.map((c, idx) => (
        <div key={idx} className="rounded-lg border p-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Brain className={`h-3.5 w-3.5 ${COMPONENT_ICONS[c.type] || "text-gray-600"}`} />
              <span className="text-xs font-semibold">{c.type}</span>
              {c.page && (
                <Badge variant="secondary" className="text-[9px]">
                  {c.page}
                </Badge>
              )}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => handleDelete(idx)}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
          {c.prompt && (
            <p className="text-[10px] text-muted-foreground mt-1 truncate">
              {c.prompt}
            </p>
          )}
        </div>
      ))}

      {components.length === 0 && !isAdding && (
        <p className="text-xs text-muted-foreground text-center py-6">
          No AI components configured. Add one to enhance the app&apos;s UI.
        </p>
      )}

      {isAdding && (
        <div className="rounded-lg border p-3 space-y-3 bg-teal-50/30">
          <div>
            <Label className="text-xs">Component Type</Label>
            <Select
              value={newComponent.type || "NaturalLanguageQuery"}
              onValueChange={(v) =>
                setNewComponent({ ...newComponent, type: v as AIComponentType })
              }
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {AI_COMPONENT_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                    {t.label} — {t.description}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Page</Label>
            <Input
              className="mt-1 h-8 text-xs"
              placeholder="/dashboard"
              value={newComponent.page || ""}
              onChange={(e) => setNewComponent({ ...newComponent, page: e.target.value })}
            />
          </div>
          <div>
            <Label className="text-xs">Model (data source)</Label>
            <Select
              value={newComponent.model || ""}
              onValueChange={(v) => setNewComponent({ ...newComponent, model: v })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue placeholder="Select model..." />
              </SelectTrigger>
              <SelectContent>
                {modelNames.map((m) => (
                  <SelectItem key={m} value={m} className="text-xs">{m}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Prompt (optional)</Label>
            <Textarea
              className="mt-1 text-xs min-h-[50px]"
              placeholder="Custom instructions for the component..."
              value={newComponent.prompt || ""}
              onChange={(e) => setNewComponent({ ...newComponent, prompt: e.target.value })}
            />
          </div>
          <div className="flex gap-2">
            <Button size="sm" className="h-7 text-xs" onClick={handleAdd}>
              Add Component
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs"
              onClick={() => setIsAdding(false)}
            >
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
