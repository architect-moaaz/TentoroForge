// The app SDK (native) - creating an account. The web's `useSignUp` (src/sdk/auth.tsx) in react-native-free
// parts, so the rules are testable under node: what a person must give, what is sent to `/api/auth/signup`,
// and what its refusals say in words. Signing in afterwards is `signInWithPassword` (signin.ts): the signup
// route creates the account and answers 201 with no session, exactly as it does for the web.
//
//   const problems = validateSignUp(input, ACCOUNT)       // field -> sentence, empty when it may be sent
//   const out = await signUpRequest(json, input, ACCOUNT)  // { ok: true } | { ok: false, field?, message }

import type { ApiResult, JsonInit } from "./http";

/** What the generated config says an account entity asks at signup (the web's `lib/account.ts`). */
export interface AccountShape {
  entity: string;
  fields: { name: string; label: string; kind: string; required: boolean; options?: { label: string; value: string }[] }[];
  labelField: string | null;
  locationField: string | null;
}

export interface SignUpInput {
  email: string;
  password: string;
  /** Asked only when the application has no account entity of its own. */
  name?: string;
  /** The account entity's own fields, by name. */
  account?: Record<string, unknown>;
}

export type SignUpOutcome = { ok: true } | { ok: false; reason: "taken" | "invalid" | "network" | "unavailable"; message: string };

export type JsonCall = <T = Record<string, unknown>>(path: string, init?: JsonInit) => Promise<ApiResult<T>>;

export const MIN_PASSWORD = 6;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** The fields a person types: the account entity's, without the email (which every account has). */
export function signUpFields(account: AccountShape | null): AccountShape["fields"] {
  return (account?.fields ?? []).filter((f) => f.kind !== "email");
}

/** Field -> a sentence in the person's words, for what the server would refuse. Empty: send it. */
export function validateSignUp(input: SignUpInput, account: AccountShape | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!account && !(input.name ?? "").trim()) out.name = "Enter your name.";
  for (const f of signUpFields(account)) {
    const v = input.account?.[f.name];
    const empty = v === undefined || v === null || v === "" || (typeof v === "number" && Number.isNaN(v));
    if (f.required && empty && f.kind !== "checkbox") out[f.name] = `${f.label} is required.`;
  }
  if (!input.email.trim()) out.email = "Enter your email address.";
  else if (!EMAIL.test(input.email.trim())) out.email = "That does not look like an email address.";
  if (!input.password) out.password = "Choose a password.";
  else if (input.password.length < MIN_PASSWORD) out.password = `Use at least ${MIN_PASSWORD} characters.`;
  return out;
}

/** What `/api/auth/signup` is sent: the web's body, to the letter. */
export function signUpBody(input: SignUpInput, account: AccountShape | null): Record<string, unknown> {
  const data = input.account ?? {};
  const label = account?.labelField ? data[account.labelField] : undefined;
  const email = input.email.trim();
  return {
    email,
    password: input.password,
    name: input.name?.trim() || (typeof label === "string" ? label : "") || email.split("@")[0],
    account: data,
  };
}

/** The refusal in words: `{ error: { message } }`, `{ error: "…" }`, or a sentence for the status. */
export function signUpMessage(res: ApiResult<unknown>): string {
  const error = (res.body as { error?: unknown } | null)?.error;
  if (typeof error === "string" && error) return error;
  const message = (error as { message?: unknown } | undefined)?.message;
  if (typeof message === "string" && message) return message;
  if (res.status === 409) return "That email is already registered. Sign in instead.";
  if (res.status === 404 || res.status === 405) return "This app does not let people create an account.";
  return "Creating the account failed. Try again in a moment.";
}

export async function signUpRequest(json: JsonCall, input: SignUpInput, account: AccountShape | null): Promise<SignUpOutcome> {
  const res = await json("/api/auth/signup", { method: "POST", body: signUpBody(input, account) });
  if (res.networkError) return { ok: false, reason: "network", message: res.networkError };
  if (res.ok) return { ok: true };
  const reason = res.status === 409 ? "taken" : res.status === 404 || res.status === 405 ? "unavailable" : "invalid";
  return { ok: false, reason, message: signUpMessage(res) };
}
