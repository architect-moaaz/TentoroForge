"use client";

import {
  Sparkles,
  ArrowRight,
  MessageSquare,
  CheckCircle2,
  Zap,
} from "lucide-react";

interface ActionButtonsProps {
  actions: ActionButton[];
  onSend: (message: string) => void;
  disabled?: boolean;
}

export interface ActionButton {
  label: string;
  message: string;
  variant?: "primary" | "secondary" | "outline";
  icon?: "sparkles" | "arrow" | "chat" | "check" | "zap";
}

const ICONS = {
  sparkles: Sparkles,
  arrow: ArrowRight,
  chat: MessageSquare,
  check: CheckCircle2,
  zap: Zap,
};

export function ActionButtons({ actions, onSend, disabled }: ActionButtonsProps) {
  if (actions.length === 0) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {actions.map((action) => {
        const Icon = action.icon ? ICONS[action.icon] : null;
        const isPrimary = action.variant === "primary";

        return (
          <button
            key={action.label}
            onClick={() => onSend(action.message)}
            disabled={disabled}
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
              isPrimary
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "border bg-background hover:bg-muted text-foreground"
            }`}
          >
            {Icon && <Icon className="h-3 w-3" />}
            {action.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Derive action buttons from an assistant message.
 * Returns contextual buttons based on the message content and metadata.
 */
export function getActionsForMessage(
  content: string,
  metadata: Record<string, unknown> | null,
  messageType: string,
  isLastAssistantMessage: boolean,
): ActionButton[] {
  // Don't show actions on old messages — only the most recent assistant message
  if (!isLastAssistantMessage) return [];

  // If the message has explicit actions in metadata, use those
  if (metadata?.actions && Array.isArray(metadata.actions)) {
    return metadata.actions as ActionButton[];
  }

  // Plan messages already have PlanCard with buttons
  if (messageType === "plan") return [];

  // Generation complete messages
  if (metadata?.commit_hash && metadata?.intent !== "UNDO") return [];

  const lower = content.toLowerCase();

  // Detect question-asking patterns from the planner
  const isAskingQuestions =
    (lower.includes("?") && (
      lower.includes("what type") ||
      lower.includes("which") ||
      lower.includes("do you") ||
      lower.includes("would you") ||
      lower.includes("how should") ||
      lower.includes("what kind") ||
      lower.includes("core entities") ||
      lower.includes("authentication") ||
      lower.includes("integrations") ||
      lower.includes("let me ask") ||
      lower.includes("clarify") ||
      lower.includes("few questions") ||
      lower.includes("understand your") ||
      lower.includes("requirements")
    ));

  if (isAskingQuestions) {
    return [
      {
        label: "Use smart defaults",
        message: "Use your best judgment and make smart assumptions for all of these. Skip questions and produce the plan.",
        variant: "primary",
        icon: "zap",
      },
      {
        label: "I'll answer each",
        message: "I'll answer your questions one by one.",
        variant: "outline",
        icon: "chat",
      },
    ];
  }

  // Detect "here's the plan" or plan summary without plan-json block
  // (planner produced text but didn't format as plan-json)
  if (
    metadata?.intent === "PLAN" &&
    (lower.includes("plan") || lower.includes("here") || lower.includes("summary")) &&
    !lower.includes("?")
  ) {
    return [
      {
        label: "Generate App",
        message: "[APPROVE_PLAN]",
        variant: "primary",
        icon: "sparkles",
      },
      {
        label: "Adjust plan",
        message: "I'd like to adjust the plan.",
        variant: "outline",
        icon: "chat",
      },
    ];
  }

  // Detect "anything else?" or follow-up prompts
  if (
    lower.includes("anything else") ||
    lower.includes("would you like") ||
    lower.includes("shall i") ||
    lower.includes("want me to") ||
    lower.includes("let me know")
  ) {
    return [
      {
        label: "Looks good!",
        message: "Looks good, that's all for now.",
        variant: "primary",
        icon: "check",
      },
    ];
  }

  return [];
}
