import { AppShellSkeleton } from "@/components/PageSkeleton";

/**
 * App-level loading state.
 *
 * Rendered while the App Router prepares a layout: a full page load, signing out, and the move
 * from the sign-in page into the app (which has to load the signed-in layout first). It is the
 * shape of the app, a rail and a page area, so the window fills in rather than showing a card
 * in the middle of nothing. Routes inside the signed-in shell have their own, shaped like the
 * page (`(dashboard)/loading.tsx` and each coded page's).
 */
export default function Loading() {
  return <AppShellSkeleton />;
}
