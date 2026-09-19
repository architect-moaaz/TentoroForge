"use client";
// The app SDK — signing in and creating an account. How an `auth` page's
// `view.tsx` signs a person in or creates their account: the logic is fixed
// here (NextAuth credentials, the signup route, the account's own fields from
// `@/lib/account`); the page around it is the UI engineer's to design.

import * as React from "react";
import { signIn } from "next-auth/react";
import { useRouter, useSearchParams } from "next/navigation";
import { ACCOUNT, AFTER_SIGNUP, HOME, type AccountField } from "@/lib/account";

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

/** Sign in with email and password; lands on `?callbackUrl=` or the app's home. */
export function useSignIn() {
  const router = useRouter();
  const search = useSearchParams();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const signInWith = React.useCallback(async (email: string, password: string) => {
    setPending(true);
    setError(null);
    try {
      const r = await signIn("credentials", { email, password, redirect: false });
      if (!r || r.error) { setError("That email and password do not match an account."); return false; }
      router.push(search?.get("callbackUrl") || HOME);
      router.refresh();
      return true;
    } catch {
      setError("Signing in failed — check your connection and try again.");
      return false;
    } finally {
      setPending(false);
    }
  }, [router, search]);
  return { signIn: signInWith, pending, error };
}

/** Create the account — and, when the application has one, the person's own
 *  record with it — then sign in and go where a new account goes first. */
export function useSignUp() {
  const router = useRouter();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const signUp = React.useCallback(async (input: { email: string; password: string; name?: string; account?: Record<string, unknown> }) => {
    setPending(true);
    setError(null);
    try {
      const account = input.account ?? {};
      const label = ACCOUNT?.labelField ? account[ACCOUNT.labelField] : undefined;
      const res = await fetch("/api/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: input.email, password: input.password,
                               name: input.name || (typeof label === "string" ? label : "") || input.email.split("@")[0],
                               account }),
      });
      if (!res.ok) {
        setError(messageOf(await res.json().catch(() => null), "Creating the account failed."));
        return false;
      }
      await signIn("credentials", { email: input.email, password: input.password, redirect: false });
      router.push(AFTER_SIGNUP);
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

/** The sign-in form: email, password, submit. Place it; style the page around it. */
export function SignInForm({ submitLabel = "Sign in", className }: { submitLabel?: string; className?: string }) {
  const { signIn: go, pending, error } = useSignIn();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  return (
    <form className={"grid gap-5 " + (className ?? "")}
      onSubmit={(e) => { e.preventDefault(); void go(email, password); }}>
      <Field id="auth-email" label="Email" required>
        <input id="auth-email" type="email" autoComplete="email" required className={inputClass}
          value={email} onChange={(e) => setEmail(e.target.value)} />
      </Field>
      <Field id="auth-password" label="Password" required>
        <input id="auth-password" type="password" autoComplete="current-password" required className={inputClass}
          value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      <button type="submit" disabled={pending} className={buttonClass}>{pending && <Spinner />}{submitLabel}</button>
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
