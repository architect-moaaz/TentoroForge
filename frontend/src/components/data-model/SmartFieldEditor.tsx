"use client";

import { useState } from "react";
import { Sparkles, Plus, X, FlaskConical, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  SMART_FIELD_TYPES,
  SMART_FIELD_TRIGGERS,
  AI_MODELS,
  type SmartFieldConfig,
  type SmartFieldType,
  type SmartFieldTrigger,
} from "@/types/ai-features";
import { api } from "@/lib/api";

interface SmartFieldEditorProps {
  config: SmartFieldConfig | undefined;
  onChange: (config: SmartFieldConfig | undefined) => void;
  fieldNames: string[];
  projectId: string;
}

export function SmartFieldEditor({
  config,
  onChange,
  fieldNames,
  projectId,
}: SmartFieldEditorProps) {
  const [enabled, setEnabled] = useState(!!config);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{
    output: unknown;
    tokens_used: number;
    duration_ms: number;
    cost_usd: number;
  } | null>(null);

  const handleToggle = (checked: boolean) => {
    setEnabled(checked);
    if (checked && !config) {
      onChange({
        type: "ai_classify",
        source: "",
        trigger: "on_create",
        model: "claude-haiku-4-5-20251001",
      });
    } else if (!checked) {
      onChange(undefined);
    }
  };

  const update = (updates: Partial<SmartFieldConfig>) => {
    if (!config) return;
    onChange({ ...config, ...updates });
  };

  const handleTest = async () => {
    if (!config) return;
    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await api.post<{
        output: unknown;
        tokens_used: number;
        duration_ms: number;
        cost_usd: number;
      }>(`/api/projects/${projectId}/ai-config/test-smart-field`, {
        smartConfig: config,
        sampleData: { text: "Sample input text for testing." },
      });
      setTestResult(result);
    } catch {
      setTestResult(null);
    } finally {
      setIsTesting(false);
    }
  };

  // Label management for classify types
  const addLabel = () => {
    if (!config) return;
    const labels = [...(config.labels || []), ""];
    update({ labels });
  };

  const removeLabel = (idx: number) => {
    if (!config?.labels) return;
    const labels = config.labels.filter((_, i) => i !== idx);
    update({ labels });
  };

  const updateLabel = (idx: number, value: string) => {
    if (!config?.labels) return;
    const labels = [...config.labels];
    labels[idx] = value;
    update({ labels });
  };

  // Extract fields management
  const addExtractField = () => {
    if (!config) return;
    const fields = [...(config.fields || []), ""];
    update({ fields });
  };

  const removeExtractField = (idx: number) => {
    if (!config?.fields) return;
    const fields = config.fields.filter((_, i) => i !== idx);
    update({ fields });
  };

  const updateExtractField = (idx: number, value: string) => {
    if (!config?.fields) return;
    const fields = [...config.fields];
    fields[idx] = value;
    update({ fields });
  };

  // Source as array for multi-source types
  const sourceFields = Array.isArray(config?.source)
    ? config.source
    : config?.source
      ? [config.source]
      : [];

  const needsLabels = config?.type === "ai_classify" || config?.type === "ai_classify_multi";
  const needsExtractFields = config?.type === "ai_extract";
  const needsMaxLength = config?.type === "ai_summarize";
  const needsTargetLanguage = config?.type === "ai_translate";
  const needsMultiSource =
    config?.type === "ai_generate" ||
    config?.type === "ai_score" ||
    config?.type === "ai_predict";

  return (
    <div className="space-y-3 rounded-md border p-3 bg-purple-50/30">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-purple-600" />
          <Label className="text-xs font-semibold text-purple-700">
            Smart Field (AI-Powered)
          </Label>
        </div>
        <Switch checked={enabled} onCheckedChange={handleToggle} />
      </div>

      {enabled && config && (
        <div className="space-y-3">
          {/* AI Type */}
          <div>
            <Label className="text-xs">AI Type</Label>
            <Select
              value={config.type}
              onValueChange={(v) => update({ type: v as SmartFieldType })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SMART_FIELD_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                    {t.label} — {t.description}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Source field(s) */}
          <div>
            <Label className="text-xs">
              Source Field{needsMultiSource ? "s" : ""}
            </Label>
            {needsMultiSource ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {sourceFields.map((sf, i) => (
                  <Badge
                    key={i}
                    variant="secondary"
                    className="text-xs cursor-pointer"
                    onClick={() => {
                      const arr = sourceFields.filter((_, j) => j !== i);
                      update({ source: arr });
                    }}
                  >
                    {sf} <X className="h-2.5 w-2.5 ml-1" />
                  </Badge>
                ))}
                <Select
                  onValueChange={(v) => {
                    if (!sourceFields.includes(v)) {
                      update({ source: [...sourceFields, v] });
                    }
                  }}
                >
                  <SelectTrigger className="h-7 w-[120px] text-xs">
                    <SelectValue placeholder="Add field..." />
                  </SelectTrigger>
                  <SelectContent>
                    {fieldNames
                      .filter((f) => !sourceFields.includes(f))
                      .map((f) => (
                        <SelectItem key={f} value={f} className="text-xs">
                          {f}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <Select
                value={typeof config.source === "string" ? config.source : ""}
                onValueChange={(v) => update({ source: v })}
              >
                <SelectTrigger className="mt-1 h-8 text-xs">
                  <SelectValue placeholder="Select source field..." />
                </SelectTrigger>
                <SelectContent>
                  {fieldNames.map((f) => (
                    <SelectItem key={f} value={f} className="text-xs">
                      {f}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          {/* Trigger */}
          <div>
            <Label className="text-xs">Trigger</Label>
            <Select
              value={config.trigger}
              onValueChange={(v) => update({ trigger: v as SmartFieldTrigger })}
            >
              <SelectTrigger className="mt-1 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SMART_FIELD_TRIGGERS.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Model */}
          <div>
            <Label className="text-xs">AI Model</Label>
            <Select
              value={config.model || "claude-haiku-4-5-20251001"}
              onValueChange={(v) =>
                update({
                  model: v as SmartFieldConfig["model"],
                })
              }
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

          {/* Labels (for classify types) */}
          {needsLabels && (
            <div>
              <Label className="text-xs">Classification Labels</Label>
              <div className="mt-1 space-y-1">
                {(config.labels || []).map((label, i) => (
                  <div key={i} className="flex gap-1">
                    <Input
                      className="h-7 text-xs flex-1"
                      placeholder={`Label ${i + 1}`}
                      value={label}
                      onChange={(e) => updateLabel(i, e.target.value)}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => removeLabel(i)}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={addLabel}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Label
                </Button>
              </div>
            </div>
          )}

          {/* Extract fields */}
          {needsExtractFields && (
            <div>
              <Label className="text-xs">Fields to Extract</Label>
              <div className="mt-1 space-y-1">
                {(config.fields || []).map((field, i) => (
                  <div key={i} className="flex gap-1">
                    <Input
                      className="h-7 text-xs flex-1"
                      placeholder={`Field name ${i + 1}`}
                      value={field}
                      onChange={(e) => updateExtractField(i, e.target.value)}
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7"
                      onClick={() => removeExtractField(i)}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                ))}
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={addExtractField}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Field
                </Button>
              </div>
            </div>
          )}

          {/* Max length (summarize) */}
          {needsMaxLength && (
            <div>
              <Label className="text-xs">Max Length (chars)</Label>
              <Input
                className="mt-1 h-8 text-xs"
                type="number"
                placeholder="100"
                value={config.maxLength || ""}
                onChange={(e) =>
                  update({
                    maxLength: e.target.value ? parseInt(e.target.value) : undefined,
                  })
                }
              />
            </div>
          )}

          {/* Target language (translate) */}
          {needsTargetLanguage && (
            <div>
              <Label className="text-xs">Target Language</Label>
              <Input
                className="mt-1 h-8 text-xs"
                placeholder="e.g. Spanish, French, Japanese"
                value={config.targetLanguage || ""}
                onChange={(e) => update({ targetLanguage: e.target.value })}
              />
            </div>
          )}

          {/* Custom prompt */}
          <div>
            <Label className="text-xs">Custom Prompt (optional)</Label>
            <Textarea
              className="mt-1 text-xs min-h-[60px]"
              placeholder="Additional instructions for the AI..."
              value={config.prompt || ""}
              onChange={(e) => update({ prompt: e.target.value })}
            />
          </div>

          {/* Test button */}
          <div className="pt-1">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={handleTest}
              disabled={isTesting}
            >
              {isTesting ? (
                <Loader2 className="h-3 w-3 mr-1 animate-spin" />
              ) : (
                <FlaskConical className="h-3 w-3 mr-1" />
              )}
              Test with Sample Data
            </Button>
            {testResult && (
              <div className="mt-2 rounded border bg-white p-2 space-y-1">
                <div className="text-[10px] font-semibold">Test Result</div>
                <pre className="text-[10px] text-muted-foreground bg-muted/50 rounded p-1.5 overflow-auto max-h-[80px]">
                  {JSON.stringify(testResult.output, null, 2)}
                </pre>
                <div className="flex gap-3 text-[9px] text-muted-foreground">
                  <span>{testResult.tokens_used} tokens</span>
                  <span>{testResult.duration_ms}ms</span>
                  <span>${testResult.cost_usd.toFixed(4)}</span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
