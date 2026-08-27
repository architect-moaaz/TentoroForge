import { z } from "zod";
import { AuthFormNode } from "@tentoroforge/schema";

/**
 * AuthForm — sign in or create an account.
 *
 * Derived from `AuthFormNode` rather than declared again, the way 69 of this
 * library's props schemas already are. Two independent declarations of the same
 * props is precisely how this component came to be renderable by the runtime
 * registry and rejected by the page schema at the same time — registered,
 * catalogued, authored, projected, and then silently dropped at render with a
 * console warning as the only trace.
 *
 * The component itself is implemented against the auth HTTP endpoints rather
 * than by importing next-auth, so the library stays a UI library with no
 * framework dependency. The credentials flow is a CSRF fetch followed by a form
 * post; that is all `signIn("credentials", …)` does underneath.
 */
export const AuthFormProps = AuthFormNode.shape.props;

export type AuthFormPropsType = z.infer<typeof AuthFormProps>;
