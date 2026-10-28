import { PageSkeleton } from "@/components/PageSkeleton";

/**
 * Loading state for every page inside the signed-in shell.
 *
 * Next shows the nearest `loading.tsx` while a route's data is read. The root
 * one (`app/loading.tsx`) replaces the whole window; this one sits inside the
 * shell's layout, so the sidebar and top bar stay and only the page area is a
 * placeholder. A coded page ships its own, shaped like the page
 * (`app_sdk.loading_module`); this is what a page without one gets.
 */
export default function Loading() {
  return <PageSkeleton />;
}
