"use client";

import { useState, useEffect } from "react";
import {
  Building2,
  Users,
  FolderOpen,
  Eye,
  CheckCircle2,
  ArrowRight,
  X,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import type { OnboardingStep } from "@/types/portal";

interface OnboardingTutorialProps {
  orgId: string;
  onDismiss: () => void;
  onNavigate: (path: string) => void;
}

interface StepConfig {
  id: OnboardingStep;
  title: string;
  description: string;
  icon: typeof Building2;
  action: string;
  path: string;
}

const STEPS: StepConfig[] = [
  {
    id: "create_org",
    title: "Set Up Your Organization",
    description:
      "Configure your organization structure with departments, teams, and roles. This helps Tentoro Forge generate apps that match your workflows.",
    icon: Building2,
    action: "Go to Settings",
    path: "/settings",
  },
  {
    id: "add_people",
    title: "Add Your Team",
    description:
      "Import your team members via CSV or add them manually. Set up reporting lines and role assignments.",
    icon: Users,
    action: "Manage People",
    path: "/people",
  },
  {
    id: "create_app",
    title: "Create Your First App",
    description:
      "Describe what you need in natural language, pick a template, or use the discovery assistant to figure out the right app.",
    icon: FolderOpen,
    action: "New Project",
    path: "/projects",
  },
  {
    id: "preview",
    title: "Preview & Refine",
    description:
      "See your app live, make changes through chat, and use visual editors to fine-tune the data model, UI, and workflows.",
    icon: Eye,
    action: "View Projects",
    path: "/projects",
  },
];

const STORAGE_KEY = "tentoroforge_onboarding";

export function OnboardingTutorial({
  orgId,
  onDismiss,
  onNavigate,
}: OnboardingTutorialProps) {
  const [completedSteps, setCompletedSteps] = useState<Set<string>>(new Set());
  const [currentIndex, setCurrentIndex] = useState(0);

  // Load from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem(`${STORAGE_KEY}_${orgId}`);
      if (saved) {
        const parsed = JSON.parse(saved);
        setCompletedSteps(new Set(parsed.completed || []));
      }
    } catch {
      // ignore
    }
  }, [orgId]);

  // Save to localStorage
  useEffect(() => {
    localStorage.setItem(
      `${STORAGE_KEY}_${orgId}`,
      JSON.stringify({ completed: Array.from(completedSteps) }),
    );
  }, [completedSteps, orgId]);

  const handleStepAction = (step: StepConfig, index: number) => {
    setCompletedSteps((prev) => new Set([...prev, step.id]));
    setCurrentIndex(Math.min(index + 1, STEPS.length - 1));
    onNavigate(`/org/${orgId}${step.path}`);
  };

  const allComplete = STEPS.every((s) => completedSteps.has(s.id));
  const progress = STEPS.filter((s) => completedSteps.has(s.id)).length;

  return (
    <Card className="relative border-primary/20 bg-gradient-to-br from-primary/5 to-transparent">
      <Button
        variant="ghost"
        size="icon"
        className="absolute right-2 top-2 h-7 w-7"
        onClick={onDismiss}
      >
        <X className="h-4 w-4" />
      </Button>

      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primary" />
          <CardTitle className="text-lg">
            {allComplete ? "You're all set!" : "Welcome to Tentoro Forge"}
          </CardTitle>
        </div>
        <CardDescription>
          {allComplete
            ? "You've completed the getting started guide. Start building!"
            : `Get started in ${STEPS.length} simple steps (${progress}/${STEPS.length} complete)`}
        </CardDescription>
        {/* Progress bar */}
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${(progress / STEPS.length) * 100}%` }}
          />
        </div>
      </CardHeader>

      {!allComplete && (
        <CardContent className="pt-0">
          <div className="space-y-3">
            {STEPS.map((step, index) => {
              const isDone = completedSteps.has(step.id);
              const isCurrent = index === currentIndex;
              const Icon = step.icon;

              return (
                <div
                  key={step.id}
                  className={`flex items-start gap-3 rounded-lg border p-3 transition-colors ${
                    isCurrent && !isDone
                      ? "border-primary/30 bg-primary/5"
                      : isDone
                        ? "border-green-200 bg-green-50/50"
                        : "border-border"
                  }`}
                >
                  <div className="mt-0.5">
                    {isDone ? (
                      <CheckCircle2 className="h-5 w-5 text-green-600" />
                    ) : (
                      <Icon className="h-5 w-5 text-muted-foreground" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p
                      // BUG-005: a completed step showed the green tick AND a
                      // strikethrough "line" through its title. The tick alone is
                      // enough — drop `line-through`, keep the green colour.
                      className={`text-sm font-medium ${isDone ? "text-green-700" : ""}`}
                    >
                      {step.title}
                    </p>
                    {!isDone && (
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {step.description}
                      </p>
                    )}
                  </div>
                  {!isDone && (
                    <Button
                      variant="outline"
                      size="sm"
                      className="shrink-0 gap-1 text-xs"
                      onClick={() => handleStepAction(step, index)}
                    >
                      {step.action}
                      <ArrowRight className="h-3 w-3" />
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
