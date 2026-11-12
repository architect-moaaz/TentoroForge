"use client";
// The app SDK — signing in and creating an account. How an `auth` page's
// `view.tsx` signs a person in or creates their account: the logic is fixed
// here (NextAuth credentials, the signup route, the account's own fields from
// `@/lib/account`); the page around it is the UI engineer's to design.

import { apiPath } from "@/lib/api-path";
import * as React from "react";
import { getSession, signIn, useSession } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { ACCOUNT, AFTER_SIGNUP, type AccountField } from "@/lib/account";
// Where a signed-in person lands: one rule for every sign-in form.
import { afterSignIn, roleAfterSignIn } from "@/lib/landing";

export type { AccountField };

/** The account entity's fields signup asks for — the ones a person types (an
 *  email field is filled from the login's email). Empty when the application
 *  has no account entity. */
export const signupFields: readonly AccountField[] = (ACCOUNT?.fields ?? []).filter((f) => f.kind !== "email");

function messageOf(body: unknown, fallback: string): string {
  const e = (body as { error?: unknown } | null)?.error;
  if (typeof e === "string" && e) return e;
  if (e && typeof e === "object" && typeof (e as { message?: unknown }).message === "string") return (e as { message: string }).message;
  return fallback;
}

/** Why a sign-in stopped short of a session (`lib/sign-in-guard.ts`): the
 *  address is paused, or a two-step code is wanted (or was wrong). */
export interface SignInStop {
  code: "SIGN_IN_PAUSED" | "TWO_STEP_REQUIRED" | "TWO_STEP_WRONG" | "TWO_STEP_EXPIRED" | "TWO_STEP_TOO_MANY";
  until?: number; sentTo?: string; wait?: number; notice?: string; left?: number;
}
function stopOf(error: unknown): SignInStop | null {
  if (typeof error !== "string" || !error.startsWith("{")) return null;
  try { const r = JSON.parse(error); return r && typeof r.code === "string" ? r as SignInStop : null; } catch { return null; }
}
/** A stop in words. */
export function stopMessage(stop: SignInStop | null): string | null {
  if (!stop) return null;
  switch (stop.code) {
    case "SIGN_IN_PAUSED": return `Sign-in is paused after 5 failed attempts. Try again after ${new Date(stop.until ?? Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}, or reset your password.`;
    case "TWO_STEP_REQUIRED": return null;
    case "TWO_STEP_WRONG": return `That code is not right. ${stop.left ?? 0} ${stop.left === 1 ? "try" : "tries"} left.`;
    case "TWO_STEP_EXPIRED": return "That code has expired. Send a new one.";
    case "TWO_STEP_TOO_MANY": return "Too many wrong codes. Send a new one.";
  }
}

/** Sign in with email and password; lands on `?callbackUrl=`, else the
 *  signed-in role's own page, else the app's home. Everyone used to go home —
 *  F&B's administrator landed on the customers' menu, outside the frame with
 *  the notification bell (2026-10-01).
 *
 *  TWO STEPS when the person turned two-step on: the first call stops with
 *  `step === "code"` (a code went to `stop.sentTo`); call again with the same
 *  email and password plus `{ code, remember }`. `resend()` asks for a new
 *  code. `pausedUntil` is set while sign-in for the address is paused. */
export function useSignIn() {
  const router = useRouter();
  const search = useSearchParams();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [stop, setStop] = React.useState<SignInStop | null>(null);
  const [step, setStep] = React.useState<"password" | "code">("password");
  const last = React.useRef<{ email: string; password: string } | null>(null);
  const signInWith = React.useCallback(async (email: string, password: string, more?: { code?: string; remember?: boolean }) => {
    setPending(true);
    setError(null);
    try {
      last.current = { email, password };
      const r = await signIn("credentials", { email, password, redirect: false,
        ...(more?.code ? { code: more.code, remember: more.remember ? "true" : "false" } : {}) });
      if (!r || r.error) {
        const s = stopOf(r?.error);
        if (s) {
          setStop(s);
          if (s.code === "SIGN_IN_PAUSED") setStep("password");
          else setStep("code");
          setError(stopMessage(s));
        } else {
          setStop(null);
          setError("That email and password do not match an account.");
        }
        return false;
      }
      setStop(null);
      // The page they were sent away from, else their role's own page
      // (`lib/landing.ts`): "/" in the address is not a destination.
      const to = afterSignIn(search?.get("callbackUrl"), await roleAfterSignIn(getSession));
      router.push(to);
      router.refresh();
      return true;
    } catch {
      setError("Signing in failed — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, [router, search]);
  /** A new two-step code: the password again, no code. */
  const resend = React.useCallback(async () => {
    if (last.current) await signInWith(last.current.email, last.current.password);
  }, [signInWith]);
  /** Back to the email and password. */
  const restart = React.useCallback(() => { setStep("password"); setStop(null); setError(null); }, []);
  const pausedUntil = stop?.code === "SIGN_IN_PAUSED" ? stop.until ?? null : null;
  return { signIn: signInWith, pending, error, step, stop, pausedUntil, resend, restart };
}

/** Forgot password: `request(email)` mails a six-digit code (the answer is
 *  the same whether or not the address has an account); `reset(email, code,
 *  password)` sets the new password, which signs the account out everywhere. */
export function usePasswordReset() {
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  const [sentAt, setSentAt] = React.useState<number | null>(null);
  const [done, setDone] = React.useState(false);
  const call = React.useCallback(async (method: "POST" | "PUT", body: Record<string, unknown>) => {
    setPending(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/password-reset"), { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await res.json().catch(() => null);
      if (!res.ok) { setError(messageOf(out, "That did not work. Try again.")); return null; }
      return out as Record<string, unknown>;
    } catch {
      setError("Check your connection and try again.");
      return null;
    } finally {
      setPending(false);
    }
  }, []);
  const request = React.useCallback(async (email: string) => {
    const out = await call("POST", { email });
    if (out) { setSentTo(String(out.sentTo ?? email)); setSentAt(Date.now()); }
    return !!out;
  }, [call]);
  const reset = React.useCallback(async (email: string, code: string, password: string) => {
    const out = await call("PUT", { email, code, password });
    if (out) setDone(true);
    return !!out;
  }, [call]);
  return { request, reset, pending, error, sentTo, sentAt, done };
}

/** Two-step sign-in for the signed-in person: `on` as it stands, `send()` a
 *  code to their own address, `confirm(code, on)` turns it on or off. */
export function useTwoStep() {
  const { update } = useSession();
  const [on, setOn] = React.useState<boolean | null>(null);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  React.useEffect(() => {
    let live = true;
    fetch(apiPath("/api/auth/two-step")).then((r) => (r.ok ? r.json() : null)).then((b) => {
      if (live && b && typeof b.on === "boolean") setOn(b.on);
    }).catch(() => undefined);
    return () => { live = false; };
  }, []);
  const send = React.useCallback(async () => {
    setPending(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/two-step"), { method: "POST" });
      const body = await res.json().catch(() => null) as { sentTo?: string; notice?: string } | null;
      if (!res.ok) { setError(messageOf(body, "The code could not be sent.")); return false; }
      setSentTo(body?.sentTo ?? null);
      setNotice(body?.notice ? `The code could not be emailed: ${body.notice}` : null);
      return true;
    } catch {
      setError("The code could not be sent — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, []);
  const confirm = React.useCallback(async (code: string, turnOn: boolean, remember = false) => {
    setPending(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/two-step"), { method: "PUT", headers: { "Content-Type": "application/json" },
                                                              body: JSON.stringify({ code, on: turnOn, remember }) });
      const body = await res.json().catch(() => null);
      if (!res.ok) { setError(messageOf(body, "That code could not be checked.")); return false; }
      setOn(turnOn);
      await update();
      return true;
    } catch {
      setError("The code could not be checked — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, [update]);
  return { on, send, confirm, pending, error, notice, sentTo };
}

export interface SignedInDevice { id: string; agent: string; at: string; via: string; current: boolean }

/** Where the signed-in person is signed in; `signOutOthers()` ends every
 *  other session (within thirty seconds), `signOut(id)` one of them. */
export function useSignedInDevices() {
  const [devices, setDevices] = React.useState<SignedInDevice[] | null>(null);
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const load = React.useCallback(async () => {
    try {
      const res = await fetch(apiPath("/api/auth/devices"));
      const body = await res.json().catch(() => null) as { devices?: SignedInDevice[] } | null;
      if (res.ok) setDevices(body?.devices ?? []);
    } catch { /* stays as it was */ }
  }, []);
  React.useEffect(() => { void load(); }, [load]);
  const end = React.useCallback(async (id?: string) => {
    setPending(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/devices" + (id ? `?id=${encodeURIComponent(id)}` : "")), { method: "DELETE" });
      const body = await res.json().catch(() => null);
      if (!res.ok) { setError(messageOf(body, "The other devices could not be signed out.")); return false; }
      await load();
      return true;
    } catch {
      setError("Check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, [load]);
  return { devices, signOutOthers: () => end(), signOut: (id: string) => end(id), pending, error, reload: load };
}

/** Create the account — and, when the application has one, the person's own
 *  record with it — then sign in and go where a new account goes first. */
export function useSignUp() {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const signUp = React.useCallback(async (input: { email: string; password: string; name?: string; account?: Record<string, unknown>;
                                                  accountType?: string; then?: string }) => {
    setPending(true);
    setError(null);
    try {
      const account = input.account ?? {};
      const label = ACCOUNT?.labelField ? account[ACCOUNT.labelField] : undefined;
      const res = await fetch(apiPath("/api/auth/signup"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: input.email, password: input.password,
                               name: input.name || (typeof label === "string" ? label : "") || input.email.split("@")[0],
                               account, ...(input.accountType ? { accountType: input.accountType } : {}) }),
      });
      if (!res.ok) {
        setError(messageOf(await res.json().catch(() => null), "Creating the account failed."));
        return false;
      }
      await signIn("credentials", { email: input.email, password: input.password, redirect: false });
      // Where this way in goes next (an employer's onboarding), else where a new account goes.
      router.push(input.then || AFTER_SIGNUP);
      router.refresh();
      return true;
    } catch {
      setError("Creating the account failed — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, [router]);
  return { signUp, pending, error };
}

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background " +
  "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
const labelClass = "text-sm font-medium leading-none";
const buttonClass =
  "inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary px-5 text-sm font-medium " +
  "text-primary-foreground shadow-sm transition hover:bg-primary/90 disabled:opacity-60";

function Spinner() {
  return <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />;
}

function Field({ id, label, required, children, help }: { id: string; label: string; required?: boolean; children: React.ReactNode; help?: string }) {
  return (
    <div className="grid gap-2">
      <label htmlFor={id} className={labelClass}>
        {label}{required && <span aria-hidden="true" className="ml-0.5 text-destructive">*</span>}
      </label>
      {children}
      {help && <p className="text-xs text-muted-foreground">{help}</p>}
    </div>
  );
}

/** How this application signs people in, as `/api/auth/methods` answers it:
 *  password, a magic link, and each identity provider with whether it is
 *  connected here. Until it answers, the password form (every app has had one). */
export interface SignInMethods {
  password: boolean;
  magicLink: boolean;
  sso: { id: string; name: string; kind: "oidc" | "saml"; connected: boolean }[];
}
const DEFAULT_METHODS: SignInMethods = { password: true, magicLink: false, sso: [] };

export function useSignInMethods(): SignInMethods {
  const [methods, setMethods] = React.useState<SignInMethods>(DEFAULT_METHODS);
  React.useEffect(() => {
    let live = true;
    fetch(apiPath("/api/auth/methods")).then((r) => (r.ok ? r.json() : null)).then((m) => {
      if (live && m && typeof m === "object") setMethods({ ...DEFAULT_METHODS, ...(m as SignInMethods) });
    }).catch(() => undefined);
    return () => { live = false; };
  }, []);
  return methods;
}

/** Continue with an identity provider the application declared (`signIn.sso`,
 *  offered only when `useSignInMethods()` says it is connected); the person
 *  comes back to `callbackUrl`, else the app's root, which sends them on to
 *  their role's own page. */
export function continueWith(providerId: string, callbackUrl?: string): void {
  void signIn(providerId, { callbackUrl: callbackUrl || apiPath("/") });
}

/** What a provider's refusal means, in words (`/login?error=…`). */
const SIGN_IN_ERRORS: Record<string, string> = {
  DomainNotAllowed: "That account's organisation is not one this application admits.",
  NotInvited: "That account has not been invited to this application yet.",
  NoEmail: "The identity provider did not say which email address you are.",
  AccessDenied: "You could not be signed in with that account.",
  OAuthSignin: "Signing in through the provider could not be started.",
  OAuthCallback: "Signing in through the provider did not complete.",
  Callback: "Signing in through the provider did not complete.",
  CredentialsSignin: "That sign-in link has expired or has already been used.",
};

/** A finished sign-in through a provider, or a magic link opened from an
 *  email: the person arrives at `/login` with a session (or `?magic=`), and
 *  goes where the signed-in role goes. */
function useArrival(setError: (s: string | null) => void) {
  const router = useRouter();
  const search = useSearchParams();
  const [finishing, setFinishing] = React.useState(false);
  React.useEffect(() => {
    const code = search?.get("error");
    if (code) setError(SIGN_IN_ERRORS[code] ?? "You could not be signed in.");
    const token = search?.get("magic");
    let live = true;
    (async () => {
      if (token) {
        setFinishing(true);
        const r = await signIn("magic", { token, redirect: false });
        if (!live) return;
        if (!r || r.error) { setError(SIGN_IN_ERRORS.CredentialsSignin); setFinishing(false); return; }
      } else if (code) {
        return;
      }
      const session = await getSession();
      if (!live || !session?.user) { setFinishing(false); return; }
      const role = String((session.user as { role?: unknown }).role ?? "");
      router.push(afterSignIn(search?.get("callbackUrl"), role || (await roleAfterSignIn(getSession))));
      router.refresh();
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return finishing;
}

/** "Email me a link": asks the app for a one-time sign-in link. */
export function useMagicLink() {
  const [pending, setPending] = React.useState(false);
  const [sent, setSent] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const request = React.useCallback(async (email: string) => {
    setPending(true); setError(null); setSent(null);
    try {
      const res = await fetch(apiPath("/api/auth/magic"), { method: "POST", headers: { "Content-Type": "application/json" },
                                                           body: JSON.stringify({ email }) });
      const body = await res.json().catch(() => null);
      if (!res.ok) { setError(messageOf(body, "The link could not be sent.")); return false; }
      setSent(String((body as { message?: string })?.message ?? "Check your email for a sign-in link.")
              + ((body as { notice?: string })?.notice ? ` (${(body as { notice: string }).notice})` : ""));
      return true;
    } catch {
      setError("The link could not be sent — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, []);
  return { request, pending, sent, error };
}

/** The code a new account proves its address with (`signIn.verifyEmail`):
 *  `send()` mails a fresh one to the signed-in person, `verify(code)` checks
 *  it and refreshes the session so the application opens to them. */
export function useEmailCode() {
  const { update } = useSession();
  const [sending, setSending] = React.useState(false);
  const [checking, setChecking] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [sentTo, setSentTo] = React.useState<string | null>(null);
  const send = React.useCallback(async () => {
    setSending(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/email-code"), { method: "POST" });
      const body = await res.json().catch(() => null) as { sentTo?: string; notice?: string; verified?: boolean } | null;
      if (!res.ok) { setError(messageOf(body, "The code could not be sent.")); return false; }
      setSentTo(body?.sentTo ?? null);
      setNotice(body?.notice ? `The code could not be emailed: ${body.notice}` : null);
      return true;
    } catch {
      setError("The code could not be sent — check your connection and try again.");
      return false;
    } finally {
      setSending(false);
    }
  }, []);
  const verify = React.useCallback(async (code: string) => {
    setChecking(true); setError(null);
    try {
      const res = await fetch(apiPath("/api/auth/email-code"), { method: "PUT", headers: { "Content-Type": "application/json" },
                                                                body: JSON.stringify({ code }) });
      const body = await res.json().catch(() => null);
      if (!res.ok) { setError(messageOf(body, "That code could not be checked.")); return false; }
      await update();
      return true;
    } catch {
      setError("The code could not be checked — check your connection and try again.");
      return false;
    } finally {
      setChecking(false);
    }
  }, [update]);
  return { send, verify, sending, checking, error, notice, sentTo };
}

const secondaryButtonClass =
  "inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-input bg-background px-5 text-sm " +
  "font-medium shadow-sm transition hover:bg-accent disabled:opacity-60";

/** The identity providers and the magic link, as buttons. Rendered inside
 *  `SignInForm`; place it alone on a page whose only way in is a provider. */
export function SignInMethods({ methods, email, className }: { methods?: SignInMethods; email?: string; className?: string }) {
  const fetched = useSignInMethods();
  const m = methods ?? fetched;
  const search = useSearchParams();
  const magic = useMagicLink();
  const [address, setAddress] = React.useState("");
  const callbackUrl = search?.get("callbackUrl") || "";
  const back = "/login" + (callbackUrl ? `?callbackUrl=${encodeURIComponent(callbackUrl)}` : "");
  if (!m.magicLink && m.sso.length === 0) return null;
  return (
    <div className={"grid gap-3 " + (className ?? "")}>
      {m.sso.map((p) => p.connected ? (
        <button key={p.id} type="button" className={secondaryButtonClass}
          onClick={() => void signIn(p.id, { callbackUrl: apiPath(back) })}>
          Continue with {p.name}
        </button>
      ) : (
        <p key={p.id} className="text-xs text-muted-foreground">Sign-in through {p.name} is not connected here yet.</p>
      ))}
      {m.magicLink && (
        <div className="grid gap-2">
          {!m.password && (
            <Field id="auth-magic-email" label="Email" required>
              <input id="auth-magic-email" type="email" autoComplete="email" className={inputClass}
                value={address} onChange={(e) => setAddress(e.target.value)} />
            </Field>
          )}
          <button type="button" disabled={magic.pending} className={secondaryButtonClass}
            onClick={() => void magic.request(email || address)}>
            {magic.pending && <Spinner />}Email me a sign-in link
          </button>
          {magic.sent && <p className="text-sm text-muted-foreground">{magic.sent}</p>}
          {magic.error && <p role="alert" className="text-sm text-destructive">{magic.error}</p>}
        </div>
      )}
    </div>
  );
}

/** The sign-in form: every way in this application offers — email and
 *  password, a link by email, the organisation's identity provider. Place
 *  it; style the page around it. */
export function SignInForm({ submitLabel = "Sign in", className }: { submitLabel?: string; className?: string }) {
  const { signIn: go, pending, error, step, stop, resend, restart } = useSignIn();
  const methods = useSignInMethods();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [arrivalError, setArrivalError] = React.useState<string | null>(null);
  const finishing = useArrival(setArrivalError);
  const shown = error ?? arrivalError;
  if (finishing) return <p className={"text-sm text-muted-foreground " + (className ?? "")}>Signing you in…</p>;
  if (step === "code") {
    return (
      <form className={"grid gap-5 " + (className ?? "")}
        onSubmit={(e) => { e.preventDefault(); void go(email, password, { code, remember }); }}>
        <p className="text-sm text-muted-foreground">We sent a 6-digit code to {stop?.sentTo ?? email}. It works for 10 minutes.</p>
        {stop?.notice && <p className="text-sm text-muted-foreground">The code could not be emailed: {stop.notice}</p>}
        <Field id="auth-code" label="Code" required>
          <input id="auth-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} required className={inputClass}
            value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Trust this browser for 30 days
        </label>
        {shown && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{shown}</p>}
        <button type="submit" disabled={pending || code.length !== 6} className={buttonClass}>{pending && <Spinner />}{submitLabel}</button>
        <div className="flex justify-between text-sm">
          <button type="button" className="text-muted-foreground underline" onClick={() => { setCode(""); restart(); }}>Back</button>
          <button type="button" className="text-primary underline" disabled={pending} onClick={() => { setCode(""); void resend(); }}>Send a new code</button>
        </div>
      </form>
    );
  }
  const others = methods.magicLink || methods.sso.length > 0;
  return (
    <form className={"grid gap-5 " + (className ?? "")}
      onSubmit={(e) => { e.preventDefault(); if (methods.password) void go(email, password); }}>
      {methods.password && (
        <>
          <Field id="auth-email" label="Email" required>
            <input id="auth-email" type="email" autoComplete="email" required className={inputClass}
              value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field id="auth-password" label="Password" required>
            <input id="auth-password" type="password" autoComplete="current-password" required className={inputClass}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
        </>
      )}
      {shown && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{shown}</p>}
      {methods.password && <button type="submit" disabled={pending} className={buttonClass}>{pending && <Spinner />}{submitLabel}</button>}
      {methods.password && <a href={apiPath("/reset-password")} className="text-center text-sm text-primary hover:underline">Forgot password?</a>}
      {others && (
        <>
          {methods.password && <p className="text-center text-xs text-muted-foreground">or</p>}
          <SignInMethods methods={methods} email={email} />
        </>
      )}
    </form>
  );
}

function AccountInput({ f, value, onChange }: { f: AccountField; value: unknown; onChange: (v: unknown) => void }) {
  const id = `auth-${f.name}`;
  if (f.kind === "checkbox") {
    return (
      <div className="flex items-start gap-3">
        <input id={id} type="checkbox" className="mt-0.5 h-4 w-4" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <label htmlFor={id} className={labelClass}>{f.label}</label>
      </div>
    );
  }
  let control: React.ReactNode;
  if (f.kind === "textarea") {
    control = <textarea id={id} rows={3} required={f.required} className={inputClass + " h-auto min-h-[80px]"}
      value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  } else if (f.kind === "select") {
    control = (
      <select id={id} required={f.required} className={inputClass} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose…</option>
        {(f.options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else {
    control = <input id={id} type={f.kind} required={f.required} className={inputClass}
      value={value === undefined || value === null ? "" : String(value)} onChange={(e) => onChange(e.target.value)} />;
  }
  return <Field id={id} label={f.label} required={f.required}>{control}</Field>;
}

/** The sign-up form: the person's own details (the account entity's fields),
 *  then email and password. Place it; style the page around it. */
export function SignUpForm({ submitLabel = "Create account", className, columns = 1 }: { submitLabel?: string; className?: string; columns?: 1 | 2 }) {
  const { signUp, pending, error } = useSignUp();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [account, setAccount] = React.useState<Record<string, unknown>>({});
  const askName = !ACCOUNT;
  return (
    <form className={"grid gap-5 " + (className ?? "")}
      onSubmit={(e) => { e.preventDefault(); void signUp({ email, password, name, account }); }}>
      <div className={"grid gap-5 " + (columns === 2 ? "sm:grid-cols-2" : "")}>
        {askName && (
          <Field id="auth-name" label="Name" required>
            <input id="auth-name" autoComplete="name" required className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
        )}
        {signupFields.map((f) => (
          <AccountInput key={f.name} f={f} value={account[f.name]}
            onChange={(v) => setAccount((cur) => ({ ...cur, [f.name]: v }))} />
        ))}
        <Field id="auth-email" label="Email" required>
          <input id="auth-email" type="email" autoComplete="email" required className={inputClass}
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field id="auth-password" label="Password" required help="At least 6 characters.">
          <input id="auth-password" type="password" autoComplete="new-password" required minLength={6} className={inputClass}
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </div>
      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      <button type="submit" disabled={pending} className={buttonClass}>{pending && <Spinner />}{submitLabel}</button>
    </form>
  );
}
