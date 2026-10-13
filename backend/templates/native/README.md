# __APP_NAME__ — Native app

The native (Expo / React Native) app for __APP_NAME__. One screen for each page of
the web app, talking to the web app's own HTTP API as the same signed-in person.
Produced by Tentoro Forge. There is no database here and no second set of rules:
reads, workflows, access and tenancy are the web app's.

```bash
cd mobile            # this folder
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
app/login.tsx          email + password sign-in (reads /api/auth/methods first)
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
| `src/config.generated.ts` | `APP_NAME: string`, `CURRENCY: string` (ISO 4217), `LOCALE: string` (BCP-47), `LANGUAGES: readonly { tag; dir: "ltr" \| "rtl" }[]`, `PRIMARY: string`, `HOME: string` (route a signed-in person lands on), `PUBLIC_ROUTES: readonly string[]` (routes, and their children, open without sign-in; `[]` = all private), `ACCOUNT: null \| { entity; fields; labelField; locationField }` (the web's `lib/account.ts`) |

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
useMe()                                  // { user, account }
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

## `@/ui` — the component kit

React Native core only; every colour/size/radius comes from the theme; 44 pt
touch targets; accessibility roles and labels throughout.

```
Screen({ title?, subtitle?, back?, right?, scroll=true, padded=true, loading?, error?, onRetry?, empty?, onRefresh?, refreshing?, footer? })
Header, Title, Text({ variant: display|title|heading|body|label|caption, tone, weight, align })
Stack({ gap, padding, align, justify }), Row({ …, wrap }), Spacer({ size? }), Divider, Card({ onPress?, variant: filled|muted|inverse, padding })
Button({ variant: primary|accent|secondary|outline|ghost|danger, size: sm|md, loading, disabled, fullWidth, onPress })
ListView({ list, renderItem(item, i), keyExtractor?, empty?, header?, separators? })   // list = what useList returns: states, pull-to-refresh, onEndReached
ListItem({ title, subtitle?, meta?, leading?, badge?, trailing?, onPress? })
Badge({ tone }), StatusBadge({ status }), Tag({ onPress?, selected? }), Avatar({ name, image, size }), StatTile({ label, value, delta?, hint? }), Money({ value, currency? })
Loading, Empty({ title, message?, action? }), ErrorState({ message, onRetry? })
SimpleChart({ type: bar|line|pie|donut, data | labels + series, format?, height?, horizontal? })   // Views only; pie/donut = proportion bar
WidgetView({ widget, data, height?, currency?, action?, title? })                    // metric, gauge, text, chart (+ table), list
Sheet({ visible, onClose, title }), Dialog({ visible, message, confirmLabel, variant, onConfirm, onCancel })
Fields (value/onChange, label, required, help, error, disabled):
  TextField(kind: text|textarea|email|tel|url|password), NumberField, MoneyField, SelectField({ options }), MultiSelect({ options }),
  TagsField, SwitchField, DateField(kind: date|time|datetime — typed 2026-03-01 / 14:30), ImageField, FileField, LocationField, Field (the shell)
WorkflowForm({ workflow, fields, initial?, submitLabel?, submitVariant?, cancelHref?, redirectTo?, successMessage?, onDone?, groups?, steps?, submitPlacement? })
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
