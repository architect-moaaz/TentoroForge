"use client";

import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RuleConfig } from "@/types/rules";

interface AIRuleFormProps {
  modelNames: string[];
  fieldNames: string[];
  config: RuleConfig;
  modelName: string;
  onConfigChange: (config: RuleConfig) => void;
  onModelChange: (model: string) => void;
  onFieldChange?: (field: string) => void;
  fieldName?: string;
}

// ---------------------------------------------------------------------------
// Content Moderation
// ---------------------------------------------------------------------------

export function ContentModerationForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
  onFieldChange,
  fieldName,
}: AIRuleFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">Model</Label>
          <Select value={modelName} onValueChange={onModelChange}>
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
          <Label className="text-xs">Field to Moderate</Label>
          <Select
            value={fieldName || ""}
            onValueChange={(v) => onFieldChange?.(v)}
          >
            <SelectTrigger className="mt-1 h-8 text-xs">
              <SelectValue placeholder="Select field..." />
            </SelectTrigger>
            <SelectContent>
              {fieldNames.map((f) => (
                <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <Label className="text-xs">Content Policy</Label>
        <Textarea
          className="mt-1 text-xs min-h-[80px]"
          placeholder="Describe what content is allowed or disallowed. E.g.: No hate speech, no spam, no personal attacks. Marketing links are OK."
          value={config.policy || ""}
          onChange={(e) => onConfigChange({ ...config, policy: e.target.value })}
        />
      </div>

      <div>
        <Label className="text-xs">Action on Violation</Label>
        <Select
          value={config.moderationAction || "flag"}
          onValueChange={(v) =>
            onConfigChange({ ...config, moderationAction: v as "flag" | "reject" | "redact" })
          }
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="flag" className="text-xs">Flag for review</SelectItem>
            <SelectItem value="reject" className="text-xs">Reject with message</SelectItem>
            <SelectItem value="redact" className="text-xs">Redact offending content</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">Enforcement</Label>
        <div className="mt-1 flex gap-3">
          {(["api", "ui"] as const).map((e) => (
            <label key={e} className="flex items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={(config.enforcement || ["api"]).includes(e)}
                onChange={(ev) => {
                  const current = config.enforcement || ["api"];
                  const updated = ev.target.checked
                    ? [...current, e]
                    : current.filter((x) => x !== e);
                  onConfigChange({ ...config, enforcement: updated });
                }}
              />
              {e.toUpperCase()}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Similarity Check
// ---------------------------------------------------------------------------

export function SimilarityCheckForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: AIRuleFormProps) {
  const fields = config.similarityFields || [];

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Model</Label>
        <Select value={modelName} onValueChange={onModelChange}>
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
        <Label className="text-xs">Fields to Compare</Label>
        <div className="mt-1 space-y-1">
          {fields.map((f, i) => (
            <div key={i} className="flex gap-1">
              <Select
                value={f}
                onValueChange={(v) => {
                  const updated = [...fields];
                  updated[i] = v;
                  onConfigChange({ ...config, similarityFields: updated });
                }}
              >
                <SelectTrigger className="h-7 text-xs flex-1">
                  <SelectValue placeholder="Select field..." />
                </SelectTrigger>
                <SelectContent>
                  {fieldNames.map((fn) => (
                    <SelectItem key={fn} value={fn} className="text-xs">{fn}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    similarityFields: fields.filter((_, j) => j !== i),
                  })
                }
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() =>
              onConfigChange({ ...config, similarityFields: [...fields, ""] })
            }
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Field
          </Button>
        </div>
      </div>

      <div>
        <Label className="text-xs">Similarity Threshold (0-1)</Label>
        <Input
          className="mt-1 h-8 text-xs"
          type="number"
          step="0.05"
          min="0"
          max="1"
          placeholder="0.85"
          value={config.similarityThreshold ?? ""}
          onChange={(e) =>
            onConfigChange({
              ...config,
              similarityThreshold: e.target.value ? parseFloat(e.target.value) : undefined,
            })
          }
        />
      </div>

      <div>
        <Label className="text-xs">Action on Duplicate</Label>
        <Select
          value={config.similarityAction || "warn"}
          onValueChange={(v) =>
            onConfigChange({
              ...config,
              similarityAction: v as "warn" | "block" | "merge_suggest",
            })
          }
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="warn" className="text-xs">Warn user</SelectItem>
            <SelectItem value="block" className="text-xs">Block creation</SelectItem>
            <SelectItem value="merge_suggest" className="text-xs">Suggest merge</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Validation
// ---------------------------------------------------------------------------

export function AIValidationForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: AIRuleFormProps) {
  const fields = config.aiValidationFields || [];

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Model</Label>
        <Select value={modelName} onValueChange={onModelChange}>
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
        <Label className="text-xs">Fields to Validate</Label>
        <div className="mt-1 space-y-1">
          {fields.map((f, i) => (
            <div key={i} className="flex gap-1">
              <Select
                value={f}
                onValueChange={(v) => {
                  const updated = [...fields];
                  updated[i] = v;
                  onConfigChange({ ...config, aiValidationFields: updated });
                }}
              >
                <SelectTrigger className="h-7 text-xs flex-1">
                  <SelectValue placeholder="Select field..." />
                </SelectTrigger>
                <SelectContent>
                  {fieldNames.map((fn) => (
                    <SelectItem key={fn} value={fn} className="text-xs">{fn}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    aiValidationFields: fields.filter((_, j) => j !== i),
                  })
                }
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() =>
              onConfigChange({ ...config, aiValidationFields: [...fields, ""] })
            }
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Field
          </Button>
        </div>
      </div>

      <div>
        <Label className="text-xs">Validation Prompt</Label>
        <Textarea
          className="mt-1 text-xs min-h-[80px]"
          placeholder="Describe the validation logic. E.g.: Validate that the expense description matches the category and the amount is reasonable."
          value={config.aiValidationPrompt || ""}
          onChange={(e) => onConfigChange({ ...config, aiValidationPrompt: e.target.value })}
        />
      </div>

      <div>
        <Label className="text-xs">Action on Failure</Label>
        <Select
          value={config.aiValidationAction || "flag"}
          onValueChange={(v) =>
            onConfigChange({ ...config, aiValidationAction: v as "flag" | "reject" })
          }
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="flag" className="text-xs">Flag for review</SelectItem>
            <SelectItem value="reject" className="text-xs">Reject with message</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AI Enrichment
// ---------------------------------------------------------------------------

export function AIEnrichmentForm({
  modelNames,
  fieldNames,
  config,
  modelName,
  onConfigChange,
  onModelChange,
}: AIRuleFormProps) {
  const enrichFields = config.aiEnrichFields || [];

  return (
    <div className="space-y-4">
      <div>
        <Label className="text-xs">Model</Label>
        <Select value={modelName} onValueChange={onModelChange}>
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
        <Label className="text-xs">Trigger Field</Label>
        <p className="text-[10px] text-muted-foreground">
          When this field is set/updated, enrichment runs automatically.
        </p>
        <Select
          value={config.aiEnrichTriggerField || ""}
          onValueChange={(v) =>
            onConfigChange({ ...config, aiEnrichTriggerField: v })
          }
        >
          <SelectTrigger className="mt-1 h-8 text-xs">
            <SelectValue placeholder="Select trigger field..." />
          </SelectTrigger>
          <SelectContent>
            {fieldNames.map((f) => (
              <SelectItem key={f} value={f} className="text-xs">{f}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="text-xs">Fields to Enrich</Label>
        <div className="mt-1 space-y-1">
          {enrichFields.map((f, i) => (
            <div key={i} className="flex gap-1">
              <Input
                className="h-7 text-xs flex-1"
                placeholder="Field name to auto-fill"
                value={f}
                onChange={(e) => {
                  const updated = [...enrichFields];
                  updated[i] = e.target.value;
                  onConfigChange({ ...config, aiEnrichFields: updated });
                }}
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() =>
                  onConfigChange({
                    ...config,
                    aiEnrichFields: enrichFields.filter((_, j) => j !== i),
                  })
                }
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs"
            onClick={() =>
              onConfigChange({ ...config, aiEnrichFields: [...enrichFields, ""] })
            }
          >
            <Plus className="h-3 w-3 mr-1" />
            Add Field
          </Button>
        </div>
      </div>

      <div>
        <Label className="text-xs">Enrichment Prompt</Label>
        <Textarea
          className="mt-1 text-xs min-h-[80px]"
          placeholder="Describe how to enrich the data. E.g.: Based on the email domain, infer the company and fill in company name, industry, and size."
          value={config.aiEnrichPrompt || ""}
          onChange={(e) => onConfigChange({ ...config, aiEnrichPrompt: e.target.value })}
        />
      </div>
    </div>
  );
}
