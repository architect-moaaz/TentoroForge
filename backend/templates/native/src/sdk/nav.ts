// The app SDK (native) — moving between screens. Navigation is expo-router, and
// a screen's address is what the web's `href()` builds: `href(pages.orderDetail,
// { id })` -> "/orders/42?tab=items". This is the web's `useRouter().push(...)`
// and `params` with the same strings, so a screen says where to go the way a
// web page does.
//
//   const nav = useNav();            nav.push(href(pages.orderDetail, { id: row.id }));
//   const { id } = useParams<{ id: string }>();

import { useRouter, useLocalSearchParams, type Href } from "expo-router";

export interface Nav {
  /** Open a route on top of this screen. */
  push: (to: string) => void;
  /** Open a route instead of this screen (after sign-in, after a create). */
  replace: (to: string) => void;
  /** Back one screen; the app's home when there is nowhere to go back to. */
  back: () => void;
  canGoBack: () => boolean;
}

export function useNav(): Nav {
  const router = useRouter();
  return {
    push: (to) => router.push(to as Href),
    replace: (to) => router.replace(to as Href),
    back: () => { if (router.canGoBack()) router.back(); else router.replace("/" as Href); },
    canGoBack: () => router.canGoBack(),
  };
}

/** The route's own parameters (`[id]`) and its query string, as strings. */
export function useParams<P extends Record<string, string | undefined> = Record<string, string | undefined>>(): P {
  const raw = useLocalSearchParams();
  // A repeated query key arrives as a list; a screen reads one value.
  const out: Record<string, string | undefined> = {};
  for (const [k, v] of Object.entries(raw)) out[k] = Array.isArray(v) ? v[0] : v;
  return out as P;
}
