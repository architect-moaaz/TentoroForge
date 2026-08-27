"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";

// Design adapts to the app: brand panel shows an industry-relevant photo
// (https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&q=80) under a primary-colour overlay; app name (Document Intelligence) +
// button use the app's palette via shadcn theme tokens.


/**
 * Signup composition — the layout is chosen per app by the design DNA
 * (`brand-wash`), and the brand surface is painted from the app's OWN
 * palette rather than a stock photo, so no two generated apps share this screen.
 */
const AUTH_LAYOUT = "brand-wash";

function BrandPanel({ variant }: { variant: "full" | "panel" }) {
  return (
    <div
      className="relative flex h-full flex-col justify-between overflow-hidden p-10 lg:p-12"
      style={{
        background:
          "linear-gradient(150deg, hsl(var(--primary)) 0%, hsl(var(--primary)) 45%, hsl(var(--accent)) 100%)",
      }}
    >
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.22]"
        style={{ background: "radial-gradient(120% 80% at 15% 10%, rgba(255,255,255,.65), transparent 60%)" }} />
      <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.10]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
        }} />
      <div className="relative z-10 text-lg font-semibold text-white">Document Intelligence</div>
      <div className="relative z-10 space-y-3">
        <h2 className={`font-semibold leading-tight text-white ${variant === "full" ? "text-4xl lg:text-5xl" : "text-3xl"}`}
          style={{ fontFamily: "var(--font-heading)" }}>
          Get started in minutes.
        </h2>
        <p className="max-w-md text-sm leading-relaxed text-white/85">Create your account to start using Document Intelligence.</p>
      </div>
      <div className="relative z-10 text-xs text-white/70">© Document Intelligence</div>
    </div>
  );
}

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j?.error || "Signup failed");
        setLoading(false);
        return;
      }
      await signIn("credentials", { redirect: false, email, password });
      router.push("/");
      router.refresh();
    } catch {
      setError("Network error");
      setLoading(false);
    }
  }

  return (
    <main className={
      AUTH_LAYOUT === "centered-minimal" || AUTH_LAYOUT === "top-anchored"
        ? "flex min-h-screen items-center justify-center bg-background"
        : "flex min-h-screen"
    }>
      {AUTH_LAYOUT !== "centered-minimal" && AUTH_LAYOUT !== "top-anchored" && AUTH_LAYOUT !== "split-reversed" && (
        <aside className={AUTH_LAYOUT === "side-panel" ? "hidden w-[38%] lg:block" : "hidden w-1/2 lg:block"}>
          <BrandPanel variant="panel" />
        </aside>
      )}
      <div className="flex flex-1 items-center justify-center bg-background p-6">
        <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5">
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold text-foreground">Create account</h1>
            <p className="text-sm text-muted-foreground">Join Document Intelligence</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground" htmlFor="name">Name</label>
            <input id="name" required value={name} onChange={(e) => setName(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground" htmlFor="email">Email</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground" htmlFor="password">Password</label>
            <input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <button type="submit" disabled={loading}
            className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:opacity-50">
            {loading ? "Creating…" : "Create account"}
          </button>
          <p className="text-center text-sm text-muted-foreground">
            Already have an account? <a href="/login" className="font-medium text-primary hover:underline">Sign in</a>
          </p>
        </form>
      </div>
      {AUTH_LAYOUT === "split-reversed" && (
        <aside className="hidden w-1/2 lg:block"><BrandPanel variant="panel" /></aside>
      )}
    </main>
  );
}
