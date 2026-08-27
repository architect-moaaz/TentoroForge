"use client";

import {
  Calculator,
  ShieldCheck,
  Layers,
  GitBranch,
  TrendingDown,
  ClipboardCheck,
  Grid3x3,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RULE_TEMPLATES } from "@/lib/decision/templates";
import type { DecisionTableDefinition, RuleTemplate } from "@/types/decision";

interface RuleTemplateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (table: DecisionTableDefinition) => void;
}

const ICONS: Record<string, typeof Calculator> = {
  Calculator,
  ShieldCheck,
  Layers,
  GitBranch,
  TrendingDown,
  ClipboardCheck,
  Grid3x3,
};

export function RuleTemplateDialog({
  open,
  onOpenChange,
  onSelect,
}: RuleTemplateDialogProps) {
  const handleSelect = (template: RuleTemplate) => {
    // Create a fresh copy with new IDs
    const table: DecisionTableDefinition = {
      ...template.table,
      id: `dt_${Date.now()}`,
      rules: template.table.rules.map((r, i) => ({
        ...r,
        id: `rule_${Date.now()}_${i}`,
      })),
    };
    onSelect(table);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-sm">Choose a Template</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-2 max-h-[400px] overflow-y-auto">
          {RULE_TEMPLATES.map((template) => {
            const Icon = ICONS[template.icon] || Calculator;
            return (
              <div
                key={template.type}
                className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/30 cursor-pointer transition-colors"
                onClick={() => handleSelect(template)}
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-50 shrink-0">
                  <Icon className="h-5 w-5 text-indigo-600" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold">{template.name}</div>
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {template.description}
                  </p>
                  <div className="flex gap-2 mt-1.5">
                    <span className="inline-flex items-center rounded bg-blue-50 px-1.5 py-0.5 text-[9px] font-medium text-blue-700">
                      {template.table.inputs.length} inputs
                    </span>
                    <span className="inline-flex items-center rounded bg-emerald-50 px-1.5 py-0.5 text-[9px] font-medium text-emerald-700">
                      {template.table.outputs.length} outputs
                    </span>
                    <span className="inline-flex items-center rounded bg-indigo-50 px-1.5 py-0.5 text-[9px] font-medium text-indigo-700">
                      {template.table.rules.length} rules
                    </span>
                    <span className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground">
                      {template.table.hitPolicy}
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
