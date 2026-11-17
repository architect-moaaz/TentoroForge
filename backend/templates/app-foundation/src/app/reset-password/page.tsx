"use client";
import { Suspense, useEffect, useState } from "react";
import { usePasswordReset } from "@/sdk/auth";

/**
 * Forgot password: the address, then the six-digit code it was sent and a new
 * password (`/api/auth/password-reset`). The answer to "send me a code" is the
 * same whether or not the address has an account, so this page never says
 * which. A password set here lifts a sign-in pause and signs the account out
 * on every device.
 *
 * Public by necessity, like /login and /set-password (`platform_routes.py`).
 * An application that draws its own forgot-password page uses the same hook.
 */
const field =
  "w-full rounded-[var(--radius)] border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring";
const primary =
  "w-full rounded-[var(--radius)] bg-primary px-3 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition hover:opacity-90 disabled:opacity-50";

function ResetForm() {
  const { request, reset, pending, error, sentTo, sentAt, done } = usePasswordReset();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const resendIn = sentAt ? Math.max(0, 30 - Math.floor((now - sentAt) / 1000)) : 0;

  if (done) {
    return (
      <div className="w-full max-w-sm space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Password updated</h1>
        <p className="text-sm text-muted-foreground">You are signed out on every other device. Sign in with your new password.</p>
        <a href="/login" className={primary + " inline-block text-center"}>Sign in</a>
      </div>
    );
  }
  if (!sentTo) {
    return (
      <form className="w-full max-w-sm space-y-5" onSubmit={(e) => { e.preventDefault(); if (email.trim()) void request(email.trim()); }}>
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Reset your password</h1>
          <p className="text-sm text-muted-foreground">We will email you a 6-digit code.</p>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <div className="space-y-1.5">
          <label htmlFor="reset-email" className="text-sm font-medium text-foreground">Email</label>
          <input id="reset-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
        </div>
        <button type="submit" disabled={pending} className={primary}>{pending ? "Sending…" : "Email me a code"}</button>
        <p className="text-center text-sm"><a href="/login" className="text-muted-foreground hover:underline">Back to sign in</a></p>
      </form>
    );
  }
  return (
    <form className="w-full max-w-sm space-y-5" onSubmit={(e) => { e.preventDefault(); void reset(email.trim(), code, password); }}>
      <div className="space-y-1.5">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Reset your password</h1>
        <p className="text-sm text-muted-foreground">If {sentTo} has an account here, a 6-digit code is on its way. It works for 10 minutes.</p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="space-y-1.5">
        <label htmlFor="reset-code" className="text-sm font-medium text-foreground">Code</label>
        <input id="reset-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className={field + " tracking-[0.4em]"} />
        <button type="button" disabled={pending || resendIn > 0} onClick={() => void request(email.trim())}
          className="text-xs text-primary hover:underline disabled:text-muted-foreground disabled:no-underline">
          {resendIn > 0 ? `Didn’t get it? Resend in 0:${String(resendIn).padStart(2, "0")}` : "Send a new code"}
        </button>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="reset-password" className="text-sm font-medium text-foreground">New password</label>
        <input id="reset-password" type="password" autoComplete="new-password" required minLength={6} value={password}
          onChange={(e) => setPassword(e.target.value)} className={field} />
      </div>
      <p className="text-xs text-muted-foreground">Updating your password signs you out on all other devices.</p>
      <button type="submit" disabled={pending || code.length !== 6 || password.length < 6} className={primary}>
        {pending ? "Updating…" : "Update password"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-12">
      <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
        <ResetForm />
      </Suspense>
    </main>
  );
}
