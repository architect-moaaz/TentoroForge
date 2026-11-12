# __APP_NAME__ — Native app

The native (Expo / React Native) app for __APP_NAME__. One screen for each page of
the web app, talking to the web app's own HTTP API as the same signed-in person.
Produced by Tentoro Forge. There is no database here and no second set of rules:
reads, workflows, access and tenancy are the web app's.

```bash
cd native            # this folder
npm install
npm start            # Expo dev server; scan the QR with Expo Go or press i / a
npm run typecheck    # tsc --noEmit — every screen against the app's own types
```

Where the app is: `EXPO_PUBLIC_APP_URL` (a local `.env`, or an `env` block of an
`eas.json` profile) wins, else `extra.appUrl` in `app.json` (`__DEPLOYED_URL__`).
`EXPO_PUBLIC_BASE_PATH` is the app's base path (empty for a published app).
Builds: `npm run build:preview:android`, `build:preview:ios-sim`,
`build:production:*`, `submit:*` (EAS Build; see `eas.json`). Needs an Expo
account (`eas login`, `eas init` writes `__EAS_PROJECT_ID__`).

Only **password sign-in** works natively (it is next-auth's cookie flow). The
login screen reads `/api/auth/methods` and says so when the app does not offer it.

---

## For whoever generates the screens (a person or a model)

This template is **half** of the project. The fixed half is identical for every
app and is never edited per app. The generated half is written by the projector
and the native engineer. A screen is written against the same mental model as a
web page — same names, same result shapes — only the components are native.

### Fixed (do not edit per app)

```
app/_layout.tsx        root: safe area, error boundary, session, toasts, sign-in gate
app/login.tsx          email + password sign-in (reads /api/auth/methods first); links to sign-up
app/signup.tsx         create an account: the account entity's own fields (or a name), email, password -> /api/auth/signup, then signs in
app/(tabs)/account.tsx the last tab of an app with a sign-in: who is signed in, organisation, language, SIGN OUT (written with the tabs)
app/organisation.tsx   organisation picker (apps with several organisations)
app/+not-found.tsx     a route that is not a screen
src/sdk/*              the SDK  (import from "@/sdk")
src/ui/*               the component kit  (import from "@/ui")
src/theme.ts           tokens -> numbers (useTheme)
package.json app.json eas.json tsconfig.json babel.config.js   (placeholders substituted)
```

### Generated (the contract the fixed half imports)

Each file is imported by the fixed half under exactly these names. The first four
are the SAME files the web app gets from `services/blueprint/app_sdk.py`
(`emit_schema`, `emit_workflows`, `emit_pages`, `emit_widgets`).
`_placeholders/` holds a minimal version of every one so the template typechecks
alone; it is never copied into an app.

| file | exports the fixed half reads |
|---|---|
| `src/sdk/schema.ts` | `Entities`, `EntityName`, `NumericField<E>`, `READABLE_FIELDS`, `NUMERIC_FIELDS`, `AccountEntity`, `LABEL_FIELD` (types of every entity's row) |
| `src/sdk/workflows.ts` | `Workflow<I>` (`{ id, name, required? }`), `workflows.<key>` handles, `WorkflowKey`, `InputOf<W>` |
| `src/sdk/pages.ts` | `PageRef<R>` (`{ id, name, route }`), `pages.<key>`, `href(page, params?, query?)` |
| `src/sdk/widgets.ts` | `WidgetRef` (`id, page, label, description?, kind, unit, size?, chart?, source`), `widgets.<key>`, `WidgetUnit`, `ChartMark`, `WidgetSource` |
| `src/theme.generated.ts` | `colors: Record<string, string>` (camelCase token -> HSL triplet `"243 75% 59%"` or any RN colour; only overrides), `radius: number`, `fonts: { body?: string; heading?: string }` |
| `src/config.generated.ts` | `CAN_SIGN_UP: boolean` (the app has a sign-up and people hold passwords), `AFTER_SIGNUP: string` (where a new account goes first), `APP_NAME: string`, `CURRENCY: string` (ISO 4217), `LOCALE: string` (BCP-47), `LANGUAGES: readonly { tag; dir: "ltr" \| "rtl" }[]`, `PRIMARY: string`, `HOME: string` (route a signed-in person lands on), `PUBLIC_ROUTES: readonly string[]` (routes, and their children, open without sign-in; `[]` = all private), `ACCOUNT: null \| { entity; fields; labelField; locationField }` (the web's `lib/account.ts`) |
| `src/navigation.generated.ts` | `TABS: readonly { name; title; icon; route }[]` — the main pages as bottom tabs (Ionicons glyph names); empty means no tab bar. The tab pages' route files live in `app/(tabs)/` and `app/(tabs)/_layout.tsx` is written with them. |

Colour tokens are the web's `token-contract.json` names in camelCase:
`background foreground card cardForeground popover popoverForeground muted
mutedForeground border input ring primary primaryForeground secondary
secondaryForeground accent accentForeground accentSubtle accentSubtleForeground
inverse inverseForeground destructive … success … warning … info …` (each with
`Foreground`, `Subtle`, `SubtleForeground`). Light only.

Also generated, per page of the Blueprint (the web writes `page.tsx`; native writes):

```
src/screens/<PAGE-ID>.tsx     export default function Screen() { … }   one screen, the page's behaviour
app/<route>.tsx               export { default } from "@/screens/<PAGE-ID>";
```

* The route file path is the page's route with `[param]` kept: `/orders/[id]` ->
  `app/orders/[id].tsx`; `/` -> `app/index.tsx`; a nested route has its folder.
  (expo-router file routing; no layout files are needed per route.)
* `app/login.tsx`, `app/organisation.tsx`, `app/_layout.tsx`, `app/+not-found.tsx`
  are fixed. A Blueprint page that is the web's sign-in page is NOT drawn
  natively and its route file must not be written over `app/login.tsx`.
* A screen reads its route's params with `useParams<{ id: string }>()`.

### What a screen imports

```tsx
import { Screen, Text, Button, ListView, ListItem, StatusBadge, WorkflowForm, WidgetView, Empty } from "@/ui";
import { useList, useRecord, useWorkflow, useNav, useParams, workflows, pages, widgets, href, formatMoney } from "@/sdk";
```

A screen is one component with hooks. There is no `load`/`view` split: a hook is
the `load`, and every action is a workflow.

---

## `@/sdk` — the public API

**Read** (the web's `@/sdk/server`, over `POST /api/read/<op>`; same options and
row types). Each returns `{ data, loading, refreshing, error, notFound, refetch }`
(`data` is null until the first answer, and is kept while a newer one loads) and
looks again by itself when any workflow finishes and on each `useLive` tick.
Pass `null`/`undefined` for an input not known yet and nothing is read.

```ts
useList(entity, { where?, search?, sort?, order?, limit? })  // ListState: data = rows so far; + total, hasMore, loadMore(), loadingMore
useRecord(entity, id)                    // one row; notFound when gone or not yours
useRecords(entity, ids)                  // { [id]: row } — related records by name, never by id
useCount(entity, where?)                 // number
useTotal(entity, "sum"|"avg"|"min"|"max", field, where?)   // number
useSeries(entity, { groupBy, bucket?, fn?, field? })       // { label, value }[]
useQuery(entity, { measures, dimensions?, where?, range?, timeField?, sort?, limit? })  // QueryRow[]
useWidget(widgets.x, { range?, where? }) // WidgetData { rows, value, previous?, delta? }
useSimilar(entity, { image?, text?, field?, limit? })      // { rows (+similarity), error }
useNear(entity, field, from: GeoPoint | null, { where?, radiusKm?, limit?, scan? })  // rows + distanceKm
useMe()                                  // ReadState: data = { user, account } — `const { data } = useMe(); data?.account`; + loading, error, refetch
                                         // (`account` is NOT a field of what useMe() returns: `const { account } = useMe()` is always undefined)
useLive(seconds = 10)                    // refresh what is on screen while this screen is in front
```

**Change** — every change is a workflow (typed by its inputs, the compiler refuses
a missing required input):

```ts
const { run, pending, error } = useWorkflow(workflows.x, { successMessage?, redirectTo?, silent? });
const out = await run({ ...input });     // RunResult { ok, result, error } — the web's shape
```
`result` is the run's receipt (`id` of the record it wrote, `records`, and `reply`:
the values its end declared). A rule refusal (`result.refused`) toasts the
workflow's own sentence; any other failure toasts "<Name> failed". The run's own
`redirect` wins over `redirectTo`; an outside URL opens in the browser.

**Session / navigation / misc**

```ts
useSession()          // { user, status: "loading"|"signedIn"|"signedOut"|"offline", signIn(email, password), signOut(), refresh() }
                      // SIGNING OUT IS `useSession().signOut()` — it ends the session and the app returns to the sign-in screen.
                      // A workflow called "Sign Out" only records an end; running it leaves the person signed in.
useOrganisations()    // { organisations, activeOrgId, needsOrganisation, switchOrganisation(orgId) }
useSignInMethods()    // { methods, loading, error, retry }
useNav()              // { push(to), replace(to), back(), canGoBack() } — `to` is what href() builds
useParams<P>()        // route params + query string, as strings
toast.success|error|info(title, { description? })   // anywhere; useToast() returns it
pickImage("camera"|"library"), pickDocument(), uploadFile(file) -> { id, error }, fileSource(id) // an <Image source>
askPosition() -> GeoPoint                // approximate (~100 m), with permission
formatMoney(amount, currency?)  CURRENCY // MAJOR units (12.50), the app's currency/locale
formatDate(iso, locale?, withTime?)  formatNumber  formatPercent  formatCell  humanize
distanceKm(a, b)  formatDistance(km, locale?)  parseNear(text)  roundPoint  isPoint
useT()  // t({ en: "Orders", hi: "ऑर्डर" });  useLanguage() -> { lang, setLang, languages }
apiFetch(path, init?) / apiJson(path, { body? }) // raw calls to the app, session attached (rarely needed)
```

Money fields hold MAJOR units; never divide or multiply by 100.

`<Avatar image={record.photo} />` takes the stored file's id or a link as it is and loads it itself: never wrap it in `fileSource(...)` (that returns an image object, which is only for an `<Image source>` you draw yourself).

### Live tracking and maps (a driver on the move, a customer watching)

Use these when a page is about someone on the move: a driver, courier or technician sharing where they are, or a customer
following a ride or an order. Do NOT draw a map for a page that only shows an address as text.

```tsx
import { FleetBeacon, ShareLocation, LiveTrackingMap, MapView, useRoute, useLiveTrip, minutesText } from "@/sdk";

<FleetBeacon entity="Driver" trip={driver.id} on={driver.availabilityStatus === "online"} />
    // the driver is ONLINE: this shares their position by itself while it is on screen. Put it on the page that shows
    // the online state, once. Never add a second "Go online" button next to the workflow's own.
<ShareLocation entity="Ride" trip={ride.id} stage={ride.status === "in_progress" ? "to_dropoff" : "to_pickup"} />
    // one trip: a Start / End button that shares for that trip only
<LiveTrackingMap entity="Ride" trip={ride.id} pickup={{ lat, lng }} dropoff={{ lat, lng }} height={320} />   // optional `heading="pickup"|"dropoff"`: which end they are going to (else read from the trip's stage)
    // the driver, both ends, the road, "To pickup: 2.1 mi · 9 min · arrives 14:05" and where the route came from
<MapView points={[{ id, lat, lng, label, tone }]} route={path} keepInView />   // any other map: pins and a line
```

- `entity` is the record type the trip is (the same one the web page names) and `trip` its id: the server lets only
  the people who may open that record follow or share it.
- The person on the move shares; the customer and the administrator watch. The phone asks permission itself.
- A screen shows a distance and a time, never coordinates. `useRoute(from, to)` gives `{ route, remainingKm, etaMin,
  arriveAt }` if a page needs the numbers alone.
- Sharing works while the app is open in front of the person. It does not run with the screen off (that needs
  background location and a real build, not Expo Go); say so on a screen where it matters.
- The map uses Apple Maps on iPhone and Google Maps on Android (the Android build's key is `GOOGLE_MAPS_ANDROID_KEY`).
- `MapView` takes `height` (points; default 320) and `keepInView`. A pin's `tone` is one of `primary`, `accent`, `muted`,
  `danger` and nothing else (there is no `neutral`); the end being driven to is `accent`, the other `muted`.
- Some values are narrow, and a wider word fails to compile: `WorkflowForm`'s `submitVariant` is `primary` or `accent` only,
  and a `Text` tone is one of the tones listed for `Text` (not `neutral`). `useWidget(...)` returns the widget in `.data`.

### A map that IS the screen (a person out and moving: a driver, a courier, a technician on the way)

For someone who works from the road, the map is the app, the way every ride-hailing and delivery app is built: the map fills
the glass, a compact panel floats on top, round buttons float at the side, and a sheet slides up from the bottom with what
to do next. Use `MapScreen` for that screen. Do NOT use it for a form, a list or a settings page, and do not put a map
inside a card on a page of cards for a person who is driving.

```tsx
import { MapScreen, BottomSheet, FloatingPanel, FloatingButton, Row, Text, Button, StatusBadge } from "@/ui";

<MapScreen
  points={[{ id: "pickup", lat, lng, label: "Pickup", tone: "accent" }]}   // only places the record really has
  route={nav.route?.path}                                                  // from useRoute(from, to)
  top={<FloatingPanel><Row>…avatar, Online / Offline, earnings today…</Row></FloatingPanel>}
  controls={<FloatingButton icon="call" label="Call the rider" onPress={call} />}
>
  <BottomSheet snapPoints={[0.24, 0.55]} header={<Text variant="heading">Arrived at pickup</Text>}>
    …who, where, how far… <Button variant="accent" onPress={start}>Start ride</Button>
  </BottomSheet>
</MapScreen>
```

- `MapScreen` follows this device's position (blue dot, camera) until the person drags the map, and a recentre button takes it
  back. It says in words when the location is blocked, cannot be found, or is old. `followUser={false}` frames the places given
  instead (a request preview). It draws no header: it is the whole screen.
- ONE STATE, ONE SHEET. The screen is a state machine over the record's own status (waiting, request, to pickup, arrived,
  in trip, done): each state is one `BottomSheet` with its header, the few facts that matter, and the ONE `variant="accent"`
  action. The sheet changes when the status changes (`index` makes it controlled); never show every fact at once, never a
  long scroll. A request is a sheet over the map with a countdown and Accept / Decline, not another page.
- A sheet's `snapPoints` are resting heights (shares of the room, e.g. `[0.24, 0.55, 0.9]`, or points). The person drags it;
  it never dims the map. A pick-one or a confirmation is still a `Sheet` / `Dialog`.
- Put floating parts in `top` (a `FloatingPanel`: compact, one line of facts), round buttons in `controls`
  (`FloatingButton`, 48 pt or more, with a `label`). Nothing else floats: the map stays visible.
- `MapView height="fill"` is the same map without the screen around it. `useDevicePosition()` reads where the device is
  if a screen needs the number. No made-up position, ever: with no fix show the last known spot and say so.

## `@/ui` — the component kit

React Native core only; every colour/size/radius comes from the theme; 44 pt
touch targets; accessibility roles and labels throughout.

```
Screen({ title?, subtitle?, back?, right?, scroll=true, padded=true, loading?, error?, onRetry?, empty?, onRefresh?, refreshing?, footer? })
Header, Title, Text({ variant: display|title|heading|body|label|caption, tone: default|muted|primary|accent|danger|success|warning|inverse, weight: regular|medium|semibold|bold, align })
Stack({ gap, padding, align, justify }), Row({ …, wrap })   // gap/padding: xs|sm|md|lg|xl|xxl; align: start|center|end|stretch|baseline; justify: start|center|end|between|around, Spacer({ size? }), Divider, Card({ onPress?, variant: filled|muted|inverse, padding })
Button({ variant: primary|accent|secondary|outline|ghost|danger, size: sm|md, icon?, loading, disabled, fullWidth, onPress })   // icon: an Icon name; sm+ghost is a compact row action
ListView({ list, renderItem(item, i), keyExtractor?, empty?, header?, separators?, spaced? })   // list = what useList returns: states, pull-to-refresh, onEndReached   // a list of CARDS is `spaced` (space between them, not hairlines)
ListItem({ title, subtitle?, meta?, leading?, badge?, trailing?, onPress? })
Badge({ tone: neutral|info|success|warning|danger|accent, dot? }), StatusBadge({ status }) /* a tinted pill with a dot */, Tag({ onPress?, selected? }), Avatar({ name, image, size }), StatTile({ label, value, delta?, hint? }), Money({ value, currency? })
Chips({ items: [{ key, label, count? }], value, onChange })   // filter chips that scroll sideways to the screen edges, never wrap
Dots({ value, max = 5 })                                      // 3 of 5 as dots: a priority, a level
Icon({ name, size?, tone?, color? })                          // an Ionicons glyph (add, search, checkmark-circle, trash-outline, construct, ...)
Loading, Empty({ title, message?, action?, icon? }), ErrorState({ message, onRetry? })   // Empty icon: an Icon name, drawn in a soft circle
SimpleChart({ type: bar|line|pie|donut, data | labels + series, format?, height?, horizontal? })   // Views only; pie/donut = proportion bar
WidgetView({ widget, data, height?, currency?, action?, title? })                    // metric, gauge, text, chart (+ table), list
GradientBand({ children, style?, bleed? })   // a padded, rounded band by default (`bleed` = style it yourself, edge to edge); the design's brand gradient (gradientStart -> gradientEnd, else primary -> accent) as a band; text on it is colors.primaryForeground; ONE per screen, never behind a form or list
AuthFrame({ title, tagline?, footer?, children })   // the sign-in / sign-up screens' frame: a band in the primary colour with the app's mark and name, a card for the form
SignInForm({ submitLabel? }), SignUpForm({ submitLabel? }), SwitchAuthLink({ to: "signin" | "signup" })   // the ONLY parts that make a session or an account; a sign-in / sign-up screen places one and draws the rest
Sheet({ visible, onClose, title }), Dialog({ visible, message, confirmLabel, variant, onConfirm, onCancel })
Fields (value/onChange, label, required, help, error, disabled):
  TextField(kind: text|textarea|email|tel|url|password), NumberField, MoneyField, SelectField({ options }), MultiSelect({ options }),
  TagsField, SwitchField, DateField(kind: date|time|datetime — typed 2026-03-01 / 14:30), ImageField, FileField, LocationField, Field (the shell)
WorkflowForm({ workflow, fields, initial?, submitLabel?, submitVariant?, cancelHref?, redirectTo?, successMessage?, onDone?, groups?, steps?, submitPlacement? })   // onDone(result) runs after EVERY attempt, a refused one too: test `result.ok` before leaving the screen or closing a sheet (or use redirectTo)
WorkflowButton({ workflow, input, children?, variant?, size?, confirm?, redirectTo?, successMessage?, fullWidth? })
LanguageSwitch, ErrorBoundary, useTheme()
```

`WorkflowForm` is the web's: `fields` is a record with one entry per workflow
input (`{ label, kind?, options?, placeholder?, help?, min?, max?, render? }`, or
`{ value }` to fix it), the same `kind`s (`text textarea email tel url password
number date time datetime select multiselect tags checkbox switch image file
location`) plus native `money`. Required inputs are marked and checked before
anything is sent.

## Tests

`bash run-native-tests.sh` runs the pure logic (cookie jar, sign-in sequence over
a fake app, reads, workflow results, form validation, formatting, chart and gate
logic) under plain node. They need a Node with `module.registerHooks` (v22.15+);
set `NODE22` to one if the default is older.
