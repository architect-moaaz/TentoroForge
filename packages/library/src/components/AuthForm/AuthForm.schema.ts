import { z } from "zod";

/**
 * AuthForm — sign in or create an account.
 *
 * The one thing a schema-rendered page could not do. Every other form in the
 * library dispatches to a workflow, and authentication is not a workflow: it
 * exchanges credentials for a session. `signIn` appeared nowhere in the
 * library, renderer or runtime, so a generated login page rendered perfectly
 * and could not log anybody in.
 *
 * Implemented against the auth HTTP endpoints rather than by importing
 * next-auth, so the library stays a UI library with no framework dependency.
 * The credentials flow is a CSRF token fetch followed by a form post; that is
 * all `signIn("credentials", …)` does underneath.
 */
export const AuthFormProps = z
  .object({
    /** `signIn` exchanges credentials for a session; `signUp` creates an
     *  account first and then signs in, so a new user never lands on a login
     *  screen holding the password they just chose. */
    mode: z.enum(["signIn", "signUp"]).default("signIn"),
    submitLabel: z.string().optional(),
    /** Where to go once a session exists. Defaults to the app root. */
    successRoute: z.string().default("/"),
    /** Route of the opposite form, rendered as a footer link when set. */
    alternateRoute: z.string().optional(),
    alternateLabel: z.string().optional(),
    emailLabel: z.string().default("Email"),
    passwordLabel: z.string().default("Password"),
    nameLabel: z.string().default("Name"),
    className: z.string().optional(),
  })
  .strict();

export type AuthFormPropsType = z.infer<typeof AuthFormProps>;
