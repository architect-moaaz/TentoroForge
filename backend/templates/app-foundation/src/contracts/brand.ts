// The scaffold's stand-in for the projected module of the same name.
//
// `project_brand_logo` writes this file from the Blueprint on every build, and
// what it writes is the application's. This copy exists for the case where
// that projection did not run at all — a crash, a timeout, an export taken
// mid-build — because the pages that import it are the sign-in screen and the
// error pages, and an import of a file the tree does not contain does not fail
// a page, it fails the build. The floor is a plain-looking application, not an
// unbuildable one.
//
// Listed in `assembly.SCAFFOLD_DEFAULTS`, so it is copied only into a tree the
// projection left without one; it never overwrites the real thing.
export type BrandLogo = {
  /** Served from the app's own `public/`. */
  src: string;
  /** The application's name unless the owner said otherwise. */
  alt: string;
  /** width / height of the source image, when it could be measured. */
  aspect?: number;
};

export const BRAND_LOGO: BrandLogo | null = null;
