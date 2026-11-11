"use client";
// Where a new account enters the code that proves its address
// (`signIn.verifyEmail`), when the application draws no code step of its own.
// The middleware sends an unproved account here with `next`, where it goes on.
// Forge runtime — do not remove.
import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEmailCode } from "@/sdk/auth";

export default function VerifyEmailPage() {
  const router = useRouter();
  const next = useSearchParams()?.get("next") || "/";
  const { data } = useSession();
  const email = String((data?.user as { email?: string } | undefined)?.email ?? "");
  const { send, verify, sending, checking, error, notice } = useEmailCode();
  const [code, setCode] = React.useState("");
  const asked = React.useRef(false);
  React.useEffect(() => {
    if (!asked.current) { asked.current = true; void send(); }
  }, [send]);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (await verify(code)) router.replace(next.startsWith("/") ? next : "/");
  };
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-md flex-col justify-center gap-6 px-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Check your email</h1>
        <p className="text-sm text-muted-foreground">Enter the 6-digit code we sent{email ? ` to ${email}` : ""}. It expires in 10 minutes.</p>
      </div>
      <form noValidate onSubmit={submit} className="flex flex-col gap-4">
        <label htmlFor="email-code" className="text-sm font-medium">Verification code</label>
        <input id="email-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          aria-invalid={error ? true : undefined} aria-describedby={error ? "email-code-error" : undefined}
          className="h-12 rounded-md border border-input bg-background px-3 text-center text-xl tracking-[0.5em]" />
        {error && <p id="email-code-error" role="alert" className="text-sm text-destructive">{error}</p>}
        {notice && <p className="text-sm text-muted-foreground">{notice}</p>}
        <button type="submit" disabled={checking || code.length !== 6}
          className="h-10 rounded-md bg-primary px-5 text-sm font-medium text-primary-foreground disabled:opacity-60">
          {checking ? "Checking…" : "Verify and continue"}
        </button>
        <button type="button" onClick={() => void send()} disabled={sending} className="text-sm text-primary underline-offset-4 hover:underline">
          {sending ? "Sending…" : "Send a new code"}
        </button>
      </form>
    </main>
  );
}
