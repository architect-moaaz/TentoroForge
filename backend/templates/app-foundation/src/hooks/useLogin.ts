"use client";

import { useState } from "react";
import { getSession, signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { afterSignIn, roleAfterSignIn } from "@/lib/landing";
import { stopMessage, type SignInStop } from "@/sdk/auth";

/**
 * The sign-in form's state. Past the password the platform may stop short of
 * a session (`lib/sign-in-guard.ts`): the address is paused after five wrong
 * passwords, or the person turned two-step on and a code was emailed. Then
 * `step` is "code": the same form comes back with `code` (and `remember` to
 * trust this browser for thirty days).
 */
export function useLogin(callbackUrl: string = "/dashboard") {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [remember, setRemember] = useState(true);
  const [step, setStep] = useState<"password" | "code">("password");
  const [stop, setStop] = useState<SignInStop | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();

  const attempt = async (withCode: boolean) => {
    setIsLoading(true);
    setError("");
    try {
      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
        ...(withCode ? { code, remember: remember ? "true" : "false" } : {}),
      });

      if (result?.error) {
        let s: SignInStop | null = null;
        try { s = result.error.startsWith("{") ? JSON.parse(result.error) : null; } catch { s = null; }
        setStop(s);
        if (s && s.code !== "SIGN_IN_PAUSED") setStep("code");
        setError(s ? stopMessage(s) ?? "" : "Invalid email or password");
      } else if (result?.ok) {
        // Every role to its own page — the template's sign-in sent everyone
        // to "/" (`lib/landing.ts`).
        router.push(afterSignIn(callbackUrl, await roleAfterSignIn(getSession)));
        router.refresh();
      }
    } catch {
      setError("An error occurred during login");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await attempt(step === "code");
  };
  /** A new code: the password again, without one. */
  const resend = () => { setCode(""); void attempt(false); };
  const back = () => { setStep("password"); setStop(null); setCode(""); setError(""); };

  return { email, setEmail, password, setPassword, code, setCode, remember, setRemember, step, stop, error, isLoading, handleSubmit, resend, back };
}
