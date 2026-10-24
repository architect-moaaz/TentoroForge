"""The native engineer: one page of the application as a React Native screen.

The web's UI engineer (`ui_engineer`) writes a page as Next.js; this writes the
SAME page — the same Blueprint page, so the same entities, workflows and rules
— as a screen in the Expo project beside it (`native_projection`). One screen
per page, written against the native SDK and kit that ship in
`templates/native`, which mirror the web's names (`useList`, `useWorkflow`,
`WorkflowForm`, `href`…) so a model that knows the one writes the other.

What it is held to is what the web page is held to, with the compiler first: a
screen is type-checked against the application's own generated types (a
workflow input left out, a route that is not there, a column the entity lacks
is an error, not a heuristic) and against the page rules (every workflow the
page launches has a control, every move the flows name leads somewhere, no
change is faked in state). What goes back to the writer is the errors; what
comes out is code that compiles.

Not here, by design: the web's look review (a screenshot of the page) — there
is no native render target in the build yet, so a screen is accepted as
compiled and the narration says so; and parts (a screen is one file).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from services.blueprint.native_projection import TEMPLATE_DIR
from services.blueprint.tsc_gate import tsc_slot

logger = logging.getLogger(__name__)

#: The reply: the screen, whole, and anything it needs that no workflow does.
NATIVE_SCREEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rationale", "screen", "needs"],
    "properties": {
        "rationale": {"type": "string",
                      "description": "Two or three sentences: how the screen is arranged for a phone and why."},
        "screen": {"type": "string", "description": "The full contents of the screen file (Screen.tsx)."},
        "needs": {"type": "array", "items": {"type": "string"},
                  "description": "A change to records the screen needs and no workflow of the application "
                                 "makes — named in a sentence each. Empty when every change has a workflow."},
    },
}

#: The rounds a screen gets to compile (the web's).
def _rounds() -> int:
    from services.blueprint.ui_engineer import COMPILE_ROUNDS
    return COMPILE_ROUNDS


# ---------------------------------------------------------------------------
# What the writer is told
# ---------------------------------------------------------------------------

def sdk_guide() -> str:
    """The native SDK and kit as the template documents them: from "What a
    screen imports" to the tests — the one place that says what exists."""
    text = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
    start = text.index("### What a screen imports")
    end = text.index("## Tests")
    return text[start:end].strip()


NATIVE_RULES = """\
- ONE FILE. The whole screen is `Screen.tsx`: `export default function Screen() { … }`. Imports only from
  "react", "react-native", "@/ui" and "@/sdk" — and a type from "@/sdk" is how you name an entity's row.
  Nothing from next/*, react-dom, lucide-react, a CSS file or a package that is not listed; no `className`,
  no <div>/<span>/<button>/<img>/<a>: this is React Native, and the kit has the part you want.
- DATA IS A HOOK. There is no `load` and no server: read with `useList`, `useRecord`, `useCount`, `useQuery`,
  `useWidget`… and handle every state the hook has — loading, error with a retry, empty, and a record that is
  gone (`notFound`). `Screen` takes `loading`, `error`, `onRetry`, `empty` and `onRefresh` for exactly this.
  A route's id comes from `useParams<{ id: string }>()`; read nothing until it is there (pass `null`).
- EVERY CHANGE IS A WORKFLOW. `WorkflowForm`, `WorkflowButton`, or `useWorkflow(workflows.x)` and `run({…})`.
  Never write records any other way, and never fake one (a handler that filters a row out of state, or waits on
  a timer). When the screen needs a change no workflow makes, leave the control out and name the change in `needs`.
- EVERY WORKFLOW THE PAGE LAUNCHES HAS A CONTROL, and every move the flows name leads where it says
  (`useNav().push(href(pages.x, { id }))`, or `redirectTo`). A screen that compiles and cannot do the page's job
  is a failure.
- A PHONE, NOT A SHRUNK PAGE. One column. The primary action is in reach of the thumb (`footer` on `Screen`, or a
  full-width Button at the end of a form). Touch targets are 44 pt. A long list is a `ListView`, not a map
  inside a ScrollView. A secondary flow is a `Sheet`, not a second screen. Tables become cards or rows with the
  two facts that matter, the rest one tap away. Text never truncates what the person needs to read.
- PADDING IS THE SCREEN'S. Leave `padded` at its default: the content keeps a 16 pt margin on every side,
  and a list's search box, chips and cards sit inside it. `padded={false}` is for content that bleeds to
  the screen's edge (a map, a full-width image) and removes the margin from EVERYTHING inside — a list
  with `padded={false}` touches the glass. A list is `<Screen scroll={false}>` with the default padding.
- A TAB OR A MENU PAGE HAS NO BACK. When the screen is one of the app's bottom tabs, or a main page of its
  hamburger menu (the brief says which), it has no `back` button - the header draws the hamburger itself; every
  other screen — a form, one record — has `back`.
- MAKE IT LOOK DESIGNED, NOT ASSEMBLED. The kit has what a polished phone app uses; reach for it:
  `ListView spaced` for a list of cards (they touch, with only a hairline between them, without it), `Chips` for status filters (they scroll sideways, never wrap), `Dots` for a 1-5 value, `StatusBadge` for a
  status, a `Button` with an `icon` (`variant="ghost" size="sm"` for a row's action), `Empty` with an `icon` for an
  empty state, `Icon` beside a label. A card shows ONE thing first (the title, in the heading face) and the rest
  quietly: do not repeat five equal rows. Whitespace between groups, not borders. The type faces are the
  design's own - use `Text` variants (`title`, `heading`, `label`, `caption`) and never set a font yourself.
- THE DESIGN SYSTEM IS THE SCREEN'S ONLY RULER. `useTheme().colors.<token>` for colour, `space.<xs..xxl>` for
  every padding, margin and gap (a `Stack`/`Row` takes the same names), `useTheme().radii.<sm|md|lg>` for a
  corner, a `Text` variant for every size and face, `Card` or `theme.shadow(1|2|3)` for depth. Never a hex
  colour, never a number written as a margin, radius, font size or shadow, never `Text` from react-native: the
  checks refuse them, because those are the measures the designer chose and the web keeps to. The kit's parts are already styled — use `Card`, `Badge`, `StatTile`, `Button`
  variants rather than styling a View.
- MONEY is in major units (12.50): `<Money value={…} />` or `formatMoney`. Dates through `formatDate`. Every
  visible string through `useT()` when the application has more than one language.
- ONE FILLED ACTION PER SCREEN. The one thing to do now is a single `variant="accent"` button: in the title bar (`right`)
  OR in the `footer` OR at the end of a form, never two of them for the same action.
- DATES AND SUMS ARE CHECKED, NOT TRUSTED. Before using a subtraction say its sign: `due - today` is NEGATIVE when the
  due date has passed and POSITIVE when it is still to come, so overdue is `due < today`. A status that reads "Overdue" for
  a future date is a failure the compiler cannot see.
- WRITE IT AS YOU WOULD SHIP IT: no TODOs, no placeholder copy, no console.log, no unused imports. Real labels
  from the page's contract, real empty states in the application's own voice."""

#: Said once in the system prompt, for the two screens it is about.
AUTH_RULES = """\
- THE SIGN-IN AND SIGN-UP SCREENS ARE A FRAME AROUND THE KIT'S FORM. The brief may be the web's sign-in or
  sign-up page. You write what the person SEES around the form - the words, the band, the layout, the mood of
  this product - and place `<SignInForm />` (sign-in) or `<SignUpForm />` (sign-up) from "@/ui": the only parts that
  make a session or an account. Never read or call the session yourself (`useSession`, `signIn`, `apiJson`), never
  draw an email or password field, never a `WorkflowForm`: a screen that does can lock everyone out, and the checks
  refuse it. Start from `AuthFrame` (`title`, `tagline`, `footer`: a band in the primary colour with the app's mark
  and name, a card for the form) and put the web page's own words in it; `SwitchAuthLink to="signup"` / `"signin"`
  is the link to the other screen (it hides itself where the app does not let people sign up) and `LanguageSwitch`
  the language. There is no `back` and no tab bar here: the person is signed out."""

#: The web direction and rhythm are written in the web's words (a 1100px column, Tailwind classes, `bg-brand-gradient`).
#: Said once, for the writer: what each means on a phone.
PHONE_TRANSLATION = """\
THE DIRECTION AND THE RHYTHM ABOVE WERE WRITTEN FOR THE WEB. Take their INTENT, not their CSS: the hierarchy, the one
primary action, the voice of an empty state, which fact leads. On the phone that reads as:
- a page frame / column width / px padding -> the screen's own margin (`Screen`); never a width or a number of yours.
- `header: band` -> the screen's title in the heading face (`Screen title`/`subtitle`), the primary action in the
  `footer` or beside the title (`right`); a gradient band is for the page's LEAD only, one per screen.
- `lead: gradient-band` -> a `GradientBand` at the top of the screen holding the facts in large `Text variant="title"`
  with `tone="inverse"`; a page whose lead is not a band opens with the title and its first facts.
- `lists: cards` -> `Card`s in a `ListView` (one fact first, in the heading face, then two or three quietly);
  `lists: table` -> the same cards with the two facts that matter. Space between cards is `space.md` as a top margin.
- `figures: inline` -> `label · value` in muted `Text`; a dashboard's KPI widgets are `StatTile`s (`WidgetView`) in a
  wrapping `Row`.
- `sections: open` -> a `Text variant="heading"` with the content under it, no card; `cards` -> a `Card` per section.
- tokens like `text-primary`, `bg-accent` -> `tone="primary"`, `variant="accent"`, `theme.colors.primary|accent`.
- The accent marks the ONE thing to do now (`Button variant="accent"`): once per screen, never on every row."""

NATIVE_DESIGN = """\
Design for the thumb and for glancing. Lead with what the person came to do or know: the primary number or the
primary action in the first screenful. Group by task with generous spacing from `space`, not by borders.
Use the application's own voice and the entity's own names. Make an empty list an invitation to add the first
one, and an error a sentence with a retry. Motion is the platform's; add none of your own. A screen that would
look at home in any other application is not finished."""


def _look(doc: dict) -> str:
    """The design system, as the tokens a native screen asks the theme for."""
    design = doc.get("designSystem") or {}
    colors = design.get("colors") or {}
    roles = {"background": "background", "surface": "card", "textPrimary": "foreground",
             "textSecondary": "mutedForeground", "primary": "primary", "accent": "accent",
             "accentSubtle": "accentSubtle", "inverse": "inverse"}
    lines = [str(design.get("visualPersonality") or "")[:600]]
    for role, token in roles.items():
        value = colors.get(role)
        if value:
            lines.append(f"- theme.colors.{token} ({value})")
    typo = design.get("typography") or {}
    head = typo.get("fontFamilyHeading") or typo.get("fontFamilyDisplay") or typo.get("headingFontFamily")
    body = typo.get("fontFamilyBase") or typo.get("fontFamily") or typo.get("fontFamilyBody")
    if head or body:
        lines.append(f"- type faces: heading {head or body}; body {body or head} (the system font unless the app loads them)")
    return "\n".join(x for x in lines if x)


def system_prompt(doc: dict) -> str:
    """Identical for every screen of one application — the cached prefix."""
    from services.blueprint.app_sdk import sdk_reference
    from services.blueprint.ui_engineer import _about, _language, _rhythm, bar

    comp = doc.get("composition") or {}
    conventions = "\n".join(f"- {c.get('topic')}: {c.get('rule')}" for c in comp.get("conventions") or []) or "- (none stated)"
    app = doc.get("application") or {}
    return f"""You are the native engineer of {app.get('name') or 'this application'}: you write one screen of its \
React Native (Expo, TypeScript strict) app, held to the standard of {bar(doc)}. The same page already exists on \
the web; you write it for the phone — the same data, the same workflows, the same rules, reached over the \
application's own API — and it must look and feel like THIS product, not like every other generated app.

WRITE IT, THEN IMPROVE IT. Your reply is compiled the moment it arrives — TypeScript strict against this \
application's own types, plus checks that every workflow the page launches has a control — and anything wrong \
comes straight back to you with the errors, up to {_rounds()} times. Begin writing early.

# The application
{app.get('name')}
{_about(doc)}

{_language(doc)}# Its direction — follow it on every screen
{comp.get('vision') or '(no vision stated — choose a calm, professional, information-dense style)'}
{conventions}

# Its rhythm — decided once for this application
{_rhythm(doc)}

# Its look — the tokens the theme carries
{_look(doc)}

# On the phone
{PHONE_TRANSLATION}

# Rules
{NATIVE_RULES}
{AUTH_RULES}

# The native SDK and kit
```
{sdk_guide()}
```

# This application's entities, workflows and pages (generated from its Blueprint — the web uses the same)
```ts
{sdk_reference(doc)}
```

# Design
{NATIVE_DESIGN}
Reply with the rationale, the full contents of Screen.tsx, and `needs` (empty when every change has a workflow)."""


def auth_kind(page: dict) -> str | None:
    """`signin` for the page at /login, `signup` for the one at /signup (a page of the `auth` pattern), else None."""
    if str(page.get("pattern") or "") != "auth":
        return None
    return {"/login": "signin", "/signup": "signup"}.get("/" + str(page.get("route") or "").strip("/"))


def _web_words(doc: dict, page: dict) -> str:
    """What the web page says (its view), so the phone says the same: the words are the product's.
    Empty when the web page has not been written yet (the two are written in parallel in a first build; a Smith
    change and the Publish-time pass find it written)."""
    row = next((r for r in doc.get("pageCode") or [] if isinstance(r, dict) and str(r.get("page")) == str(page.get("id"))), None)
    return str((row or {}).get("view") or "")


def user_prompt(doc: dict, page: dict, *, feedback: str = "", brief: str = "", current: dict | None = None) -> str:
    from services.blueprint.native_projection import is_menu_page, is_tab
    from services.blueprint.ui_engineer import _page_brief

    out = ["Write this page as a native screen. The brief below is the web page's; its `load.ts`, `searchParams`, "
           "`useSearchParams` and `view.tsx` are the web's words — on the phone a hook reads the data, `useParams` "
           "gives the route's id and query, and the screen is one component.\n\n```json\n"
           + json.dumps(_page_brief(doc, page), indent=2) + "\n```"]
    kind = auth_kind(page)
    if kind:
        form = "<SignInForm />" if kind == "signin" else "<SignUpForm />"
        out.append(f"\nThis is the {'sign-in' if kind == 'signin' else 'sign-up'} screen: a frame around {form}, with no `back` and "
                   "no tab bar (see the rules). Use the web page's own words and mood below, in the phone's parts.")
        words = _web_words(doc, page)
        if words:
            out.append("\nThe web page, for its words, its mood and what it puts beside the form (do not copy its markup):\n```tsx\n"
                       + words + "\n```")
    elif is_menu_page(doc, str(page.get("id"))):
        out.append("\nThis screen is a MAIN PAGE of the app's hamburger menu: it has no `back` button (its header draws the "
                   "hamburger by itself), and its title is the menu item's.")
    else:
        out.append("\nThis screen IS one of the app's bottom tabs: it has no `back` button, and its title is the tab's."
                   if is_tab(doc, str(page.get("id"))) else
                   "\nThis screen is NOT a tab: it is opened from another screen, so it has a `back` button.")
    if not kind:
        words = _web_words(doc, page)
        if words:
            out.append("\nThe web page as it is written now - what it shows, how it words things, which status is which "
                       "colour. Make the phone's screen say the same (translate it to the kit, do not copy its markup):\n"
                       "```tsx\n" + words + "\n```")
    if brief:
        out.append(f"\nWhat is wanted of it now:\n{brief}")
    if current:
        out.append("\nIts current screen — change it as asked, keep what works:\n```tsx\n"
                   + str(current.get("screen") or "") + "\n```")
    if feedback:
        out.append(f"\nYour previous version was refused. Fix every one of these and keep what worked:\n{feedback}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The page rules (text checks; the compiler does the rest)
# ---------------------------------------------------------------------------

_WEB_IMPORT = re.compile(r"""from\s+["'](next/[^"']*|next|react-dom[^"']*|lucide-react|@/components/[^"']*|@/lib/[^"']*|"""
                         r"""@tentoroforge/[^"']*|tailwind[^"']*|[^"']+\.css)["']""")
_HTML_TAG = re.compile(r"<(div|span|button|img|a|p|ul|li|table|tr|td|th|input|form|section|main|header|footer|h[1-6])[\s>/]")
_CLASSNAME = re.compile(r"\bclassName\s*=")
_HEX = re.compile(r"""["']#[0-9a-fA-F]{3,8}["']""")
#: THE DESIGN SYSTEM'S MEASURES ARE NOT THE SCREEN'S TO INVENT. Spacing, corner radii, type and shadows come
#: from the theme (`space.md`, `useTheme().radii.md`, a `Text` variant, `Card`): a number written into a style
#: is a measure the design never chose, and it is the web's strictness the phone would lose.
_NUM = r"-?[1-9]\d*(?:\.\d+)?"
_SPACING_LITERAL = re.compile(r"\b(?:padding|paddingHorizontal|paddingVertical|paddingTop|paddingBottom|paddingLeft|paddingRight|"
                              r"margin|marginHorizontal|marginVertical|marginTop|marginBottom|marginLeft|marginRight|"
                              r"gap|rowGap|columnGap)\s*:\s*" + _NUM)
_RADIUS_LITERAL = re.compile(r"\bborder(?:Top|Bottom)?(?:Left|Right)?Radius\s*:\s*" + _NUM)
_TYPE_LITERAL = re.compile(r"\b(?:fontSize|lineHeight|fontFamily|fontWeight|letterSpacing)\s*:")
_SHADOW_LITERAL = re.compile(r"\b(?:shadow(?:Color|Offset|Opacity|Radius)|elevation)\s*:")
_RAW_TEXT_IMPORT = re.compile(r"import\s*\{[^}]*\b(?:Text|TextInput)\b[^}]*\}\s*from\s*[\"']react-native[\"']")
_ONDONE_BLIND = re.compile(r"\bonDone\s*=\s*\{\s*\(\s*\)\s*=>")
_SCROLL_OFF = re.compile(r"\bscroll\s*=\s*\{\s*false\s*\}")
_LISTVIEW = re.compile(r"<ListView\b")
_SCROLLER = re.compile(r"import\s*\{[^}]*\b(?:ScrollView|FlatList|SectionList|VirtualizedList)\b[^}]*\}\s*from\s*[\"']react-native[\"']")
_FETCH = re.compile(r"\bfetch\s*\(")
_CONSOLE = re.compile(r"\bconsole\.(log|debug)\s*\(")
#: `as any` SWITCHES THE COMPILER OFF FOR THAT LINE, which is the one thing the screen is held to. The Account screen read
#: `account` off `useMe() as any` (it is `data.account`), drew nothing on every phone, and compiled.
_AS_ANY = re.compile(r"\bas\s+any\b")
#: A "Sign Out" workflow is a record of an end, not a sign-out: the session stays, and the sign-in screen sends the person
#: straight back in. Signing out is the session's: `useSession().signOut()`.
_SIGN_OUT_WORKFLOW = re.compile(r"\bworkflows\.(?:signOut|signout|logOut|logout)\b")


def _native_findings(screen: str) -> list[str]:
    out = []
    if not re.search(r"export\s+default\s+(?:async\s+)?function\b|export\s+default\s+\w+", screen):
        out.append("Screen.tsx: it has no default export — `export default function Screen() { … }`.")
    for m in sorted({m.group(1) for m in _WEB_IMPORT.finditer(screen)}):
        out.append(f"Screen.tsx: imports `{m}` — a web module. Only react, react-native, @/ui and @/sdk exist here.")
    tags = sorted({m.group(1) for m in _HTML_TAG.finditer(screen)})
    if tags:
        out.append("Screen.tsx: HTML elements (" + ", ".join(f"<{t}>" for t in tags[:6])
                   + ") do not exist in React Native — use View/Text or the kit's parts.")
    if _CLASSNAME.search(screen):
        out.append("Screen.tsx: `className` does nothing in React Native — style from the kit and `useTheme()`.")
    if _HEX.search(screen):
        out.append("Screen.tsx: a hard-coded hex colour — take it from `useTheme().colors`.")
    if _FETCH.search(screen):
        out.append("Screen.tsx: `fetch` — read with the SDK's hooks and change with a workflow.")
    if _SPACING_LITERAL.search(screen):
        out.append("Screen.tsx: a number written as padding, margin or gap — spacing is the design's scale: `space.xs`..`space.xxl` "
                   "(import `space` from \"@/ui\"), or the kit's `Stack`/`Row` `gap` and `padding`.")
    if _RADIUS_LITERAL.search(screen):
        out.append("Screen.tsx: a number written as a corner radius — the design has three: `useTheme().radii.sm|md|lg` "
                   "(or let `Card`/`Button` draw their own).")
    if _TYPE_LITERAL.search(screen):
        out.append("Screen.tsx: fontSize, lineHeight, fontFamily or fontWeight set by hand — the design's type scale and typefaces are "
                   "the `Text` variants (`title`, `heading`, `label`, `body`, `caption`) and its `weight` prop.")
    if _SHADOW_LITERAL.search(screen):
        out.append("Screen.tsx: a shadow or elevation written by hand — depth is the design's: `Card`, or `...useTheme().shadow(1|2|3)`.")
    if _ONDONE_BLIND.search(screen):
        out.append("Screen.tsx: `onDone={() => …}` ignores the result - `WorkflowForm` calls `onDone(result)` after EVERY attempt, a "
                   "refused one too, so this leaves the screen (or closes the sheet) when a rule refused the input and the person "
                   "loses what they typed. Take the result and test it: `onDone={(r) => { if (r.ok) … }}` - or use `redirectTo`.")
    if _SCROLL_OFF.search(screen) and not _LISTVIEW.search(screen):
        out.append("Screen.tsx: `scroll={false}` with no `<ListView>` - nothing on this screen scrolls, so a long list is cut "
                   "off. Put the records in a `ListView` (with the header, search and chips in its `header`), or leave `scroll` on.")
    if _SCROLLER.search(screen):
        out.append("Screen.tsx: ScrollView/FlatList from react-native - `Screen` scrolls its content and `ListView` is the list "
                   "(with `<Screen scroll={false}>`); two scrollers nested is a bug.")
    if _RAW_TEXT_IMPORT.search(screen):
        out.append("Screen.tsx: `Text`/`TextInput` from react-native draw the system font — use `Text` and the fields from \"@/ui\", "
                   "which carry the design's typefaces and colours.")
    if _CONSOLE.search(screen):
        out.append("Screen.tsx: a console.log is left in.")
    if _AS_ANY.search(screen):
        out.append("Screen.tsx: `as any` turns the compiler off for that line, and a wrong guess about a hook's shape then draws "
                   "nothing. Give it its real type instead: `useMe()` is `{ data, loading, error, refetch }` - the person is "
                   "`data?.user` and their own record is `data?.account`.")
    if _SIGN_OUT_WORKFLOW.search(screen):
        out.append("Screen.tsx: a \"Sign Out\" workflow does not sign anyone out - it only records an end, and the person stays "
                   "signed in. Sign out with `const { signOut } = useSession(); await signOut();` (the app then returns to the "
                   "sign-in screen by itself).")
    return out


_AUTH_OWN = re.compile(r"\b(useSession|useSignInMethods|signIn|signOut|apiJson|SecureStore|useWorkflow|WorkflowForm|WorkflowButton)\b")
_AUTH_FIELD = re.compile(r"""kind\s*=\s*["'](?:password|email)["']""")


def _auth_findings(page: dict, screen: str) -> list[str]:
    """The sign-in and sign-up screens may draw the frame, never the form."""
    kind = auth_kind(page)
    if not kind:
        return []
    form = "SignInForm" if kind == "signin" else "SignUpForm"
    out = []
    if not re.search(r"<" + form + r"\b", screen):
        out.append(f"Screen.tsx: the {'sign-in' if kind == 'signin' else 'sign-up'} screen must place `<{form} />` from \"@/ui\" - it is the "
                   "only part that makes a " + ("session" if kind == "signin" else "account") + ".")
    own = sorted({m.group(1) for m in _AUTH_OWN.finditer(screen)})
    if own:
        out.append("Screen.tsx: " + ", ".join(f"`{n}`" for n in own[:5]) + " - this screen draws the frame only; "
                   f"`<{form} />` holds the session, the account and the way in.")
    if _AUTH_FIELD.search(screen):
        out.append(f"Screen.tsx: an email or password field of its own - `<{form} />` draws them; do not ask twice.")
    return out


def _page_findings(doc: dict, page: dict, screen: str) -> list[str]:
    """The web's page rules, said for a screen: a launched workflow with no
    control, a flow move that leads nowhere, a change faked in state."""
    from services.blueprint.ui_engineer import _simulated_writes, _unfollowed_flows, _unwired_actions

    found = _unwired_actions(doc, page, screen) + _unfollowed_flows(doc, page, screen) + _simulated_writes(screen)
    return [e.replace("view.tsx", "Screen.tsx") for e in found]


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

#: The packages the template's `package.json` names, installed once and shared.
_TOOLCHAIN_LOCK = threading.Lock()

#: A FAILED INSTALL IS REMEMBERED FOR THE LIFE OF THE PROCESS. On a host with no network (or a bad registry) every
#: screen's compile asked for the toolchain again: pages x rounds x Smith turns of `npm install`, each up to 25 minutes,
#: one after another behind the lock. Keyed by the folder and the template's dependencies, so a changed template (or
#: `forget_toolchain_failures()`) tries again.
_INSTALL_FAILED: dict[str, str] = {}


def forget_toolchain_failures() -> None:
    """Try the install again on the next compile (a network that came back, a test)."""
    with _TOOLCHAIN_LOCK:
        _INSTALL_FAILED.clear()


def toolchain_dir() -> Path:
    """Where the compiler and the packages the screens type-check against live:
    `FORGE_NATIVE_TOOLCHAIN`, else `backend/.forge/native-toolchain`."""
    given = os.environ.get("FORGE_NATIVE_TOOLCHAIN", "").strip()
    return Path(given) if given else Path(__file__).resolve().parents[2] / ".forge" / "native-toolchain"


def _package_json() -> dict:
    pkg = json.loads((TEMPLATE_DIR / "package.json").read_text(encoding="utf-8"))
    return {"name": "forge-native-toolchain", "version": "1.0.0", "private": True,
            "dependencies": pkg.get("dependencies") or {}, "devDependencies": pkg.get("devDependencies") or {}}


def _fingerprint() -> str:
    return hashlib.sha256(json.dumps(_package_json(), sort_keys=True).encode()).hexdigest()[:16]


def ensure_toolchain(run: Any = None, timeout: float = 1500.0) -> Path | None:
    """The toolchain directory with its packages installed, or None when it
    cannot be (no npm, no network): the screen is then checked by its page
    rules alone and the run says it was not compiled. Installed once, keyed by
    the template's dependencies, and shared by every screen of every app."""
    run = run or subprocess.run
    root = toolchain_dir()
    stamp = root / "node_modules" / ".forge-installed"
    tsc = root / "node_modules" / "typescript" / "bin" / "tsc"
    explicit = bool(os.environ.get("FORGE_NATIVE_TOOLCHAIN", "").strip())
    with _TOOLCHAIN_LOCK:
        if tsc.is_file() and (explicit or (stamp.is_file() and stamp.read_text().strip() == _fingerprint())):
            return root
        failed_key = f"{root}|{_fingerprint()}"
        if failed_key in _INSTALL_FAILED:
            return None                      # it did not install earlier in this process: not again, for every screen
        npm = shutil.which("npm")
        if not npm:
            logger.warning("[native_engineer] no npm: screens are not compiled")
            return None
        root.mkdir(parents=True, exist_ok=True)
        (root / "package.json").write_text(json.dumps(_package_json(), indent=2), encoding="utf-8")
        logger.info("[native_engineer] installing the native toolchain in %s (once)", root)
        try:
            proc = run([npm, "install", "--no-audit", "--no-fund", "--loglevel", "error"], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("[native_engineer] the toolchain did not install (not tried again in this process): %s", exc)
            _INSTALL_FAILED[failed_key] = str(exc)[:400]
            return None
        if getattr(proc, "returncode", 1) != 0 or not tsc.is_file():
            why = (getattr(proc, "stderr", "") or "")[-400:]
            logger.warning("[native_engineer] the toolchain did not install (not tried again in this process): %s", why)
            _INSTALL_FAILED[failed_key] = why or "npm install failed"
            return None
        stamp.write_text(_fingerprint(), encoding="utf-8")
        return root


def _posix(path: Path) -> str:
    return path.resolve().as_posix()


def typecheck(doc: dict, native_root: Path, page_id: str, screen: str, *, timeout: float = 240.0,
              toolchain: Path | None = None, run: Any = None) -> list[str] | None:
    """Compile one screen against the application's own generated types and
    the kit. Only errors in the screen count: the kit is checked by its own
    tests. Returns the errors (empty when it compiles), or None when there is
    no compiler to ask — which the caller says out loud."""
    from services.blueprint.native_projection import ensure_native_project

    tool = toolchain or ensure_toolchain()
    node = shutil.which("node")
    if tool is None or node is None:
        return None
    run = run or subprocess.run
    project = ensure_native_project(doc, native_root.parent)
    check = tool / ".checks" / f"{page_id}-{os.getpid()}-{threading.get_ident()}"
    if check.exists():
        shutil.rmtree(check, ignore_errors=True)
    check.mkdir(parents=True)
    try:
        (check / "screen.tsx").write_text(screen, encoding="utf-8")
        modules = tool / "node_modules"
        (check / "tsconfig.json").write_text(json.dumps({
            "extends": "expo/tsconfig.base",
            "compilerOptions": {
                "strict": True, "jsx": "react-native", "noEmit": True, "incremental": False,
                "skipLibCheck": True, "baseUrl": _posix(check),
                "paths": {
                    f"@/screens/{page_id}": [_posix(check / "screen.tsx")],
                    "@/*": [_posix(project / "src") + "/*"],
                    "*": [_posix(modules) + "/*", _posix(modules / "@types") + "/*"],
                },
                "typeRoots": [_posix(modules / "@types")],
            },
            "include": [_posix(check / "screen.tsx"), _posix(project / "src") + "/**/*.d.ts"],
        }, indent=2), encoding="utf-8")
        with tsc_slot():
            proc = run([node, _posix(modules / "typescript" / "bin" / "tsc"), "-p", _posix(check / "tsconfig.json"),
                        "--pretty", "false"], cwd=str(check), capture_output=True, text=True, encoding="utf-8",
                       timeout=timeout)
        marker = check.name + "/"
        errors: list[str] = []
        ours = False
        for line in (proc.stdout + proc.stderr).splitlines():
            where = line.split("(", 1)[0].replace("\\", "/")
            # tsc names a file relative to its cwd — the check folder, so the screen is
            # plain `screen.tsx` — or by a longer path through it from elsewhere. Anything
            # else is the kit's own file, and the kit is checked by its tests.
            if where == "screen.tsx" or where.endswith("/" + marker + "screen.tsx"):
                errors.append("Screen.tsx" + line[len(where):])
                ours = True
            elif ours and line.startswith(" "):
                errors[-1] += " " + line.strip()
            else:
                ours = False
        return errors
    finally:
        shutil.rmtree(check, ignore_errors=True)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

_TS_ERROR = re.compile(r"^Screen\.tsx\((\d+),(\d+)\): error (TS\d+): (.*)$", re.S)
_QUOTED = re.compile(r"'([^']+)'")
_EXPORT_LIST = re.compile(r"export\s+(?:type\s+)?\{([^}]*)\}", re.S)
_EXPORT_STAR = re.compile(r"""export\s+\*\s+from\s+["']\./([\w/.-]+)["']""")
_EXPORT_DECL = re.compile(r"\bexport\s+(?:async\s+)?(?:function|const|class|interface|type|enum)\s+(\w+)")


def _exports_of(index: Path) -> set[str]:
    """The names a kit module hands to a screen: what its `index.ts` exports, listed or re-exported whole."""
    try:
        text = index.read_text(encoding="utf-8")
    except OSError:
        return set()
    names: set[str] = set()
    for m in _EXPORT_LIST.finditer(text):
        for part in m.group(1).split(","):
            part = re.sub(r"^\s*type\s+", "", part.strip())
            if part:
                names.add(part.split(" as ")[-1].strip())
    for m in _EXPORT_STAR.finditer(text):
        for ext in (".ts", ".tsx"):
            try:
                names |= set(_EXPORT_DECL.findall((index.parent / (m.group(1) + ext)).read_text(encoding="utf-8")))
            except OSError:
                continue
    return names


def explain_error(error: str, screen: str, native_root: Path) -> str:
    """A compiler error as the writer should read it: the line it points at, with a mark under the spot, and — for the
    mistakes a writer makes again and again — what to do about it.

    The compiler says "(2,79): … has no exported member 'toast'" and the writer had to count to find the place and guess where
    the name lives. This shows the line, and says where the name IS."""
    m = _TS_ERROR.match(error)
    if not m:
        return error
    line_no, col, code, message = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
    lines = screen.splitlines()
    out = [error]
    if 1 <= line_no <= len(lines):
        shown = lines[line_no - 1].rstrip()
        prefix = f"    line {line_no}: "
        out.append(prefix + shown)
        out.append(" " * (len(prefix) + max(col - 1, 0)) + "^")
    names = _QUOTED.findall(message)
    hint = ""
    if code in ("TS2305", "TS2724", "TS2614") and len(names) >= 2 and "@/" in names[0]:
        # "Module '"@/ui"' has no exported member 'toast'": the module is quoted first, the missing name second.
        module, member = names[0], names[1]
        homes = {mod: member in _exports_of(native_root / "src" / mod / "index.ts") for mod in ("sdk", "ui")}
        where = [f'"@/{mod}"' for mod, has in homes.items() if has]
        if where:
            hint = f"`{member}` is exported from {' and '.join(where)}" + (f", not {module}." if module else ".")
        else:
            hint = f"`{member}` is exported from neither \"@/ui\" nor \"@/sdk\": use a part that exists (the guide lists them)."
    elif code == "TS2353" and len(names) >= 2:
        hint = (f"`{names[0]}` is not something {names[-1]} accepts: delete it. What a part accepts is in the guide; "
                "a list handles loading more by itself (`<ListView list={list} …/>`).")
    elif code == "TS2339" and len(names) >= 2:
        hint = (f"`{names[0]}` is not a field of {names[-1]}: a record's own fields are the ones in the generated types "
                "(`src/sdk/schema.ts`), and a hook's result has the fields its type names.")
    if hint:
        out.append("    hint: " + hint)
    return "\n".join(out)


def compose_screen(doc: dict, page: dict, native_root: Path, client: Any, *, feedback: str = "", brief: str = "",
                   current: dict | None = None, node: str = "native_code",
                   check: Any = None) -> tuple[dict, list[Any]]:
    """Author one screen and compile it, returning the accepted `nativeCode`
    body and the usage of every call. Raises `CompileError` when the last round
    still does not compile; `NeedsWorkflow` when a change asks for records to
    change in a way no workflow does.

    `check(screen) -> list[str] | None` is the compiler, replaceable; None
    from it means there is none to ask (the screen is accepted on the page
    rules alone and the log says so)."""
    from services.blueprint.ui_engineer import CompileError, NeedsWorkflow, WRITE_EFFORT, WRITE_MAX_TOKENS, _with

    check = check or (lambda screen: typecheck(doc, native_root, str(page.get("id")), screen))
    system = system_prompt(doc)
    writer = _with(client, effort=WRITE_EFFORT, max_tokens=WRITE_MAX_TOKENS)
    spent: list[Any] = []
    note = feedback
    last_errors: list[str] = []
    rounds = _rounds()
    for round_ in range(1, rounds + 1):
        t0 = time.monotonic()
        reply = writer(system=system, user=user_prompt(doc, page, feedback=note, brief=brief, current=current),
                       schema=NATIVE_SCREEN_SCHEMA)
        text = getattr(reply, "text", reply)
        if getattr(reply, "usage", None) is not None:
            spent.append((reply.usage, time.monotonic() - t0))
        try:
            body = json.loads(text)
        except json.JSONDecodeError as exc:
            note = f"Your reply was not valid JSON ({exc}). Return the object only."
            continue
        screen = str(body.get("screen") or "")
        needs = [str(n).strip() for n in body.get("needs") or [] if str(n).strip()]
        if needs and current is not None:
            # NOTHING IS WRITTEN AROUND A MISSING WORKFLOW — the web's rule.
            raise NeedsWorkflow(needs)
        errors = _native_findings(screen) + _page_findings(doc, page, screen) + _auth_findings(page, screen)
        compiled = check(screen)
        if compiled is None:
            logger.info("[native_engineer] %s not compiled (no compiler); accepted on its page rules", page.get("id"))
        else:
            errors += compiled
        if not errors:
            logger.info("[native_engineer] %s composed in %d round(s), %d chars", page.get("id"), round_, len(screen))
            return ({"page": str(page.get("id")), "rationale": str(body.get("rationale") or ""),
                     "screen": screen, "parts": {}, "requirements": list(page.get("requirements") or [])}, spent)
        last_errors = errors
        current = {"screen": screen}
        note = ("The TypeScript compiler (strict) and the screen rules refused it:\n"
                + "\n".join(f"- {explain_error(e, screen, native_root)}" for e in errors[:40]))
        logger.warning("[native_engineer] %s round %d: %d error(s): %s", page.get("id"), round_, len(errors),
                       "; ".join(errors[:3])[:400])
    raise CompileError(f"{page.get('id')}: the native screen still does not compile after {rounds} rounds — "
                       + "; ".join(last_errors[:12]))
