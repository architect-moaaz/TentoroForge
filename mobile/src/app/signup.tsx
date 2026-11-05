import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useRef, useState, type ComponentRef } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import { AuthShell, ErrorBox, EyeToggle, OrDivider, SwitchLine } from '@/components/auth-shell';
import { TextField } from '@/components/kit';
import { Button } from '@/components/ui';
import { useSession } from '@/lib/session';
import { icon, radius, space, type, useColors } from '@/theme';

// Same rules the server checks (backend/auth.py validate_password_strength),
// shown live so people fix the password before sending it.
const RULES: { label: string; ok: (p: string) => boolean }[] = [
  { label: '8+ characters', ok: (p) => p.length >= 8 },
  { label: 'Uppercase letter', ok: (p) => /[A-Z]/.test(p) },
  { label: 'Lowercase letter', ok: (p) => /[a-z]/.test(p) },
  { label: 'Number', ok: (p) => /\d/.test(p) },
];

export default function Signup() {
  const router = useRouter();
  const { signUp } = useSession();
  const colors = useColors();
  const emailRef = useRef<ComponentRef<typeof TextInput>>(null);
  const passwordRef = useRef<ComponentRef<typeof TextInput>>(null);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordOk = RULES.every((r) => r.ok(password));
  const ready = !!name.trim() && !!email.trim() && passwordOk;

  const submit = async () => {
    if (busy || !ready) return;
    setBusy(true);
    setError(null);
    try {
      // On success the session flips to signed-in and the gate shows the app.
      await signUp(name.trim(), email.trim(), password);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the account');
      setBusy(false);
    }
  };

  const edit = (set: (v: string) => void) => (v: string) => {
    set(v);
    setError(null);
  };

  return (
    <AuthShell title="Create account" subtitle="Build, change and ship apps with AI." onBack={() => router.back()}>
      {error ? <ErrorBox text={error} /> : null}

      <TextField
        label="Full name"
        icon="user"
        placeholder="Ada Lovelace"
        autoCapitalize="words"
        autoComplete="name"
        returnKeyType="next"
        submitBehavior="submit"
        onSubmitEditing={() => emailRef.current?.focus()}
        value={name}
        onChangeText={edit(setName)}
      />
      <TextField
        ref={emailRef}
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
        onChangeText={edit(setEmail)}
      />
      <View style={{ gap: space.md }}>
        <TextField
          ref={passwordRef}
          label="Password"
          icon="lock"
          placeholder="Make a strong password"
          secure={!showPassword}
          autoCapitalize="none"
          autoComplete="new-password"
          returnKeyType="go"
          value={password}
          onChangeText={edit(setPassword)}
          onSubmitEditing={submit}
          right={<EyeToggle shown={showPassword} onToggle={() => setShowPassword((s) => !s)} />}
        />
        <View style={styles.rules}>
          {RULES.map((r) => {
            const ok = r.ok(password);
            return (
              <View key={r.label} style={[styles.rule, { backgroundColor: ok ? colors.successBg : colors.muted }]}>
                <Feather name={ok ? 'check' : 'circle'} size={icon.sm - 2} color={ok ? colors.success : colors.textTertiary} />
                <Text style={[type.caption, { color: ok ? colors.success : colors.textSecondary }]}>{r.label}</Text>
              </View>
            );
          })}
        </View>
      </View>

      <Button
        label="Create account"
        busy={busy}
        disabled={!ready}
        onPress={submit}
        style={styles.submit}
        icon={(c) => <Feather name="arrow-right" size={16} color={c} />}
      />

      <OrDivider />
      <SwitchLine prompt="Already have an account?" action="Sign in" onPress={() => router.back()} />
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  submit: { minHeight: 52, borderRadius: radius.xl },
  rules: { flexDirection: 'row', flexWrap: 'wrap', gap: space.xs + 2 },
  rule: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: space.sm,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
});
