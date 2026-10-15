// Create an account - the FALLBACK, the same in every app. The Blueprint's own sign-up page is drawn natively by
// the native engineer and replaces this file in the app; when it has not been, this is what a person gets. The
// form is `SignUpForm` (`src/ui/AuthForms.tsx`): it asks what the web's sign-up asks - the account entity's own
// fields when the application has one, a name when it does not, then email and password - sends them to
// `/api/auth/signup`, and signs the person in with the same session cookie the login uses.

import { AuthFrame, SignUpForm, SwitchAuthLink } from "@/ui";

export default function SignUp() {
  return (
    <AuthFrame title="Create your account" tagline="It takes a minute" footer={<SwitchAuthLink to="signin" />}>
      <SignUpForm />
    </AuthFrame>
  );
}
