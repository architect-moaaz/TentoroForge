"use client";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * Where a setup link lands — the screen on which a person invited to the
 * application, or one whose password was reset, chooses their own password.
 *
 * THIS PAGE IS WHY NOBODY HAS TO HANDLE A PASSWORD ON SOMEONE ELSE'S BEHALF.
 * The owner asks for an account; the account is created with no usable
 * password and a one-time link; the person opens the link and types a password
 * that only they and bcrypt ever see. The link is checked before the form is
 * shown, so an expired one says so instead of failing on submit.
 *
 * Public by necessity: a page that restores a session cannot itself require
 * one (`_ALWAYS_OPEN` in the middleware projection lists it beside
 * login and signup).
 */
const APP_NAME = "__APP_NAME__";

function SetPasswordForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") || "";
  // null = still checking; "" = no valid link; otherwise the account's email.
  const [email, setEmail] = useState<string | null>(null);
  const [purpose, setPurpose] = useState("invite");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      if (!token) {
        if (live) setEmail("");
        return;
      }
      try {
        const res = await fetch(`/api/auth/set-password?token=${encodeURIComponent(token)}`);
        const body = await res.json();
        if (!live) return;
        if (!res.ok) {
          setEmail("");
          setError(body?.error?.message || "This link has expired or has already been used.");
          return;
        }
        setEmail(String(body.email || ""));
        setPurpose(String(body.purpose || "invite"));
      } catch {
        if (live) {
          setEmail("");
          setError("Could not check that link. Try opening it again.");
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [token]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setIsSaving(true);
    try {
      const res = await fetch("/api/auth/set-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body?.error?.message || "Could not set that password.");
        return;
      }
      setDone(true);
      // Straight to the sign-in they can now complete, with the email filled
      // in by nothing but their own memory — the login page takes no hints.
      setTimeout(() => router.push("/login"), 1200);
    } catch {
      setError("Could not reach the server. Try again.");
    } finally {
      setIsSaving(false);
    }
  }

  if (email === null) {
    return <p className="text-sm text-muted-foreground">Checking your link…</p>;
  }

  if (!email) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">This link cannot be used</h1>
        <p className="text-sm text-muted-foreground">
          {error || "This link has expired or has already been used."} Ask whoever set up your
          account for a new one.
        </p>
        <a href="/login" className="inline-block text-sm font-medium text-primary hover:underline">
          Go to sign in
        </a>
      </div>
    );
  }

  if (done) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Password set</h1>
        <p className="text-sm text-muted-foreground">
          You can now sign in to {APP_NAME} as <span className="font-medium text-foreground">{email}</span>.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="w-full space-y-5">
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {purpose === "reset" ? "Choose a new password" : "Set your password"}
        </h1>
        <p className="text-sm text-muted-foreground">
          For <span className="font-medium text-foreground">{email}</span> on {APP_NAME}.
        </p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium text-foreground">New password</label>
        <input id="password" type="password" required minLength={6} value={password}
          onChange={(e) => setPassword(e.target.value)} autoComplete="new-password"
          className="w-full rounded-[var(--radius)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
        <p className="text-xs text-muted-foreground">At least 6 characters.</p>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="confirm" className="text-sm font-medium text-foreground">Repeat it</label>
        <input id="confirm" type="password" required minLength={6} value={confirm}
          onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password"
          className="w-full rounded-[var(--radius)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring" />
      </div>
      <button type="submit" disabled={isSaving}
        className="w-full rounded-[var(--radius)] bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:opacity-50">
        {isSaving ? "Saving…" : "Set password and sign in"}
      </button>
    </form>
  );
}

export default function SetPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md rounded-[var(--radius)] border border-border bg-card p-8 shadow-sm">
        <Suspense fallback={<p className="text-sm text-muted-foreground">Loading…</p>}>
          <SetPasswordForm />
        </Suspense>
      </div>
    </main>
  );
}
