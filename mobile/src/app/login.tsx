import { Feather } from '@expo/vector-icons';
import { useRouter, type Href } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useMemo, useRef, useState, type ComponentRef } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { AuthShell, ErrorBox, EyeToggle, OrDivider, SwitchLine } from '@/components/auth-shell';
import { Sheet, TextField } from '@/components/kit';
import { Button } from '@/components/ui';
import { errorText, postJson } from '@/lib/api';
import { useSession } from '@/lib/session';
import { radius, space, type, useColors, type Palette } from '@/theme';

export default function Login() {
  const router = useRouter();
  const { signIn } = useSession();
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const passwordRef = useRef<ComponentRef<typeof TextInput>>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forgotOpen, setForgotOpen] = useState(false);

  const submit = async () => {
    if (busy || !email.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sign in');
      setBusy(false);
    }
  };

  return (
    <AuthShell title="Welcome back" subtitle="Your AI app workspace, in your pocket.">
      {error ? <ErrorBox text={error} /> : null}

      <TextField
        label="Email"
        icon="mail"
        placeholder="you@company.com"
        autoCapitalize="none"
        autoComplete="email"
        keyboardType="email-address"
        returnKeyType="next"
        submitBehavior="submit"
        onSubmitEditing={() => passwordRef.current?.focus()}
        value={email}
        onChangeText={(v) => {
          setEmail(v);
          setError(null);
        }}
      />
      <View style={{ gap: space.md }}>
        <TextField
          ref={passwordRef}
          label="Password"
          icon="lock"
          placeholder="Your password"
          secure={!showPassword}
          autoCapitalize="none"
          autoComplete="password"
          returnKeyType="go"
          value={password}
          onChangeText={(v) => {
            setPassword(v);
            setError(null);
          }}
          onSubmitEditing={submit}
          right={<EyeToggle shown={showPassword} onToggle={() => setShowPassword((s) => !s)} />}
        />
        <Pressable onPress={() => setForgotOpen(true)} hitSlop={8} style={{ alignSelf: 'flex-end' }}>
          <Text style={styles.link}>Forgot password?</Text>
        </Pressable>
      </View>

      <Button
        label="Sign in"
        busy={busy}
        disabled={!email.trim() || !password}
        onPress={submit}
        style={styles.submit}
        icon={(c) => <Feather name="arrow-right" size={16} color={c} />}
      />

      <OrDivider />
      <SwitchLine prompt="New to Tentoro?" action="Create an account" onPress={() => router.push('/signup' as Href)} />

      <ForgotSheet visible={forgotOpen} initialEmail={email} onClose={() => setForgotOpen(false)} />
    </AuthShell>
  );
}

/** Asks the server for a reset link. Until email is wired, the server may hand the link back; then we open it. */
function ForgotSheet({ visible, initialEmail, onClose }: { visible: boolean; initialEmail: string; onClose: () => void }) {
  const colors = useColors();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [email, setEmail] = useState(initialEmail);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ message: string; url?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const close = () => {
    setDone(null);
    setError(null);
    onClose();
  };

  const send = async () => {
    if (busy || !email.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await postJson<{ message: string; reset_url?: string | null }>('/api/auth/forgot-password', {
        email: email.trim(),
      });
      setDone({ message: res.message, url: res.reset_url ?? undefined });
    } catch (e) {
      setError(e instanceof Error ? e.message : errorText(null, 'Could not send the link'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={visible} onClose={close} title="Reset password">
      <View style={{ gap: space.lg }}>
        {done ? (
          <>
            <Text style={styles.sheetText}>{done.message}</Text>
            {done.url ? (
              <Button
                label="Open reset page"
                onPress={() => WebBrowser.openBrowserAsync(done.url!)}
                style={styles.submit}
                icon={(c) => <Feather name="external-link" size={16} color={c} />}
              />
            ) : null}
            <Button label="Done" tone="outline" onPress={close} style={styles.submit} />
          </>
        ) : (
          <>
            <Text style={styles.sheetText}>Enter your email and we will make a link to set a new password.</Text>
            {error ? <ErrorBox text={error} /> : null}
            <TextField
              label="Email"
              icon="mail"
              placeholder="you@company.com"
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              returnKeyType="send"
              value={email}
              onChangeText={setEmail}
              onSubmitEditing={send}
            />
            <Button label="Send reset link" busy={busy} disabled={!email.trim()} onPress={send} style={styles.submit} />
          </>
        )}
      </View>
    </Sheet>
  );
}

const makeStyles = (colors: Palette) =>
  StyleSheet.create({
    link: { ...type.callout, fontFamily: 'Inter_500Medium', color: colors.brand },
    submit: { minHeight: 52, borderRadius: radius.xl },
    sheetText: { ...type.body, color: colors.textSecondary },
  });
