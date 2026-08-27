"use client";

import * as React from "react";

import type { AuthFormPropsType } from "./AuthForm.schema";

/** The credentials flow, without importing the auth framework.
 *
 * `signIn("credentials", …)` posts a CSRF token and the credentials to the
 * callback endpoint; doing it directly keeps this a plain UI component. */
async function signInWithCredentials(
  email: string,
  password: string,
  successRoute: string,
): Promise<string | null> {
  const csrfRes = await fetch("/api/auth/csrf");
  const { csrfToken } = await csrfRes.json();

  const body = new URLSearchParams({
    csrfToken,
    email,
    password,
    callbackUrl: successRoute,
    json: "true",
  });
  const res = await fetch("/api/auth/callback/credentials", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    redirect: "follow",
  });

  // The callback answers 200 with a url on success and redirects to an error
  // page otherwise; both shapes are checked because which one appears depends
  // on the auth version.
  const text = await res.text();
  if (!res.ok || text.includes("error=CredentialsSignin")) {
    return "That email and password did not match.";
  }
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.url === "string" && parsed.url.includes("error=")) {
      return "That email and password did not match.";
    }
  } catch {
    /* a non-JSON body is the redirect form, which means success */
  }
  return null;
}

export function AuthForm(props: AuthFormPropsType) {
  const {
    mode = "signIn",
    submitLabel,
    successRoute = "/",
    alternateRoute,
    alternateLabel,
    emailLabel = "Email",
    passwordLabel = "Password",
    nameLabel = "Name",
    className,
  } = props ?? ({} as AuthFormPropsType);

  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "signUp") {
        const res = await fetch("/api/auth/signup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, email, password }),
        });
        if (!res.ok) {
          const payload = await res.json().catch(() => null);
          setError(payload?.error?.message ?? "Could not create that account.");
          return;
        }
      }
      // Sign up then sign in, so a new account never bounces to a login form.
      const failure = await signInWithCredentials(email, password, successRoute);
      if (failure) {
        setError(failure);
        return;
      }
      window.location.assign(successRoute);
    } catch {
      setError("Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const label = submitLabel ?? (mode === "signUp" ? "Create account" : "Sign in");

  return (
    <form onSubmit={onSubmit} className={className} data-auth-form={mode}>
      {mode === "signUp" && (
        <label>
          <span>{nameLabel}</span>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            required
          />
        </label>
      )}
      <label>
        <span>{emailLabel}</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
      </label>
      <label>
        <span>{passwordLabel}</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={mode === "signUp" ? "new-password" : "current-password"}
          required
        />
      </label>

      {error && <p role="alert">{error}</p>}

      <button type="submit" disabled={busy}>
        {busy ? "Working…" : label}
      </button>

      {alternateRoute && (
        <p>
          <a href={alternateRoute}>{alternateLabel ?? "Use another option"}</a>
        </p>
      )}
    </form>
  );
}
