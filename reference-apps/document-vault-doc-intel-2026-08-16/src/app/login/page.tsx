"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useLogin } from "@/hooks/useLogin";

/**
 * Auth page — COMPOSED PER APP.
 *
 * `brand-wash` is replaced at generation time with the layout chosen by
 * the project's design DNA, so no two generated apps share a sign-in screen.
 * The brand panel is painted from the app's OWN palette (CSS gradients over
 * --primary/--accent) rather than a stock photo, which is what made every
 * previous app open on the same purple image.
 *
 * Layouts: split-editorial | centered-minimal | brand-wash | side-panel |
 *          top-anchored | split-reversed
 */
const AUTH_LAYOUT = "brand-wash";
const APP_NAME = "Document Intelligence";
const HEADLINE = "Welcome to Document Intelligence";
const SUBHEAD = "Sign in to continue to Document Intelligence.";
// Form copy comes from the app's design DNA (per-archetype voice), so no two
// apps greet users with the identical "Welcome back / Sign in to X".
const FORM_TITLE = "Hey, you";
const FORM_SUB = "Let's make something today.";

function LoginForm() {
  // Honour ?callbackUrl=… and fall back to "/" — a REAL route. (The hook's own
  // default points at a route GROUP, which has no URL, so always pass one.)
  const callbackUrl = useSearchParams().get("callbackUrl") || "/";
  // NOTE: the hook's contract is `isLoading` / `handleSubmit` — destructuring
  // `loading` / `onSubmit` yields undefined, the form loses its handler and
  // does a NATIVE GET submit (URL becomes "/login?" and nothing happens).
  const { email, setEmail, password, setPassword, error, isLoading, handleSubmit } =
    useLogin(callbackUrl);
  return (
    <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {FORM_TITLE.startsWith("__") ? "Welcome back" : FORM_TITLE}
        </h1>
        <p className="text-sm text-muted-foreground">
          {FORM_SUB.startsWith("__") ? `Sign in to ${APP_NAME}` : FORM_SUB}
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-sm font-medium text-foreground">Email</label>
        <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-[var(--radius)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium text-foreground">Password</label>
        <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-[var(--radius)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
      </div>
      <button type="submit" disabled={isLoading}
        className="w-full rounded-[var(--radius)] bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:opacity-50">
        {isLoading ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-center text-sm text-muted-foreground">
        Don&apos;t have an account? <a href="/signup" className="font-medium text-primary hover:underline">Sign up</a>
      </p>
    </form>
  );
}

/** Brand surface painted from the app's palette — never a stock image. */
function BrandPanel({ variant }: { variant: "full" | "panel" }) {
  return (
    <div
      className="relative flex h-full flex-col justify-between overflow-hidden p-10 lg:p-12"
      style={{
        background:
          "linear-gradient(150deg, hsl(var(--primary)) 0%, hsl(var(--primary)) 45%, hsl(var(--accent)) 100%)",
      }}
    >
      {/* Depth: soft radial bloom + a fine grid — geometry, not clip-art. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.22]"
        style={{ background: "radial-gradient(120% 80% at 15% 10%, rgba(255,255,255,.65), transparent 60%)" }} />
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.10]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }} />
      <div className="relative z-10 text-lg font-semibold text-white">{APP_NAME}</div>
      <div className="relative z-10 space-y-3">
        <h2 className={`font-semibold leading-tight text-white ${variant === "full" ? "text-4xl lg:text-5xl" : "text-3xl"}`}
          style={{ fontFamily: "var(--font-heading)" }}>
          {HEADLINE}
        </h2>
        <p className="max-w-md text-sm leading-relaxed text-white/85">{SUBHEAD}</p>
      </div>
      <div className="relative z-10 text-xs text-white/70">© {APP_NAME}</div>
    </div>
  );
}

const FormPane = ({ className = "" }: { className?: string }) => (
  <div className={`flex flex-1 items-center justify-center bg-background p-6 ${className}`}>
    <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
      <LoginForm />
    </Suspense>
  </div>
);

export default function LoginPage() {
  switch (AUTH_LAYOUT) {
    // Form first, brand panel on the RIGHT — mirrors the industry default.
    case "split-reversed":
      return (
        <main className="flex min-h-screen">
          <FormPane />
          <aside className="hidden w-1/2 lg:block"><BrandPanel variant="panel" /></aside>
        </main>
      );

    // Narrow brand strip, generous form area.
    case "side-panel":
      return (
        <main className="flex min-h-screen">
          <aside className="hidden w-[38%] lg:block"><BrandPanel variant="panel" /></aside>
          <FormPane />
        </main>
      );

    // Single centred card on the app's tinted canvas — quiet and premium.
    case "centered-minimal":
      return (
        <main className="flex min-h-screen items-center justify-center bg-background p-6">
          <div className="w-full max-w-md rounded-[var(--radius)] border border-border bg-card p-8 shadow-sm">
            <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
              <LoginForm />
            </Suspense>
          </div>
        </main>
      );

    // Full-bleed brand wash with a floating glass form card.
    case "brand-wash":
      return (
        <main className="relative min-h-screen">
          <div className="absolute inset-0"><BrandPanel variant="full" /></div>
          <div className="relative z-10 flex min-h-screen items-center justify-end p-6 lg:p-16">
            <div className="w-full max-w-md rounded-[var(--radius)] bg-card/95 p-8 shadow-2xl backdrop-blur">
              <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
                <LoginForm />
              </Suspense>
            </div>
          </div>
        </main>
      );

    // Logo above a borderless form — maximum air, no chrome.
    case "top-anchored":
      return (
        <main className="min-h-screen bg-background">
          <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6">
            <div className="mb-10 flex flex-col items-center gap-3">
              <span className="grid h-12 w-12 place-items-center rounded-[var(--radius)] text-lg font-bold text-primary-foreground"
                style={{ background: "linear-gradient(140deg, hsl(var(--primary)), hsl(var(--accent)))" }}>
                {APP_NAME.slice(0, 1)}
              </span>
              <span className="text-xl font-semibold tracking-tight text-foreground"
                style={{ fontFamily: "var(--font-heading)" }}>{APP_NAME}</span>
            </div>
            <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
              <LoginForm />
            </Suspense>
          </div>
        </main>
      );

    // split-editorial (default): 50/50 brand statement + form.
    default:
      return (
        <main className="flex min-h-screen">
          <aside className="hidden w-1/2 lg:block"><BrandPanel variant="panel" /></aside>
          <FormPane />
        </main>
      );
  }
}
