import { z } from "zod";


/**
 * AuthForm — sign in or create an account.
 *
 * Defined here rather than in the library because that is the direction the
 * package graph runs: `library` imports `schema`, never the reverse, and 69 of
 * the library's props schemas already read `SomethingNode.shape.props` off a
 * node defined in this package. Putting the shape here and deriving the
 * component's props from it is what keeps one definition instead of two that
 * drift — which is exactly how AuthForm came to be renderable by the registry
 * and rejected by the schema at the same time.
 */
export const AuthFormNode = z.object({
  id: z.string().min(1).optional(),
  type: z.literal("AuthForm"),
  props: z
    .object({
      /** `signIn` exchanges credentials for a session; `signUp` creates the
       *  account and then signs in, so a new user never lands on a login form
       *  holding the password they just chose. */
      mode: z.enum(["signIn", "signUp"]).default("signIn"),
      submitLabel: z.string().optional(),
      /** Where to go once a session exists. */
      successRoute: z.string().default("/"),
      /** Route of the opposite form, rendered as a footer link when set. */
      alternateRoute: z.string().optional(),
      alternateLabel: z.string().optional(),
      emailLabel: z.string().default("Email"),
      passwordLabel: z.string().default("Password"),
      nameLabel: z.string().default("Name"),
      className: z.string().optional(),
    })
    .default({}),
});
