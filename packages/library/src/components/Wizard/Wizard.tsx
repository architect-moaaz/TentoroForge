import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import type { WizardStepType, WizardFieldType } from "./Wizard.schema";

type Props = {
  steps: WizardStepType[];
  onComplete?: string;
  successRoute?: string;
  title?: string;
  skipReview?: boolean;
  submitLabel?: string;
  style?: StyleSlotT;
  className?: string;
};

/**
 * Wizard — Spec E Wave 3 multi-step form.
 *
 * Simple, dependency-free stepper: renders one step at a time, keeps
 * form values in local state, and on the final Submit dispatches a
 * `forge:workflow` event carrying the accumulated payload. The host
 * runtime is expected to translate that event into a real workflow
 * dispatch (mirrors the pattern already used by BulkActionBar).
 */
export function Wizard({
  steps,
  onComplete,
  successRoute: _successRoute,
  title,
  skipReview = false,
  submitLabel = "Submit",
  style,
  className,
}: Props): React.ReactElement {
  const [stepIdx, setStepIdx] = React.useState(0);
  const [values, setValues] = React.useState<Record<string, unknown>>({});
  const [submitted, setSubmitted] = React.useState(false);
  const styleProps = resolveStyle(style);

  const cleanSteps = Array.isArray(steps) ? steps.filter(Boolean) : [];
  const total = cleanSteps.length;
  // With `total === 0` the review index is 0 too, so an unconfigured Wizard
  // opened directly on its own review screen with an ARMED submit button —
  // "Review your entries before submitting" over no entries at all. A wizard
  // with no steps has nothing to review and nothing to submit.
  const reviewIdx = skipReview || total === 0 ? -1 : total;
  const isReview = !skipReview && total > 0 && stepIdx === reviewIdx;
  const step = cleanSteps[stepIdx];

  const setField = (name: string, v: unknown) =>
    setValues((prev) => ({ ...prev, [name]: v }));

  const canGoNext = React.useMemo(() => {
    if (isReview) return true;
    if (!step) return false;
    for (const f of step.fields ?? []) {
      if (f.required && !values[f.name]) return false;
    }
    if (step.nextIf && !values[step.nextIf]) return false;
    return true;
  }, [step, values, isReview]);

  const handleSubmit = () => {
    setSubmitted(true);
    if (onComplete && typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("forge:workflow", {
          detail: { workflow: onComplete, input: values },
        }),
      );
    }
  };

  const goNext = () => {
    if (!canGoNext) return;
    if (stepIdx < total - 1) return setStepIdx(stepIdx + 1);
    if (!skipReview && stepIdx === total - 1) return setStepIdx(reviewIdx);
    handleSubmit();
  };
  const goBack = () => setStepIdx((i) => Math.max(0, i - 1));

  return (
    <div
      data-forge-wizard
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        padding: 20,
        borderRadius: "var(--radius-md, 0.5rem)",
        border: "1px solid var(--border, hsl(0 0% 90%))",
        background: "var(--card, white)",
        color: "var(--card-foreground, hsl(0 0% 15%))",
        ...styleProps,
      }}
    >
      {title ? (
        <h2 style={{ margin: 0, fontSize: "1.25rem", fontWeight: 600 }}>{title}</h2>
      ) : null}

      {/* Step indicator */}
      <ol
        role="list"
        data-forge-wizard-stepper
        style={{
          display: "flex",
          gap: 8,
          listStyle: "none",
          padding: 0,
          margin: 0,
          flexWrap: "wrap",
        }}
      >
        {cleanSteps.map((s, i) => {
          const active = i === stepIdx;
          const done = i < stepIdx || isReview;
          return (
            <li
              key={s.id ?? i}
              aria-current={active ? "step" : undefined}
              style={{
                flex: "1 1 120px",
                padding: "6px 10px",
                borderRadius: "var(--radius-sm, 0.25rem)",
                fontSize: "0.8125rem",
                background: active
                  ? "var(--primary, hsl(210 60% 45%))"
                  : done
                    ? "var(--muted, hsl(0 0% 96%))"
                    : "transparent",
                color: active
                  ? "var(--primary-foreground, white)"
                  : "var(--foreground, hsl(0 0% 15%))",
                border: "1px solid var(--border, hsl(0 0% 90%))",
              }}
            >
              <span style={{ opacity: 0.7, marginRight: 6 }}>{i + 1}.</span>
              {s.title}
            </li>
          );
        })}
        {!skipReview && (
          <li
            aria-current={isReview ? "step" : undefined}
            style={{
              flex: "1 1 120px",
              padding: "6px 10px",
              borderRadius: "var(--radius-sm, 0.25rem)",
              fontSize: "0.8125rem",
              background: isReview
                ? "var(--primary, hsl(210 60% 45%))"
                : "transparent",
              color: isReview ? "var(--primary-foreground, white)" : "inherit",
              border: "1px solid var(--border, hsl(0 0% 90%))",
            }}
          >
            <span style={{ opacity: 0.7, marginRight: 6 }}>{total + 1}.</span>
            Review
          </li>
        )}
      </ol>

      {/* Body */}
      <div data-forge-wizard-body style={{ minHeight: 120 }}>
        {isReview ? (
          <ReviewPane values={values} steps={cleanSteps} />
        ) : step ? (
          <StepPane
            step={step}
            values={values}
            onChange={setField}
          />
        ) : null}
      </div>

      {/* Controls */}
      <div
        data-forge-wizard-controls
        style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}
      >
        <button
          type="button"
          onClick={goBack}
          disabled={stepIdx === 0}
          style={{
            padding: "6px 14px",
            borderRadius: "var(--radius-sm, 0.25rem)",
            border: "1px solid var(--border, hsl(0 0% 85%))",
            background: "transparent",
            cursor: stepIdx === 0 ? "not-allowed" : "pointer",
            opacity: stepIdx === 0 ? 0.5 : 1,
          }}
        >
          Back
        </button>
        <button
          type="button"
          onClick={goNext}
          disabled={!canGoNext || submitted}
          data-forge-wizard-next
          style={{
            padding: "6px 14px",
            borderRadius: "var(--radius-sm, 0.25rem)",
            border: "none",
            background: "var(--primary, hsl(210 60% 45%))",
            color: "var(--primary-foreground, white)",
            cursor: !canGoNext ? "not-allowed" : "pointer",
            opacity: !canGoNext ? 0.6 : 1,
          }}
        >
          {isReview ? submitLabel : stepIdx === total - 1 && skipReview ? submitLabel : "Next"}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────

function StepPane({
  step,
  values,
  onChange,
}: {
  step: WizardStepType;
  values: Record<string, unknown>;
  onChange: (name: string, v: unknown) => void;
}): React.ReactElement {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {step.description ? (
        <p style={{ margin: 0, color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
          {step.description}
        </p>
      ) : null}
      {(step.fields ?? []).map((f) => (
        <FieldControl
          key={f.name}
          field={f}
          value={values[f.name]}
          onChange={(v) => onChange(f.name, v)}
        />
      ))}
    </div>
  );
}

function FieldControl({
  field,
  value,
  onChange,
}: {
  field: WizardFieldType;
  value: unknown;
  onChange: (v: unknown) => void;
}): React.ReactElement {
  const id = `wizard-field-${field.name}`;
  const label = (
    <label
      htmlFor={id}
      style={{ fontSize: "0.8125rem", fontWeight: 500 }}
    >
      {field.label}
      {field.required ? (
        <span style={{ color: "var(--destructive, hsl(0 70% 50%))", marginLeft: 4 }}>*</span>
      ) : null}
    </label>
  );

  const commonStyle: React.CSSProperties = {
    padding: "8px 10px",
    borderRadius: "var(--radius-sm, 0.25rem)",
    border: "1px solid var(--border, hsl(0 0% 85%))",
    background: "var(--background, white)",
    color: "var(--foreground, hsl(0 0% 15%))",
    fontSize: "0.875rem",
    width: "100%",
    boxSizing: "border-box",
  };

  const v = value == null ? "" : String(value);

  let ctl: React.ReactNode;
  if (field.kind === "textarea") {
    ctl = (
      <textarea
        id={id}
        name={field.name}
        rows={4}
        value={v}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={commonStyle}
      />
    );
  } else if (field.kind === "select") {
    ctl = (
      <select
        id={id}
        name={field.name}
        value={v}
        onChange={(e) => onChange(e.target.value)}
        style={commonStyle}
      >
        <option value="">Select…</option>
        {(field.options ?? []).map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else if (field.kind === "checkbox") {
    ctl = (
      <input
        id={id}
        name={field.name}
        type="checkbox"
        checked={Boolean(value)}
        onChange={(e) => onChange(e.target.checked)}
      />
    );
  } else if (field.kind === "radio") {
    ctl = (
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {(field.options ?? []).map((o) => (
          <label
            key={o.value}
            style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: "0.8125rem" }}
          >
            <input
              type="radio"
              name={field.name}
              value={o.value}
              checked={v === o.value}
              onChange={() => onChange(o.value)}
            />
            {o.label}
          </label>
        ))}
      </div>
    );
  } else {
    const inputType =
      field.kind === "email" ? "email"
      : field.kind === "number" ? "number"
      : field.kind === "date" ? "date"
      : "text";
    ctl = (
      <input
        id={id}
        name={field.name}
        type={inputType}
        value={v}
        placeholder={field.placeholder}
        onChange={(e) => onChange(field.kind === "number" ? Number(e.target.value) : e.target.value)}
        style={commonStyle}
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {label}
      {ctl}
    </div>
  );
}

function ReviewPane({
  values,
  steps,
}: {
  values: Record<string, unknown>;
  steps: WizardStepType[];
}): React.ReactElement {
  return (
    <div
      data-forge-wizard-review
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <p style={{ margin: 0, color: "var(--muted-foreground, hsl(0 0% 45%))" }}>
        Review your entries before submitting.
      </p>
      {steps.map((s) => (
        <div key={s.id}>
          <div style={{ fontWeight: 600, fontSize: "0.8125rem", marginBottom: 4 }}>
            {s.title}
          </div>
          <dl
            style={{
              display: "grid",
              gridTemplateColumns: "auto 1fr",
              columnGap: 12,
              rowGap: 4,
              margin: 0,
              fontSize: "0.8125rem",
            }}
          >
            {(s.fields ?? []).map((f) => (
              <React.Fragment key={f.name}>
                <dt style={{ color: "var(--muted-foreground, hsl(0 0% 45%))" }}>{f.label}</dt>
                <dd style={{ margin: 0 }}>
                  {values[f.name] == null || values[f.name] === ""
                    ? <span style={{ color: "var(--muted-foreground, hsl(0 0% 45%))" }}>—</span>
                    : String(values[f.name])}
                </dd>
              </React.Fragment>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
