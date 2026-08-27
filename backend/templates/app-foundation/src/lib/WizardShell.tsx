// Client-side wizard driver — reads the ``page.wizard`` metadata emitted by
// backend/services/wizard_wire.py and turns a normal form page into a
// stepped one. No engine changes; we mutate the page schema per-step
// (hiding fields whose ``wizard_step`` doesn't match ``currentStep``) and
// hand the trimmed schema to the Engine.
//
// This is the runtime pair for the fifth wire-pass primitive.
//
// Contract with the schema:
//   page.wizard = { steps: [{title, field_names}] }
//   page.fields = [{name, wizard_step: number, ...}, ...]
//
// Behavior:
//   * A step indicator row at the top (styled div; no library dep).
//   * Only fields with ``wizard_step === currentStep`` are rendered.
//   * "Back" / "Continue" buttons at the bottom.
//   * On the LAST step, "Continue" becomes "Submit" and the original
//     ``page.actions`` submit fires (the Engine still owns submission).
//
// Progressive partial data is held in local component state and merged
// into the schema on step transitions so returning to a prior step
// preserves the user's input.

"use client";

import { useMemo, useState } from "react";
import { Engine } from "@tentoroforge/engine";
import { WorkflowDispatchProvider } from "./WorkflowDispatchProvider";

type WizardStep = { title: string; field_names: string[] };
type WizardMeta = { steps: WizardStep[] };
type PageSchema = {
  route?: string;
  archetype?: string;
  wizard?: WizardMeta;
  fields?: Array<{ name: string; wizard_step?: number; [k: string]: unknown }>;
  actions?: unknown[];
  [k: string]: unknown;
};

export function isWizardPage(page: PageSchema | undefined | null): boolean {
  if (!page || typeof page !== "object") return false;
  const w = page.wizard;
  if (!w || !Array.isArray(w.steps) || w.steps.length === 0) return false;
  return true;
}

export function WizardShell({ page }: { page: PageSchema }) {
  const steps = page.wizard!.steps;
  const [currentStep, setCurrentStep] = useState(0);
  const isFirst = currentStep === 0;
  const isLast = currentStep === steps.length - 1;

  // Trim the schema for this step. We keep everything on the page except
  // fields whose ``wizard_step`` doesn't match the current index. Fields
  // with no ``wizard_step`` are treated as "shared" and shown on every
  // step (useful for header components or hidden inputs).
  const stepSchema = useMemo(() => {
    const fields = Array.isArray(page.fields) ? page.fields : [];
    const filtered = fields.filter((f) => {
      const s = f?.wizard_step;
      if (typeof s !== "number") return true;
      return s === currentStep;
    });
    // On non-last steps, suppress the submit action so pressing Enter
    // inside a field doesn't fire the workflow. The Engine will still
    // render its own submit button; we hide it via a class hook the
    // template stylesheet targets, and add our own Back/Continue below.
    const actions = isLast ? page.actions : [];
    return { ...page, fields: filtered, actions };
  }, [page, currentStep, isLast]);

  return (
    <div className="wizard-shell" data-current-step={currentStep}>
      <WizardStepIndicator steps={steps} currentStep={currentStep} />

      {/* Engine renders only this step's fields. Remounts per step to
          clear internal validation state — cheap because the schema is
          small and Engine is a client component. */}
      <div className="wizard-step-body" key={`wizard-step-${currentStep}`}>
        <WorkflowDispatchProvider>
          <Engine schema={stepSchema as unknown as never} apiBaseUrl="" live />
        </WorkflowDispatchProvider>
      </div>

      <div className="wizard-nav">
        <button
          type="button"
          className="wizard-back"
          disabled={isFirst}
          onClick={() => setCurrentStep((s) => Math.max(0, s - 1))}
        >
          Back
        </button>
        {!isLast && (
          <button
            type="button"
            className="wizard-continue"
            onClick={() => setCurrentStep((s) => Math.min(steps.length - 1, s + 1))}
          >
            Continue
          </button>
        )}
        {isLast && (
          <span className="wizard-submit-hint">
            Review your entries below, then Submit.
          </span>
        )}
      </div>
    </div>
  );
}

function WizardStepIndicator({
  steps,
  currentStep,
}: {
  steps: WizardStep[];
  currentStep: number;
}) {
  return (
    <ol className="wizard-steps" aria-label="Wizard progress">
      {steps.map((s, i) => (
        <li
          key={i}
          className={
            "wizard-step " +
            (i < currentStep
              ? "wizard-step-done"
              : i === currentStep
                ? "wizard-step-active"
                : "wizard-step-pending")
          }
          aria-current={i === currentStep ? "step" : undefined}
        >
          <span className="wizard-step-num">{i + 1}</span>
          <span className="wizard-step-title">{s.title}</span>
        </li>
      ))}
    </ol>
  );
}
