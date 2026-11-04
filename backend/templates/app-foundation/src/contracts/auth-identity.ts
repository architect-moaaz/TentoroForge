// The scaffold's stand-in for the projected module of the same name.
//
// `project_shell_identity` writes this file from the Blueprint on every build,
// the way `brand.ts` is written, and for the same reason: the sign-in and
// sign-up pages carry "use client" and cannot read a file at render time, but
// they can import a constant the bundler inlines.
//
// IT IS A MODULE AND NOT A SUBSTITUTION BECAUSE A SUBSTITUTION HAPPENS ONCE.
// The sign-in page used to hold placeholder literals that the injector
// replaced at generation time. Once replaced a placeholder is gone, so a
// later change of the design had nothing left to write to and the page kept
// its first value for ever: Mark 8's design-dna chose `centered-minimal`
// and its login page still says `split-editorial`.
// Re-projected like tokens.css, this file is simply rewritten, so a design
// changed on turn fifty reaches the first screen as readily as on turn one.
//
// Listed in `assembly.SCAFFOLD_DEFAULTS`, so it is copied only into a tree the
// projection left without one; it never overwrites the real thing. Every
// field empty means "nothing stated" — the page falls back to the wording it
// has always had.
export type AuthIdentity = {
  /**
   * One of split-editorial | split-reversed | side-panel | centered-minimal |
   * brand-wash | top-anchored. Empty lets the page keep its own default.
   */
  layout: string;
  /** The brand half: what this product is, to someone not signed in yet. */
  headline: string;
  subhead: string;
  /** Over the form itself. */
  title: string;
  sub: string;
};

export const AUTH_IDENTITY: AuthIdentity = {
  layout: "",
  headline: "",
  subhead: "",
  title: "",
  sub: "",
};
