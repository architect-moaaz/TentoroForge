"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Play, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useSchemaChange } from "@/hooks/useSchemaChange";
import { RULE_TYPES, type Rule, type RuleType, type RuleConfig } from "@/types/rules";
import type { AppModel } from "@/types/app-model";
import { ValidationRuleForm } from "./ValidationRuleForm";
import { AccessControlRuleForm } from "./AccessControlRuleForm";
import { RowAccessRuleForm } from "./RowAccessRuleForm";
import { BusinessRuleForm } from "./BusinessRuleForm";
import { ComputedFieldRuleForm } from "./ComputedFieldRuleForm";
import { StateMachineEditor } from "./StateMachineEditor";
import { TriggerRuleForm } from "./TriggerRuleForm";
import {
  ContentModerationForm,
  SimilarityCheckForm,
  AIValidationForm,
  AIEnrichmentForm,
} from "./AIRuleForms";

interface RuleFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  orgId: string;
  rule: Rule | null;
  modelNames: string[];
  onSaved: () => void;
  /**
   * What a NEW rule starts as. The Record Scope panel opens this dialog to
   * author one specific kind of rule against one already-chosen model, so it
   * seeds both — and the type is then fixed, because a panel titled "Record
   * Scope" offering to save a validation rule would be lying about where the
   * rule lands. Absent (the Rules tab), the dialog behaves as before: a
   * validation rule with no model, and the type free to change.
   */
  defaultRuleType?: RuleType;
  defaultModelName?: string;
}

export function RuleFormDialog({
  open,
  onOpenChange,
  projectId,
  orgId,
  rule,
  modelNames,
  onSaved,
  defaultRuleType,
  defaultModelName,
}: RuleFormDialogProps) {
  const queryClient = useQueryClient();
  const { applyChange, isApplying, progress } = useSchemaChange();

  const [name, setName] = useState("");
  const [ruleType, setRuleType] = useState<RuleType>(defaultRuleType ?? "validation");
  const [modelName, setModelName] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [config, setConfig] = useState<RuleConfig>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset form on open
  useEffect(() => {
    if (open) {
      if (rule) {
        setName(rule.name);
        setRuleType(rule.rule_type);
        setModelName(rule.model_name || "");
        setFieldName(rule.field_name || "");
        setConfig(rule.config || {});
      } else {
        setName("");
        setRuleType(defaultRuleType ?? "validation");
        setModelName(defaultModelName ?? "");
        setFieldName("");
        setConfig({});
      }
      setError(null);
    }
  }, [open, rule, defaultRuleType, defaultModelName]);

  // Get field names for selected model
  const { data: appModel } = useQuery({
    queryKey: ["project", projectId, "app-model"],
    queryFn: () => api.get<AppModel>(`/api/projects/${projectId}/app-model`),
    enabled: open,
  });

  const fieldNames =
    appModel?.database?.tables
      ?.find((t) => t.name === modelName)
      ?.columns?.map((c) => c.name) ?? [];

  const handleSave = async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      const payload = {
        name,
        rule_type: ruleType,
        model_name: modelName || null,
        field_name: fieldName || null,
        config,
      };

      if (rule) {
        await api.put(`/api/projects/${projectId}/rules/${rule.id}`, payload);
      } else {
        await api.post(`/api/projects/${projectId}/rules`, payload);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!rule) return;
    setIsSaving(true);
    try {
      await api.delete(`/api/projects/${projectId}/rules/${rule.id}`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete rule");
    } finally {
      setIsSaving(false);
    }
  };

  const handleApply = async () => {
    if (!rule) return;
    await applyChange(projectId, `Apply rule: ${rule.name}`, () => {
      queryClient.invalidateQueries({
        queryKey: ["project", projectId, "app-model"],
      });
    });
  };

  const isEdit = !!rule;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-sm">
            {isEdit ? `Edit Rule: ${rule.name}` : "Create Rule"}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Name & Type */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Rule Name</Label>
              <Input
                className="mt-1 h-8 text-xs"
                placeholder="e.g. Require email format"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <Label className="text-xs">Rule Type</Label>
              <Select
                value={ruleType}
                onValueChange={(v) => {
                  setRuleType(v as RuleType);
                  setConfig({});
                }}
                disabled={isEdit || !!defaultRuleType}
              >
                <SelectTrigger className="mt-1 h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RULE_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value} className="text-xs">
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Type-specific form */}
          {ruleType === "validation" && (
            <ValidationRuleForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              fieldName={fieldName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
              onFieldChange={setFieldName}
            />
          )}

          {ruleType === "access" && (
            <AccessControlRuleForm
              orgId={orgId}
              modelNames={modelNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "row_access" && (
            <RowAccessRuleForm
              orgId={orgId}
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "business" && (
            <BusinessRuleForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "computed" && (
            <ComputedFieldRuleForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "state_machine" && (
            <StateMachineEditor
              modelNames={modelNames}
              config={config}
              modelName={modelName}
              fieldName={fieldName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
              onFieldChange={setFieldName}
            />
          )}

          {ruleType === "trigger" && (
            <TriggerRuleForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              fieldName={fieldName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
              onFieldChange={setFieldName}
            />
          )}

          {ruleType === "content_moderation" && (
            <ContentModerationForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              fieldName={fieldName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
              onFieldChange={setFieldName}
            />
          )}

          {ruleType === "similarity_check" && (
            <SimilarityCheckForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "ai_validation" && (
            <AIValidationForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {ruleType === "ai_enrichment" && (
            <AIEnrichmentForm
              modelNames={modelNames}
              fieldNames={fieldNames}
              config={config}
              modelName={modelName}
              onConfigChange={setConfig}
              onModelChange={setModelName}
            />
          )}

          {/* Progress indicator */}
          {isApplying && (
            <div className="rounded-md border bg-muted/20 p-3">
              <div className="flex items-center gap-2 text-xs">
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>{progress.status || "Applying rule..."}</span>
              </div>
              {progress.logs.length > 0 && (
                <div className="mt-2 max-h-24 overflow-auto text-[10px] text-muted-foreground">
                  {progress.logs.slice(-5).map((log, i) => (
                    <div key={i}>{log}</div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Error */}
          {error && (
            <p className="text-xs text-red-500">{error}</p>
          )}

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            <div>
              {isEdit && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 text-xs text-red-500 hover:text-red-600"
                  onClick={handleDelete}
                  disabled={isSaving || isApplying}
                >
                  <Trash2 className="mr-1 h-3 w-3" />
                  Delete
                </Button>
              )}
            </div>
            <div className="flex gap-2">
              {isEdit && (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 text-xs"
                  onClick={handleApply}
                  disabled={isSaving || isApplying}
                >
                  <Play className="mr-1 h-3 w-3" />
                  Apply to Code
                </Button>
              )}
              <Button
                size="sm"
                className="h-8 text-xs"
                onClick={handleSave}
                disabled={isSaving || isApplying}
              >
                {isSaving && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
                {isEdit ? "Update" : "Create"}
              </Button>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
