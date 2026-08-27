import { z } from "zod";

export const NavFlowPageEntry = z.object({
  id: z.string(),
  route: z.string(),
  title: z.string(),
  schemaFile: z.string(),
  layout: z.string().optional(),
  guard: z.string().nullable().optional(),
  params: z.array(z.string()).default([]),
  /** When true (default), this route renders inside the app shell.
   *  Set to false for auth-style pages (login, signup, etc.) that
   *  should render bare with no nav chrome. */
  shell: z.boolean().default(true),
});

export const NavFlowTransition = z.object({
  id: z.string(),
  from: z.string(),
  trigger: z.string(),
  to: z.string(),
  params: z.record(z.unknown()).optional(),
});

export const NavFlowGuard = z.object({
  redirectTo: z.string(),
  condition: z.string(),
});

export const NavFlow = z.object({
  version: z.literal("1.0").default("1.0"),
  initialPage: z.string(),
  pages: z.array(NavFlowPageEntry),
  transitions: z.array(NavFlowTransition).default([]),
  guards: z.record(NavFlowGuard).default({}),
  /** Routes that bypass the app shell (auth pages). Derived from pages[].shell === false. */
  auth_routes: z.array(z.string()).default([]),
  /** After a successful auth.signIn / auth.signUp workflow, navigate here. */
  post_login_redirect: z.string().optional(),
  /** After auth.signOut workflow, navigate here. */
  post_logout_redirect: z.string().optional(),
});

export type NavFlowT = z.infer<typeof NavFlow>;
