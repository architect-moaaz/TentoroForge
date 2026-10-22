# The live phone preview

A change to a phone screen shows in the Editor's picture in under a second, instead of the ten seconds a rebuild takes.

## What it is

`services/phone_preview.py` draws the whole picture again for every change (`expo export`, about 10 s). `services/phone_live.py` instead keeps
Metro (Expo's dev server) running for the project, on its own copy of the phone project, and Metro swaps the changed piece into the page that
is already open (hot reload). Measured on Cart Buddy (Windows): 0.3-0.4 s for words and for a colour at Metro; 0.7 s from the editor starting to
save a change to the picture showing it, through the backend.

## How the browser reaches it

The browser never talks to Metro. Metro listens on `127.0.0.1` and a free port inside the backend's own machine/container. The backend passes
requests on under `/api/projects/{short_id}/phone/live/` (`routers/phone_live.py`, `services/phone_live_proxy.py`):

* Everything rides on `/api/*`, which the front door already forwards (Caddy: `handle /api/*`, WebSockets included; nginx: the `Upgrade`
  headers in `location /api/`). No new port, host name or certificate.
* Only what a page needs is passed on (the page, `*.bundle`, `assets/`, `_expo/`, a few static files) and the two sockets `/hot` and
  `/message`. Metro's own tools (open a file in an editor, the debugger, symbolicate) are refused before they reach it.
* Starting, syncing and stopping need the person's session. Loading the picture does not (an iframe cannot send the bearer token), as for
  `/phone/serve`.

## Three things that only a live run showed

1. **Metro stops if the page's socket tells it the wrong address.** The page names its bundle by full address, which carries the path it is
   served from; Metro reads that path as a file to find, did not, and the whole server stopped. The socket's text has the prefix removed on its
   way in (`phone_live_proxy.unprefixed`).
2. **Expo's router strips its base path only in a production build.** Under a path prefix in development it finds no screen. An earlier
   version moved the page's address to `/` (`history.replaceState`); any full reload then loaded the platform's own home page inside the phone
   frame ("I drop a part and it takes me to the home page"). Now the live copy's router files (`getStateFromPath.js`, `getPathFromState.js`)
   are swapped for copies that handle the base path in development too, and the page keeps its real address. The router then reports every
   pathname with the base path in front, so the app's gate (`templates/native/src/sdk/gate.ts`) removes `EXPO_BASE_URL` before it decides
   whether a route is public; without that, a signed-out visitor to a public `/` was sent to `/login`.

3. **The app's entry file is outside the project** (the packages are linked from the real phone project), so Metro names it by climbing out.
   On Windows it writes `..%5C..%5C`; on Linux plain `../../`, which a browser collapses before asking. The climb is written as `..%2F`
   (`_no_dot_segments`); Metro reads it back as slashes.

Expo's two socket files open `ws://<host>/hot` and `/message` at the top of the host, with no way to add a path. The live copy swaps them for
patched copies that read the prefix from the page (`window.__FORGE_LIVE__`, set by the proxy), through a `metro.config.js` resolver
(`phone_live.write_live_files`). If those files are not the version it knows (a different Expo), `LiveUnavailable` says so.

4. **Expo hands out assets from the top of the host.** `expo start` fixes the asset base at `/assets/?unstable_path=.` (it cannot be set in a
   config file) and writes it into every bundled asset, so the icon font was asked for at the platform's own address: a 404 and no icons. The
   address is plain text in the bundle, so the proxy moves it under the prefix, in bundles and in live updates (`rewrite_bundle`).
5. **Expo's "Refreshing... Using Fast Refresh" bar** would cover the phone's tab bar on every change; the live copy swaps the module that
   announces it for a silent one.

## Checked on Linux

Run in a `node:20-bookworm` container (the backend image's Node major) with the Cart Buddy phone project installed there and this package's own
`phone_live.start` driving a real Metro: it started in 6-14 s; Metro wrote the entry path with plain `/../../../native/…` (the Linux case in 3.
above) and the rewritten `..%2F` form was served (HTTP 200, 4.7 MB, patched sockets in the bundle); registering the entry the way the page does
kept Metro alive; a file change reached the live-update socket as an `update` of 2 modules in 0.9 s, through the backend's watcher and Linux file
watching; stopping left no `expo` process (process-group kill). Not run: the full backend image behind Caddy.

## Fail safe

The editor falls back to the built picture (and its Redraw button) whenever the live preview is not ready: while it starts (about 30 s the
first time), if it cannot start, if the Expo files are not as expected, or if Metro stops answering (the next status poll shows `failed`).
Only the Editor asks for the live preview; the Phone tab on its own keeps the build.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `FORGE_PHONE_LIVE_IDLE` | 600 | seconds without use before a project's dev server is stopped |
| `FORGE_PHONE_LIVE_MAX` | 3 | dev servers at once; one more stops the one used least recently |

Each dev server holds about 300 MB (Metro 230 MB plus the `npx` wrapper 65 MB, measured on Cart Buddy) and more after many bundles: size the
backend container for `FORGE_PHONE_LIVE_MAX` of them. Dev servers are stopped when the backend shuts down.

## Keeping the copy current

`phone_live.sync_files` copies what changed in `native/app` and `native/src` into the live copy and removes what is gone; the preview's own
files (`src/sdk/api.ts`, `preview.ts`, `preview-data.json`) are never touched. A watcher checks every 0.3 s, so a change made by the editor,
by Smith or by a build all arrive; the editor also asks for a sync as soon as it has saved a change.

A change to the app's packages (`package.json`) needs the live preview restarted.
