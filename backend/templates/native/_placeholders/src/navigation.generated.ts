// PLACEHOLDER of the generated `src/navigation.generated.ts` — not copied into apps.
// The application's MAIN pages, in order, as bottom tabs: `name` is the route
// file's name inside `app/(tabs)/`, `icon` an Ionicons glyph. Empty when the
// application has fewer than two main pages (no tab bar is drawn then).

export const TABS: readonly { name: string; title: string; icon: string; route: string }[] = [
  { name: "index", title: "Home", icon: "home", route: "/" },
];

/** The main pages that do not fit the bar, listed on the More tab (empty when they all fit). */
export const MORE: readonly { title: string; icon: string; route: string }[] = [];

/** How a phone navigates: `tabs` (a bottom bar, plus a More tab when the main pages do not all fit) or `drawer` (a hamburger
 *  menu listing every main page). The Blueprint's `navigation.mobile`, else decided from the number of main pages. */
export const NAV_STYLE: "tabs" | "drawer" = "tabs";

/** The main pages (then Account, when the app has a sign-in), for the drawer's menu. Empty for a tab app. */
export const MENU: readonly { title: string; icon: string; route: string }[] = [];
