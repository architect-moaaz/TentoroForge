// The scaffold's stand-in for the projected module of the same name.
//
// `project_public_routes` writes this file from the Blueprint on every build:
// the application's name and the public pages a visitor can move between. This
// copy exists for a tree that projection never reached, because
// `PublicPageFrame` imports it and an import of a missing file fails the build.
// Listed in `assembly.SCAFFOLD_DEFAULTS`; it never overwrites the real thing.
export type PublicNavItem = { label: string; route: string };

export const PUBLIC_NAV: {
  appName: string;
  items: PublicNavItem[];
  /** The app also has pages behind sign-in. */
  signIn: boolean;
} = { appName: "", items: [], signIn: false };
