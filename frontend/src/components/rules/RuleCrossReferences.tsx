"use client";

import { useMemo } from "react";
import {
  Shield,
  Database,
  Layout,
  ArrowRight,
  Link2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Rule, RuleType } from "@/types/rules";
import type { AppModel } from "@/types/app-model";

interface RuleCrossReferencesProps {
  rules: Rule[];
  appModel: AppModel | null | undefined;
  selectedModel?: string | null;
  selectedField?: string | null;
  selectedComponent?: string | null;
  onRuleClick?: (rule: Rule) => void;
}

const TYPE_BADGE_COLORS: Record<RuleType, string> = {
  validation: "bg-amber-100 text-amber-700",
  access: "bg-blue-100 text-blue-700",
  row_access: "bg-sky-100 text-sky-700",
  business: "bg-green-100 text-green-700",
  computed: "bg-purple-100 text-purple-700",
  state_machine: "bg-rose-100 text-rose-700",
  trigger: "bg-orange-100 text-orange-700",
  content_moderation: "bg-red-100 text-red-700",
  similarity_check: "bg-teal-100 text-teal-700",
  ai_validation: "bg-violet-100 text-violet-700",
  ai_enrichment: "bg-cyan-100 text-cyan-700",
};

interface CrossRefGroup {
  label: string;
  icon: typeof Shield;
  rules: Rule[];
}

export function RuleCrossReferences({
  rules,
  appModel,
  selectedModel,
  selectedField,
  selectedComponent,
  onRuleClick,
}: RuleCrossReferencesProps) {
  const crossRefs = useMemo(() => {
    const groups: CrossRefGroup[] = [];

    if (selectedModel) {
      // Rules attached to this model
      const modelRules = rules.filter(
        (r) => r.model_name === selectedModel,
      );
      if (modelRules.length > 0) {
        groups.push({
          label: `Rules for ${selectedModel}`,
          icon: Database,
          rules: modelRules,
        });
      }

      // If a specific field is selected, show field-specific rules
      if (selectedField) {
        const fieldRules = rules.filter(
          (r) =>
            r.model_name === selectedModel &&
            (r.field_name === selectedField ||
              r.config?.targetField === selectedField ||
              r.config?.watchField === selectedField ||
              r.config?.stateField === selectedField ||
              r.config?.similarityFields?.includes(selectedField) ||
              r.config?.aiValidationFields?.includes(selectedField) ||
              r.config?.aiEnrichTriggerField === selectedField ||
              r.config?.aiEnrichFields?.includes(selectedField)),
        );
        if (fieldRules.length > 0) {
          groups.push({
            label: `Rules for ${selectedModel}.${selectedField}`,
            icon: Shield,
            rules: fieldRules,
          });
        }
      }

      // Access control rules that reference this model
      const accessRules = rules.filter(
        (r) =>
          r.rule_type === "access" &&
          r.model_name === selectedModel,
      );
      if (accessRules.length > 0 && !groups.some((g) => g.rules === accessRules)) {
        groups.push({
          label: `Access rules for ${selectedModel}`,
          icon: Shield,
          rules: accessRules,
        });
      }
    }

    if (selectedComponent && appModel) {
      // Find what models this component might reference
      // by checking page routes that correspond to the component
      const page = appModel.pages?.find(
        (p) => p.component === selectedComponent,
      );
      if (page) {
        // Find access rules that might apply to this page's data
        const relatedAccessRules = rules.filter(
          (r) => r.rule_type === "access",
        );
        if (relatedAccessRules.length > 0) {
          groups.push({
            label: `Access rules (may affect ${selectedComponent})`,
            icon: Layout,
            rules: relatedAccessRules,
          });
        }
      }
    }

    return groups;
  }, [rules, appModel, selectedModel, selectedField, selectedComponent]);

  if (crossRefs.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Link2 className="h-3 w-3" />
        Cross-References
      </div>
      {crossRefs.map((group, gi) => {
        const Icon = group.icon;
        return (
          <div key={gi} className="rounded-lg border p-2">
            <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium">
              <Icon className="h-3 w-3 text-muted-foreground" />
              {group.label}
              <Badge variant="secondary" className="ml-auto text-[10px]">
                {group.rules.length}
              </Badge>
            </div>
            <div className="space-y-1">
              {group.rules.slice(0, 5).map((rule) => (
                <button
                  key={rule.id}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs hover:bg-muted/50"
                  onClick={() => onRuleClick?.(rule)}
                >
                  <Badge
                    variant="secondary"
                    className={`shrink-0 text-[9px] ${TYPE_BADGE_COLORS[rule.rule_type] || ""}`}
                  >
                    {rule.rule_type}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate">{rule.name}</span>
                  <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                </button>
              ))}
              {group.rules.length > 5 && (
                <p className="px-2 text-[10px] text-muted-foreground">
                  +{group.rules.length - 5} more
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
