"use client";

import { useState, useEffect } from "react";
import {
  Building2,
  Users,
  FolderOpen,
  Eye,
  MessageSquare,
  PaintBucket,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  X,
  Sparkles,
  Lightbulb,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";

interface OnboardingWizardDialogProps {
  orgId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNavigate: (path: string) => void;
}

interface WizardStep {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  icon: typeof Building2;
  tip: string;
  actionLabel: string;
  path: string;
}

const WIZARD_STEPS: WizardStep[] = [
  {
    id: "welcome",
    title: "Welcome to Tentoro Forge",
    subtitle: "Build production-ready apps with AI",
    description:
      "Tentoro Forge generates full-stack applications from natural language descriptions. " +
      "Let us walk you through the key steps to get your first app running.",
    icon: Sparkles,
    tip: "You can skip this tutorial at any time and come back to it later from your dashboard.",
    actionLabel: "Get Started",
    path: "",
  },
  {
    id: "create_org",
    title: "Set Up Your Organization",
    subtitle: "Step 1 of 4",
    description:
      "Your organization is the foundation. Add departments, roles, and teams to help " +
      "Tentoro Forge understand your structure and generate apps that match your workflows.",
    icon: Building2,
    tip: "The more context you provide about your org, the better the generated apps will fit your needs.",
    actionLabel: "Go to Settings",
    path: "/settings",
  },
  {
    id: "create_project",
    title: "Create Your First Project",
    subtitle: "Step 2 of 4",
    description:
      "Start a new project by describing what you need in plain English. You can also import from " +
      "a Figma design, pick a template, or use the discovery assistant to explore ideas.",
    icon: FolderOpen,
    tip: "Try starting with a simple description like 'Build me a task management app for my engineering team'.",
    actionLabel: "Go to Projects",
    path: "/projects",
  },
  {
    id: "use_chat",
    title: "Describe Your App via Chat",
    subtitle: "Step 3 of 4",
    description:
      "The chat interface is your primary tool. Describe features, request changes, and ask questions. " +
      "Tentoro Forge will plan, generate code, and iterate based on your feedback.",
    icon: MessageSquare,
    tip: "After generation, you can refine by saying things like 'Add a search bar to the task list' or 'Change the color scheme'.",
    actionLabel: "View Projects",
    path: "/projects",
  },
  {
    id: "visual_editors",
    title: "Use Visual Editors",
    subtitle: "Step 4 of 4",
    description:
      "Once your app is generated, use the visual editors to fine-tune the data model, " +
      "configure business rules, design workflows, adjust navigation, and customize the UI " +
      "-- all without writing code.",
    icon: PaintBucket,
    tip: "Changes made in visual editors are automatically applied to your generated code via AI agents.",
    actionLabel: "Done",
    path: "",
  },
];

const STORAGE_KEY = "tentoroforge_wizard_completed";

export function OnboardingWizardDialog({
  orgId,
  open,
  onOpenChange,
  onNavigate,
}: OnboardingWizardDialogProps) {
  const [currentStep, setCurrentStep] = useState(0);

  // Reset step on open
  useEffect(() => {
    if (open) {
      setCurrentStep(0);
    }
  }, [open]);

  const step = WIZARD_STEPS[currentStep];
  const isFirst = currentStep === 0;
  const isLast = currentStep === WIZARD_STEPS.length - 1;
  const progress = ((currentStep + 1) / WIZARD_STEPS.length) * 100;
  const Icon = step.icon;

  const handleNext = () => {
    if (isLast) {
      // Mark wizard as completed
      localStorage.setItem(`${STORAGE_KEY}_${orgId}`, "true");
      onOpenChange(false);
      return;
    }
    setCurrentStep((s) => Math.min(s + 1, WIZARD_STEPS.length - 1));
  };

  const handlePrev = () => {
    setCurrentStep((s) => Math.max(s - 1, 0));
  };

  const handleSkip = () => {
    localStorage.setItem(`${STORAGE_KEY}_${orgId}`, "true");
    onOpenChange(false);
  };

  const handleAction = () => {
    if (step.path) {
      localStorage.setItem(`${STORAGE_KEY}_${orgId}`, "true");
      onOpenChange(false);
      onNavigate(`/org/${orgId}${step.path}`);
    } else {
      handleNext();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* BUG-001: DialogContent renders its OWN close X by default. This wizard
          also has a custom X in its header (below, wired to handleSkip). That's
          why two X icons stacked in the top-right corner. Suppress the built-in
          one and keep the custom skip-aware button. */}
      <DialogContent showCloseButton={false} className="gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogTitle className="sr-only">Getting Started</DialogTitle>
        {/* Progress bar */}
        <div className="h-1 bg-muted">
          <div
            className="h-full bg-primary transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-5 pb-2">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Icon className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">{step.title}</h2>
              <p className="text-xs text-muted-foreground">{step.subtitle}</p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleSkip}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Body */}
        <div className="px-6 py-4">
          <p className="text-sm leading-relaxed text-foreground/80">
            {step.description}
          </p>

          {/* Tip box */}
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
            <Lightbulb className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
            <p className="text-xs leading-relaxed text-amber-800">{step.tip}</p>
          </div>
        </div>

        {/* Step indicators */}
        <div className="flex items-center justify-center gap-2 py-2">
          {WIZARD_STEPS.map((_, i) => (
            <button
              key={i}
              className={`h-2 rounded-full transition-all ${
                i === currentStep
                  ? "w-6 bg-primary"
                  : i < currentStep
                    ? "w-2 bg-primary/50"
                    : "w-2 bg-muted-foreground/20"
              }`}
              onClick={() => setCurrentStep(i)}
            />
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t px-6 py-4">
          <div className="flex items-center gap-2">
            {!isFirst && (
              <Button variant="ghost" size="sm" onClick={handlePrev}>
                <ArrowLeft className="mr-1 h-3 w-3" />
                Back
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={handleSkip}
            >
              Skip tutorial
            </Button>
          </div>
          <div className="flex items-center gap-2">
            {step.path && (
              <Button variant="outline" size="sm" onClick={handleAction}>
                {step.actionLabel}
                <ArrowRight className="ml-1 h-3 w-3" />
              </Button>
            )}
            <Button size="sm" onClick={handleNext}>
              {isLast ? (
                <>
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  Finish
                </>
              ) : (
                <>
                  Next
                  <ArrowRight className="ml-1 h-3 w-3" />
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
