// The component kit - sign in and sign up. The web's `<SignInForm />` and `<SignUpForm />`, for the phone: the
// only parts that make a session or an account, so a screen that draws the FRAME of the sign-in or sign-up page
// (its words, its band, its layout) cannot break the way in.
//
//   <AuthFrame title="Welcome back" tagline="Sign in to continue" footer={<SwitchAuthLink to="signup" />}>
//     <SignInForm />
//   </AuthFrame>
//
// WHAT THEY HOLD, SO A SCREEN NEVER DOES: the app being configured, the sign-in options being read from
// `/api/auth/methods` (and said plainly when password sign-in is not offered: single sign-on and email links
// need a browser redirect), the fields and their validation, the cookie-session calls, and the sentence a
// refusal gets. Where the sign-in goes next is the root layout's: the session changed, and the gate moves on.

import * as React from "react";
import { Linking } from "react-native";
import { apiJson, appConfigured, appUrl, useNav, useSession, useSignInMethods } from "../sdk";
import { MIN_PASSWORD, signUpFields, signUpRequest, validateSignUp } from "../sdk/signup";
import { ACCOUNT, AFTER_SIGNUP, CAN_SIGN_UP, HOME } from "../config.generated";
import { Button } from "./Button";
import { DateField, NumberField, SelectField, SwitchField, TextField } from "./Fields";
import { Stack } from "./Layout";
import { ErrorState, Loading } from "./States";
import { Text } from "./Text";

/** What a form shows in place of itself until the app can be reached and says what it offers. */
function useReady(): { blocked: React.ReactNode | null; passwordOk: boolean; hasOtherWays: boolean } {
  const { methods, loading, error, retry } = useSignInMethods();
  if (!appConfigured) {
    return { passwordOk: false, hasOtherWays: false, blocked: (
      <ErrorState title="Not connected yet" message="This app does not know where its server is. It needs the deployed address (EXPO_PUBLIC_APP_URL) before anyone can sign in." />
    ) };
  }
  if (loading) return { passwordOk: false, hasOtherWays: false, blocked: <Loading /> };
  if (error || !methods) {
    return { passwordOk: false, hasOtherWays: false, blocked: <ErrorState title="Cannot reach the app" message={error ?? "The sign-in options could not be read."} onRetry={retry} /> };
  }
  return { blocked: null, passwordOk: methods.password, hasOtherWays: methods.sso.length > 0 || methods.magicLink };
}

export interface AuthFormProps {
  /** The button's words. */
  submitLabel?: string;
}

/** Email and password, through the app's next-auth cookie flow. */
export function SignInForm({ submitLabel = "Sign in" }: AuthFormProps) {
  const { signIn } = useSession();
  const { methods } = useSignInMethods();
  const ready = useReady();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [problem, setProblem] = React.useState<string | null>(null);
  const [errors, setErrors] = React.useState<{ email?: string; password?: string }>({});
  const [pending, setPending] = React.useState(false);

  if (ready.blocked) return <>{ready.blocked}</>;
  if (!ready.passwordOk) {
    const providers = (methods?.sso ?? []).filter((s) => s.connected).map((s) => s.name);
    return (
      <Stack gap="md">
        <Text variant="heading">Password sign-in is not available</Text>
        <Text tone="muted">
          This app does not let people sign in with an email and password, and the phone app can only do that.{" "}
          {providers.length ? `It offers ${providers.join(", ")}, which open in a browser. ` : methods?.magicLink ? "It offers an email link, which opens in a browser. " : ""}
          Ask the app&apos;s owner to switch password sign-in on, or use the web app.
        </Text>
        <Button variant="outline" onPress={() => { void Linking.openURL(appUrl("/login")); }}>Open the web app</Button>
      </Stack>
    );
  }

  const submit = async () => {
    const found: { email?: string; password?: string } = {};
    if (!email.trim()) found.email = "Enter your email address.";
    if (!password) found.password = "Enter your password.";
    setErrors(found);
    if (found.email || found.password) return;
    setPending(true);
    setProblem(null);
    const out = await signIn(email, password);
    setPending(false);
    // On success the root layout moves on: the session changed.
    if (!out.ok) setProblem(out.message);
  };

  return (
    <Stack gap="lg">
      <TextField label="Email" kind="email" icon="mail-outline" value={email} onChange={setEmail} error={errors.email} />
      <TextField label="Password" kind="password" icon="lock-closed-outline" value={password} onChange={setPassword} error={errors.password} />
      {problem ? <Text tone="danger" accessibilityRole="alert">{problem}</Text> : null}
      <Button fullWidth loading={pending} onPress={() => { void submit(); }}>{submitLabel}</Button>
      {ready.hasOtherWays ? (
        <Text variant="caption" tone="muted">Other ways to sign in (single sign-on, email links) are available on the web only.</Text>
      ) : null}
    </Stack>
  );
}

/** The account entity's own fields (or a name), then email and password; makes the account, then signs in. */
export function SignUpForm({ submitLabel = "Create account" }: AuthFormProps) {
  const nav = useNav();
  const { signIn } = useSession();
  const ready = useReady();
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [account, setAccount] = React.useState<Record<string, unknown>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [problem, setProblem] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);
  const set = (field: string) => (value: unknown) => setAccount((cur) => ({ ...cur, [field]: value }));

  if (ready.blocked) return <>{ready.blocked}</>;
  if (!CAN_SIGN_UP || !ready.passwordOk) {
    return (
      <Stack gap="md">
        <Text tone="muted">
          This app does not let people create an account on the phone. Ask the app&apos;s owner for an invitation, or use the web app.
        </Text>
        <Button variant="outline" onPress={() => { void Linking.openURL(appUrl("/signup")); }}>Open the web app</Button>
      </Stack>
    );
  }

  const submit = async () => {
    const found = validateSignUp({ email, password, name, account }, ACCOUNT);
    setErrors(found);
    if (Object.keys(found).length) return;
    setPending(true);
    setProblem(null);
    const made = await signUpRequest(apiJson, { email, password, name, account }, ACCOUNT);
    if (!made.ok) {
      setPending(false);
      setProblem(made.message);
      return;
    }
    const signed = await signIn(email.trim(), password);
    setPending(false);
    if (!signed.ok) {
      setProblem("Your account is ready, but signing in failed: " + signed.message);
      return;
    }
    // The sign-in gate leaves this screen; a new account that has a first step (a profile to complete) goes there.
    if (AFTER_SIGNUP !== HOME) nav.replace(AFTER_SIGNUP);
  };

  return (
    <Stack gap="lg">
      {!ACCOUNT ? <TextField label="Name" required value={name} onChange={setName} error={errors.name} /> : null}
      {signUpFields(ACCOUNT).map((f) => {
        const error = errors[f.name];
        switch (f.kind) {
          case "number":
            return <NumberField key={f.name} label={f.label} required={f.required} value={account[f.name] as number | undefined} onChange={set(f.name)} error={error} />;
          case "date":
            return <DateField key={f.name} label={f.label} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
          case "select":
            return <SelectField key={f.name} label={f.label} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} options={f.options ?? []} error={error} />;
          case "checkbox":
            return <SwitchField key={f.name} label={f.label} value={Boolean(account[f.name])} onChange={set(f.name)} />;
          case "textarea":
            return <TextField key={f.name} label={f.label} kind="textarea" required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
          default:
            return <TextField key={f.name} label={f.label} kind={f.kind === "tel" || f.kind === "url" ? f.kind : "text"} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
        }
      })}
      <TextField label="Email" kind="email" icon="mail-outline" required value={email} onChange={setEmail} error={errors.email} />
      <TextField label="Password" kind="password" icon="lock-closed-outline" required help={`At least ${MIN_PASSWORD} characters.`} value={password} onChange={setPassword} error={errors.password} />
      {problem ? <Text tone="danger" accessibilityRole="alert">{problem}</Text> : null}
      <Button fullWidth loading={pending} onPress={() => { void submit(); }}>{submitLabel}</Button>
    </Stack>
  );
}

/** The link between the two screens: to sign up (only where the app lets people), or back to sign in. */
export function SwitchAuthLink({ to, children }: { to: "signin" | "signup"; children?: React.ReactNode }) {
  const nav = useNav();
  if (to === "signup" && !CAN_SIGN_UP) return null;
  const label = children ?? (to === "signup" ? "New here? Create an account" : "I already have an account");
  return <Button variant="ghost" fullWidth onPress={() => (to === "signup" ? nav.push("/signup") : nav.replace("/login"))}>{label}</Button>;
}
