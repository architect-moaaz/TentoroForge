"use client";
import { useContext, useState } from "react";
import {
  WorkflowDispatcherContext,
  useNavigator,
  bindComputeAction,
  type ComputeAction,
} from "@tentoroforge/renderer";
import { FormComputeContext } from "../Form/Form";
import { fallbackDispatch } from "../../util/fallbackDispatch";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { RADIUS_SURFACE_CLASS } from "../../style/radius";
import { useRadiusScale } from "../../theme/tokens-context";
import { buttonVariants } from "./variants";
import { resolveIcon } from "../../icons";

/** Action descriptor shape for onClick. Engine handles "navigate" at the
 *  DOM level via a delegated click listener on [data-nav-trigger] so the
 *  library never imports from @tentoroforge/engine (avoids circular dep). */
type NavActionDescriptor = {
  action: "navigate";
  trigger?: string;
  to?: string;
  // All of these carry the same semantic — "the route this button navigates to".
  // The LLM emits any of them (route/target/href/path most common) and used to
  // silently no-op because the alias chain below only read trigger/to. Accepting
  // the whole family closes the "dead button" class at the runtime edge, matching
  // the same posture used for form-submit + workflow-dispatch descriptors.
  route?: string;
  target?: string;
  href?: string;
  path?: string;
  params?: Record<string, unknown>;
};

type Props = {
  label?: string;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  loading?: boolean;
  workflow?: string;
  args?: Record<string, unknown>;
  /** When true, render as a native submit button (type="submit") so it triggers
   *  the enclosing <Form>'s onSubmit (which collects field values + dispatches the
   *  form's workflow). The button itself does NOT dispatch — the form owns it. */
  submit?: boolean;
  navigate?: string;
  /** Id of a Dialog node to open when this button is clicked. Engine's
   *  delegated click listener picks up the `data-dialog-open` data-attr
   *  and calls openDialog(id) on DialogStateContext. */
  opensDialog?: string;
  /** onClick may be a function OR a NavActionDescriptor from the schema.
   *  When it is a NavActionDescriptor, the button renders passively with
   *  data-nav-trigger / data-nav-params and the Engine mounts the handler. */
  onClick?: (() => void) | NavActionDescriptor | unknown;
  style?: StyleSlotT;
  icon?: string;
  /** URL fallback for icons that aren't part of the lucide-react set.
   *  The Figma extractor emits this on Buttons whose Figma source had an
   *  Icon child with an exported SVG asset (e.g. nav items). Rendered as
   *  an <img> at the iconPosition when set and `icon` is absent. */
  iconSrc?: string;
  iconPosition?: "left" | "right";
  /** Marks this button as the hamburger toggle for the app shell's mobile
   *  sidebar drawer — renders `data-sidebar-toggle=""` so the
   *  ShellStateProvider's delegated click handler picks it up. */
  togglesSidebar?: boolean;
  /** Marks this button as the "Reset all filters" affordance. On click it
   *  strips every query param from the URL and dispatches `forge:urlstate`,
   *  which the host app's LiveRefresh turns into a router refresh so the
   *  page's dataSources re-resolve unfiltered. Declarative on purpose: the
   *  emitter (and the editor's toggle) sets a flag, not a handler. */
  clearsFilters?: boolean;
  "aria-label"?: string;
  /** Extra Tailwind/CSS classes from Figma-derived schemas.
   *  Appended AFTER the CVA variant classes so arbitrary-value overrides
   *  (e.g. bg-[#841013]) win via Tailwind source-order specificity. */
  className?: string;
  /** Stable slug for the journey verifier's Playwright driver — renders
   *  as `data-journey="<slug>"` on the button element. Deterministic page
   *  emitters stamp this on primary submit/create CTAs; the driver's
   *  locator resolver prefers it over role+label so tests survive label
   *  drift. See services/journey_verifier/spec.py Locator.journey_slug. */
  dataJourney?: string;
  /** Test injection only — allows bypassing context in unit tests. */
  __dispatch?: (workflow: string, args?: Record<string, unknown>) => void;
};

// className is now composed via the CVA buttonVariants factory (see variants.ts).
// The rendered class strings are functionally identical to the previous
// VARIANT_CLASSES + SIZE_CLASSES + BASE_CLASSES array-join approach —
// only the composition mechanism changes. Public prop API is unchanged.

const ICON_PX: Record<"sm" | "md" | "lg", number> = { sm: 14, md: 16, lg: 20 };

export function Button({
  label,
  variant = "primary",
  size = "md",
  disabled,
  loading,
  workflow,
  args,
  submit,
  navigate,
  opensDialog,
  onClick: onClickProp,
  style,
  icon,
  iconSrc,
  iconPosition = "left",
  togglesSidebar,
  clearsFilters,
  "aria-label": ariaLabel,
  className: extraClassName,
  dataJourney,
  __dispatch,
}: Props) {
  const ctxDispatch = useContext(WorkflowDispatcherContext);
  // Slice 5 — a compute controller (getValues/setValue) is present whenever this
  // Button is a descendant of a Form. Null outside any form, in which case a
  // compute-action onClick becomes a no-op with a console.warn (developer error).
  const computeCtx = useContext(FormComputeContext);
  const [running, setRunning] = useState(false);
  const radiusScale = useRadiusScale();
  const nav = useNavigator();
  const hasIcon = !!icon || !!iconSrc;
  const isIconOnly = hasIcon && !label;
  const IconComp = icon ? resolveIcon(icon) : null;

  // Detect a NavActionDescriptor passed via onClick from the schema renderer.
  // When detected, render passively with data-nav-trigger — the Engine mounts
  // a delegated click listener that resolves the trigger through useNavigate().
  const isNavAction =
    onClickProp !== null &&
    typeof onClickProp === "object" &&
    (onClickProp as NavActionDescriptor).action === "navigate";
  const navTrigger = isNavAction
    ? ((onClickProp as NavActionDescriptor).trigger ??
       (onClickProp as NavActionDescriptor).to ??
       (onClickProp as NavActionDescriptor).route ??
       (onClickProp as NavActionDescriptor).target ??
       (onClickProp as NavActionDescriptor).href ??
       (onClickProp as NavActionDescriptor).path)
    : undefined;
  const navParams = isNavAction
    ? JSON.stringify((onClickProp as NavActionDescriptor).params ?? {})
    : undefined;

  // Slice 5 — Detect a ComputeAction descriptor. Shape: {kind: "compute",
  // target, formula}. Runs synchronously against the enclosing form's values
  // via FormComputeContext. Coexists with navigate/workflow — one click can
  // compute AND then navigate, matching the "= then jump to result page"
  // calculator pattern.
  const isComputeAction =
    onClickProp !== null &&
    typeof onClickProp === "object" &&
    (onClickProp as ComputeAction).kind === "compute";
  const computeAction = isComputeAction ? (onClickProp as ComputeAction) : null;

  const onClick = isNavAction
    ? undefined
    : async (e?: { currentTarget?: unknown }) => {
        if (disabled || loading || running) return;
        // Reset-all-filters: drop the whole query string, then tell the host to
        // re-resolve. `replaceState` alone never re-runs the server component
        // that resolved this page's dataSources — which is why a reset chip
        // that only rewrote the URL looked like it did nothing.
        if (clearsFilters && typeof window !== "undefined") {
          window.history.replaceState(
            {}, "", `${window.location.pathname}${window.location.hash}`,
          );
          window.dispatchEvent(
            new CustomEvent("forge:urlstate", { detail: { key: "*", value: "" } }),
          );
        }
        // Submit button: explicitly submit the associated <form> via requestSubmit()
        // — this works whether the button sits INSIDE the form or in a footer action
        // bar OUTSIDE it (a common LLM layout), unlike a native type="submit" which
        // only fires for buttons nested in the form. requestSubmit() triggers the
        // Form's onSubmit (collect field values + dispatch the workflow).
        if (submit) {
          const el = (e && (e.currentTarget as HTMLElement)) || null;
          const form =
            (el && typeof el.closest === "function" && el.closest("form")) ||
            (typeof document !== "undefined" ? document.querySelector("form") : null);
          (form as HTMLFormElement | null)?.requestSubmit?.();
          return;
        }
        if (workflow) {
          // ctxDispatch can be undefined when Provider/library resolve different
          // renderer copies in a standalone app — fall back to a direct API POST.
          const dispatch = __dispatch ?? ctxDispatch ?? fallbackDispatch;
          // If no explicit args and we're inside a form, send its field values so
          // a workflow-bearing submit button still carries the user's input.
          let dispatchArgs = args as Record<string, unknown> | undefined;
          if (dispatchArgs === undefined) {
            const el = (e && (e.currentTarget as HTMLElement)) || null;
            const form =
              (el && typeof el.closest === "function" && el.closest("form")) ||
              (typeof document !== "undefined" ? document.querySelector("form") : null);
            if (form) {
              const fd = new FormData(form as HTMLFormElement);
              const vals: Record<string, unknown> = {};
              fd.forEach((v, k) => { vals[k] = v; });
              if (Object.keys(vals).length > 0) dispatchArgs = vals;
            }
          }
          setRunning(true);
          try {
            await dispatch(workflow, dispatchArgs);
          } finally {
            setRunning(false);
          }
        }
        // Slice 5 compute action — fire BEFORE navigate so a "= then go to
        // result" pattern lands the value on the form before the redirect.
        if (computeAction) {
          if (computeCtx) {
            const envelope = bindComputeAction(computeAction, computeCtx)();
            if (!envelope.ok && typeof console !== "undefined") {
              console.warn("[compute] failed:", envelope.error);
            }
          } else if (typeof console !== "undefined") {
            console.warn(
              "[compute] Button.onClick={kind:'compute'} requires a Form ancestor; got none.",
            );
          }
        }
        if (navigate) nav.push(navigate);
        if (typeof onClickProp === "function") (onClickProp as () => void)();
      };

  const isBusy = loading || running;

  const iconNode = IconComp ? (
    <IconComp
      size={ICON_PX[size]}
      data-icon={icon}
      aria-hidden="true"
    />
  ) : iconSrc ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={iconSrc}
      width={ICON_PX[size]}
      height={ICON_PX[size]}
      alt=""
      data-icon-src={iconSrc}
      aria-hidden="true"
    />
  ) : null;

  // When the schema's extraClassName carries an explicit bg-* token
  // (arbitrary like `bg-[#841013]` OR keyword like `bg-white`/`bg-transparent`)
  // the schema is authoritative — drop the variant's bg/text classes so the
  // caller's styling wins regardless of Tailwind's compiled rule order. The
  // arbitrary-value case is ALSO applied as inline backgroundColor since the
  // .bg-primary rule may otherwise outrank an arbitrary-value class at equal
  // selector specificity.
  const hasBgOverride = !!extraClassName && /\bbg-(?:\[[^\]]+\]|[a-z0-9-]+)\b/.test(extraClassName);
  const variantClass = buttonVariants({ variant, size, iconOnly: isIconOnly });
  const filteredVariantClass = hasBgOverride
    ? variantClass
        .split(/\s+/)
        .filter((t) => !/^bg-/.test(t) && !/^text-/.test(t) && !/^hover:bg-/.test(t) && !/^hover:text-/.test(t))
        .join(" ")
    : variantClass;

  const className = [
    filteredVariantClass,
    RADIUS_SURFACE_CLASS[radiusScale],
    extraClassName,
  ].filter(Boolean).join(" ");

  // Extract arbitrary-value bg color (e.g. bg-[#841013]) for inline override.
  const bgOverrideMatch = extraClassName?.match(/\bbg-\[([^\]]+)\]/);
  const inlineBgColor = bgOverrideMatch ? bgOverrideMatch[1] : undefined;

  const resolvedStyle = {
    ...resolveStyle(style),
    ...(inlineBgColor ? { backgroundColor: inlineBgColor } : {}),
  };

  return (
    <button
      type="button"
      data-variant={variant ?? "primary"}
      data-size={size ?? "md"}
      className={className}
      disabled={disabled || running}
      aria-busy={isBusy ? "true" : undefined}
      aria-label={ariaLabel}
      onClick={onClick}
      data-nav-trigger={navTrigger}
      data-nav-params={navParams}
      data-dialog-open={opensDialog}
      data-sidebar-toggle={togglesSidebar ? "" : undefined}
      data-journey={dataJourney || undefined}
      style={resolvedStyle}
      {...useMotion(style?.motion)}
    >
      {isBusy
        ? "…"
        : isIconOnly
          ? iconNode
          : iconPosition === "left"
            ? <>{iconNode}{label}</>
            : <>{label}{iconNode}</>}
    </button>
  );
}
