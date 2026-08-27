# Using a Generated App

After clicking **Export** in the Tentoro Forge editor, you'll download a
`.tar.gz` containing your generated Next.js application. This guide
covers running it locally, deploying it, and editing schemas after
export.

---

## What you downloaded

The tarball contains a self-contained Next.js 15 + React 19 project:

```
<project-id>/
├── package.json              # deps pinned to vendored engine stack
├── next.config.js
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── src/
│   ├── app/
│   │   ├── layout.tsx        # loads design-spec + nav-flow, wraps EngineProvider
│   │   ├── page.tsx          # redirects to /home
│   │   ├── [...slug]/
│   │   │   └── page.tsx      # reads src/schemas/<slug>.json → <Engine>
│   │   ├── globals.css       # project tokens + base styles
│   │   └── not-found.tsx
│   ├── schemas/              # one JSON per page — the editable content
│   │   ├── home.json
│   │   ├── notes.json
│   │   └── ...
│   └── contracts/
│       ├── design-spec.json  # palette + register + entityPhotos
│       ├── nav-flow.json     # routes + transitions + guards
│       └── tokens.json       # color / typography / spacing tokens
└── vendor/
    └── @tentoroforge/        # pre-built engine + library + renderer + schema
        ├── engine/dist/
        ├── library/dist/
        ├── renderer/dist/
        └── schema/dist/
```

Everything in `vendor/@tentoroforge/` ships inside the tarball — no
private registry credentials are needed.

---

## Run locally

```bash
tar -xzf <project-id>.tar.gz
cd <project-id>
npm install
npm run dev
```

Open http://localhost:3000 — your generated app is running.

The first `npm install` takes ~30 seconds. Next.js, React, and
Tailwind come from the public npm registry; everything in
`@tentoroforge/*` resolves from the local `vendor/` directory.

---

## Project layout

| Path | What it is |
|---|---|
| `src/schemas/` | One JSON file per page — this is the editable content layer |
| `src/contracts/design-spec.json` | Palette, component register, entity photos |
| `src/contracts/nav-flow.json` | Routes, transitions, and auth guards |
| `src/contracts/tokens.json` | Color, typography, and spacing tokens |
| `src/app/[...slug]/page.tsx` | Route handler — maps URL slug to a schema file |
| `vendor/@tentoroforge/` | Pre-built engine packages (do not edit) |

---

## Deploy to Vercel

```bash
npm install -g vercel
vercel
```

Vercel auto-detects Next.js 15 and runs `npm install && npm run build`.
The deployed app reads its schemas + design-spec + nav-flow from disk
at request time — same as the local dev server.

For other hosts (Netlify, Cloudflare Pages, Railway, self-hosted), the
project is a standard Next.js app: build with `npm run build`, serve
with `npm start`.

### Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Base URL for `/api/*` data fetches | empty (same-origin) |

If your app's schemas reference a backend API for live data, set
`NEXT_PUBLIC_API_URL=https://your-api.example.com` in the deploy
environment. With no value set, the engine uses same-origin.

---

## Editing schemas

Page schemas are plain JSON. The easiest workflow:

1. Edit any file in `src/schemas/` with your editor
2. Save — Next.js dev server hot-reloads the change
3. Refresh the page in your browser

For example, to change the dashboard title, edit
`src/schemas/home.json`:

```json
{
  "schemaVersion": "2",
  "id": "home",
  "route": "/",
  "root": {
    "type": "Hero",
    "id": "hero",
    "props": {
      "headline": "Welcome back, Alex"
    }
  }
}
```

Each node follows this shape:

```json
{ "id": "<unique>", "type": "<ComponentName>", "props": { ... }, "children": [ ... ] }
```

### Visual editing

For drag-and-drop, click-to-select, and properties-panel editing,
re-open the project in the Tentoro Forge editor. This requires the
Tentoro Forge dev environment running locally (backend on port 6500,
frontend on port 6501, render-scaffold on its own port).

---

## Component vocabulary

Schemas can use any component from `@tentoroforge/library`. Common ones:

| Type | Use |
|---|---|
| `Stack` / `Row` / `Grid` | Layout containers |
| `Hero` | Page hero with background + CTAs |
| `MetricTile` | Stat tile with label + value |
| `Card` / `Section` | Surface containers |
| `Heading` / `Text` | Typography |
| `Button` / `IconButton` / `Link` | Interactive elements |
| `Input` / `Textarea` / `Select` / `Checkbox` | Form fields |
| `Avatar` / `Badge` / `Breadcrumb` | Display |
| `Table` / `Chart` / `Timeline` | Data |

The full component list is available in
`vendor/@tentoroforge/library/dist/`.

---

## Troubleshooting

### `npm install` fails with `ENOENT … @tentoroforge/engine`

The `vendor/` directory is missing from your tarball, or was deleted.
Re-export from the editor.

### Pages render with literal `{{user.name}}` text instead of real data

The schema has Mustache bindings pointing at data sources that aren't
wired up. Options:

- Set `NEXT_PUBLIC_API_URL` so `/api/*` calls find your backend, or
- Hard-code values in `src/schemas/<page>.json` (replace `{{...}}`
  with literals), or
- Add fixture data to a mock endpoint matching the page's
  `dataSources`.

### `Module not found: @tentoroforge/library`

You ran `npm install` from a directory other than the project root.
`vendor/` is resolved relative to the project's `package.json` — `cd`
into the project directory first.

### Pages 404 after running `npm run dev`

`src/schemas/<slug>.json` doesn't exist for the URL you're visiting.
Either the file genuinely isn't there (regenerate from the editor) or
the slug doesn't match a file (e.g. visiting `/dashboard` when the file
is `home.json`). Check `src/contracts/nav-flow.json` for the canonical
slug-to-page map.

### `npm run build` fails on deploy

Most build failures are TypeScript or import errors surfaced only
during production build. Run `npm run build` locally first to catch
these before deploying. The `vendor/` packages ship pre-built, so type
errors there are rare — look at your `src/` files first.
