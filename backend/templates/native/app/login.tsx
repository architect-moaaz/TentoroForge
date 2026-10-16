// Sign in - the FALLBACK, the same in every app. The Blueprint's own sign-in page is drawn natively by the native
// engineer (its words, its band, its layout) and replaces this file in the app; when it has not been (no page,
// or it did not pass the checks) this is what a person gets. Either way the form is `SignInForm`: the only part
// that makes a session (`src/ui/AuthForms.tsx`), so a drawn frame cannot break the way in.

import { AuthFrame, LanguageSwitch, SignInForm, SwitchAuthLink } from "@/ui";
import { useT } from "@/sdk";

export default function Login() {
  const t = useT();
  return (
    <AuthFrame
      title={t({ en: "Welcome back" })}
      tagline={t({ en: "Sign in to continue" })}
      footer={(
        <>
          <SwitchAuthLink to="signup" />
          <LanguageSwitch />
        </>
      )}
    >
      <SignInForm />
    </AuthFrame>
  );
}
