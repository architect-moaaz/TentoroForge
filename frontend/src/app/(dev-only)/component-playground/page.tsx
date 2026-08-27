"use client";

/**
 * Component playground — renders every library component in known states.
 * Used by:
 *   - apps/visual-regression for screenshot diffing
 *   - Manual QA when refactoring components
 *
 * URL: http://localhost:6501/component-playground
 *
 * Each component group is wrapped in <section data-component="X"> so the
 * regression suite can target snapshots per-component.
 *
 * Loaded with ssr:false because the library bundle pulls in
 * isomorphic-dompurify (via renderer primitives), which tries to read a CSS
 * file that only exists in a browser build.
 */
import dynamic from "next/dynamic";

const PlaygroundInner = dynamic(
  () => import("./PlaygroundInner"),
  { ssr: false }
);

export default function ComponentPlayground() {
  return <PlaygroundInner />;
}
