// Sign in — fixed, the same in every app (the Blueprint's own sign-in page is
// not drawn natively; this is it). Email and password, through the app's
// next-auth cookie flow (src/sdk/signin.ts).
//
// It reads `/api/auth/methods` FIRST and says so plainly when password sign-in
// is not offered: single sign-on and email links need a browser redirect, which
// the app does not do, and showing a form that cannot work would only teach the
// person that the app is broken.

import * as React from "react";
import { Linking } from "react-native";
import { Button, ErrorState, LanguageSwitch, Loading, Screen, Stack, Text, TextField, Title } from "@/ui";
import { appConfigured, appUrl, useSession, useSignInMethods, useT } from "@/sdk";
import { APP_NAME } from "@/config.generated";

export default function Login() {
  const t = useT();
  const { signIn } = useSession();
  const { methods, loading, error, retry } = useSignInMethods();
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [problem, setProblem] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<{ email?: string; password?: string }>({});
  const [pending, setPending] = React.useState(false);

  if (!appConfigured) {
    return <Screen back={false}><ErrorState title="Not connected yet" message="This app does not know where its server is. It needs the deployed address (EXPO_PUBLIC_APP_URL) before anyone can sign in." /></Screen>;
  }
  if (loading) return <Screen back={false}><Loading /></Screen>;
  if (error || !methods) {
    return <Screen back={false}><ErrorState title="Cannot reach the app" message={error ?? "The sign-in options could not be read."} onRetry={retry} /></Screen>;
  }

  if (!methods.password) {
    const providers = methods.sso.filter((s) => s.connected).map((s) => s.name);
    return (
      <Screen back={false}>
        <Stack gap="lg">
          <Title>{APP_NAME}</Title>
          <Text variant="heading">Password sign-in is not available</Text>
          <Text tone="muted">
            This app does not let people sign in with an email and password, and the phone app can only do that.{" "}
            {providers.length ? `It offers ${providers.join(", ")}, which open in a browser. ` : methods.magicLink ? "It offers an email link, which opens in a browser. " : ""}
            Ask the app's owner to switch password sign-in on, or use the web app.
          </Text>
          <Button variant="outline" onPress={() => { void Linking.openURL(appUrl("/login")); }}>Open the web app</Button>
        </Stack>
      </Screen>
    );
  }

  const submit = async () => {
    const found: { email?: string; password?: string } = {};
    if (!email.trim()) found.email = "Enter your email address.";
    if (!password) found.password = "Enter your password.";
    setFieldErrors(found);
    if (found.email || found.password) return;
    setPending(true);
    setProblem(null);
    const out = await signIn(email, password);
    setPending(false);
    // On success the root layout moves on: the session changed.
    if (!out.ok) setProblem(out.message);
  };

  return (
    <Screen back={false}>
      <Stack gap="xl">
        <Stack gap="xs">
          <Title>{APP_NAME}</Title>
          <Text tone="muted">{t({ en: "Sign in to continue" })}</Text>
        </Stack>
        <Stack gap="lg">
          <TextField label="Email" kind="email" value={email} onChange={setEmail} error={fieldErrors.email} />
          <TextField label="Password" kind="password" value={password} onChange={setPassword} error={fieldErrors.password} />
          {problem ? <Text tone="danger" accessibilityRole="alert">{problem}</Text> : null}
          <Button fullWidth loading={pending} onPress={() => { void submit(); }}>Sign in</Button>
        </Stack>
        {methods.sso.length || methods.magicLink ? (
          <Text variant="caption" tone="muted">Other ways to sign in (single sign-on, email links) are available on the web only.</Text>
        ) : null}
        <LanguageSwitch />
      </Stack>
    </Screen>
  );
}
