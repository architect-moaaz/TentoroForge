// Create an account - fixed, the same in every app (the Blueprint's own sign-up page is not drawn natively;
// this is it). It asks what the web's sign-up asks - the account entity's own fields when the application has
// one, a name when it does not, then email and password - sends them to `/api/auth/signup`, and signs the
// person in with the same session cookie the login uses. The rules are `src/sdk/signup.ts`.

import * as React from "react";
import { Linking } from "react-native";
import { Button, DateField, ErrorState, Loading, NumberField, Screen, SelectField, Stack, SwitchField, Text, TextField, Title } from "@/ui";
import { apiJson, appConfigured, appUrl, useNav, useSession, useSignInMethods } from "@/sdk";
import { MIN_PASSWORD, signUpFields, signUpRequest, validateSignUp } from "@/sdk/signup";
import { ACCOUNT, AFTER_SIGNUP, APP_NAME, CAN_SIGN_UP, HOME } from "@/config.generated";

export default function SignUp() {
  const nav = useNav();
  const { signIn } = useSession();
  const { methods, loading, error, retry } = useSignInMethods();
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [account, setAccount] = React.useState<Record<string, unknown>>({});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const [problem, setProblem] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);
  const set = (field: string) => (value: unknown) => setAccount((cur) => ({ ...cur, [field]: value }));

  if (!appConfigured) {
    return <Screen back={false}><ErrorState title="Not connected yet" message="This app does not know where its server is. It needs the deployed address (EXPO_PUBLIC_APP_URL)." /></Screen>;
  }
  if (loading) return <Screen back={false}><Loading /></Screen>;
  if (error || !methods) {
    return <Screen back={false}><ErrorState title="Cannot reach the app" message={error ?? "The sign-in options could not be read."} onRetry={retry} /></Screen>;
  }
  if (!CAN_SIGN_UP || !methods.password) {
    return (
      <Screen title="Create an account" back>
        <Stack gap="lg">
          <Text tone="muted">
            This app does not let people create an account on the phone. Ask the app's owner for an invitation, or use the web app.
          </Text>
          <Button variant="outline" onPress={() => { void Linking.openURL(appUrl("/signup")); }}>Open the web app</Button>
        </Stack>
      </Screen>
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
    <Screen title="Create your account" subtitle={APP_NAME} back>
      <Stack gap="lg">
        {!ACCOUNT ? <TextField label="Name" required value={name} onChange={setName} error={errors.name} /> : null}
        {signUpFields(ACCOUNT).map((f) => {
          const label = f.label;
          const error = errors[f.name];
          switch (f.kind) {
            case "number":
              return <NumberField key={f.name} label={label} required={f.required} value={account[f.name] as number | undefined} onChange={set(f.name)} error={error} />;
            case "date":
              return <DateField key={f.name} label={label} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
            case "select":
              return <SelectField key={f.name} label={label} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} options={f.options ?? []} error={error} />;
            case "checkbox":
              return <SwitchField key={f.name} label={label} value={Boolean(account[f.name])} onChange={set(f.name)} />;
            case "textarea":
              return <TextField key={f.name} label={label} kind="textarea" required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
            default:
              return <TextField key={f.name} label={label} kind={f.kind === "tel" || f.kind === "url" ? f.kind : "text"} required={f.required} value={account[f.name] as string | undefined} onChange={set(f.name)} error={error} />;
          }
        })}
        <TextField label="Email" kind="email" required value={email} onChange={setEmail} error={errors.email} />
        <TextField label="Password" kind="password" required help={`At least ${MIN_PASSWORD} characters.`} value={password} onChange={setPassword} error={errors.password} />
        {problem ? <Text tone="danger" accessibilityRole="alert">{problem}</Text> : null}
        <Button fullWidth loading={pending} onPress={() => { void submit(); }}>Create account</Button>
        <Button variant="ghost" fullWidth onPress={() => nav.replace("/login")}>I already have an account</Button>
      </Stack>
    </Screen>
  );
}
