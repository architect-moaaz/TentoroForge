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

## Two workers

The backend runs `uvicorn --workers 2`: two copies of the program, each with its own memory, answering the same port. A request can land on
either. The list of running servers used to be in one copy's memory, so a start on worker A was invisible to worker B (503 "not running",
a second server started, the working folder deleted under the first one's Metro, and a cap of 3 that was 3 per worker).

It is now a small file per project (`services/phone_live_registry.py`, in `dev_servers.DIR/phone-live`, shared by every worker):
`{id, outputDir, state, port, pid, stage, owner, token}`. Its modified time is "last used".

* **Starting:** `claim` takes a lock, looks at the file, and starts only if no live server or start in progress is there. If the
  organisation already holds `FORGE_PHONE_LIVE_PER_ORG`, it ends that organisation's own least recently used server (over all workers); if
  the platform holds `FORGE_PHONE_LIVE_MAX` it refuses (`CapReached`), and never ends another organisation's. A second start, from any
  worker, changes nothing.
* **Using:** any worker reads the port from the file and passes the request to `127.0.0.1:port` itself. The status, "unreachable", sync
  and stop work from any worker. Only the worker that claimed a record (its `token`) writes its progress.
* **A worker that dies:** its servers have nothing watching their files. Every worker's reaper ends what is failed, idle (`FORGE_PHONE_LIVE_IDLE`),
  or left by a worker that is gone; the next start brings it back.
* **A cancelled install:** every step that runs npm starts it in its own process group and, on a cancel or a timeout, ends the whole group
  (`phone_preview._run`, `native_build._npm_run`), so a stopped start no longer leaves an install running in the shared packages.
* **Builds of the built picture** (`phone_preview.start`) hold a file lock per project, so one runs at a time over all workers, and a build
  cut off with its worker is seen as cut off.
* **Checked with real processes** (2026-10-23): worker A started FocusFlow's preview; worker B (another process) saw it ready on the same
  port, its own start changed nothing, it reached Metro (200), synced, and stopped it.
* **Not covered:** Linux (the registry uses `/proc` start times and process groups there; Windows uses `taskkill`), and the full backend image.

## What an anonymous caller can do, and what the picture runs in

The picture's address needs no sign-in (an iframe cannot send the platform's token). Two things keep that safe (PR #28 review, 2026-10-22).

**What it will do for anyone.**
* **One bundle.** Only the app's one entry bundle (and its source map), with exactly the options the page itself names it by, is passed to the dev
  server (`phone_live_proxy.bundle_allowed`; the entry is read from the dev server's own page at start and written in the registry record).
  Checked on a real picture: the page asks for this one bundle, and opening its other screens asks for no other. Any other path or option gets 404.
* **Messages.** Over the `/hot` socket only `register-entrypoints` (naming that same entry) and `log` messages go on to the dev server; anything else,
  non-JSON, binary, or over 64 KB is dropped (`message_allowed`). A message naming an address the dev server does not know once stopped the whole
  server. At most 8 sockets per project.
* **Nothing the caller does keeps a server alive.** The picture's own requests no longer mark a server as used. The editor's signed-in status call
  does (`phone_live.touch`, every 8 s while the live preview is ready), and so do start and sync: a server ends 10 minutes after the editor is closed.
* **A limit.** 900 requests a minute (burst 240) per caller and project for `/phone/serve` and `/phone/live`: a page load is a dozen files, so a
  page never reaches it.

**What the page runs in: a sandbox.** The picture is a generated app's code served from the platform's own address, and the platform keeps its sign-in
in `localStorage`; on that origin a screen's code (or a package's) could read a viewer's token, and the link can be sent to anyone signed in. So:
* the responses carry `Content-Security-Policy: sandbox allow-scripts` (no `allow-same-origin`) and `frame-ancestors 'self'`, plus
  `X-Frame-Options: SAMEORIGIN` and `Access-Control-Allow-Origin: *` for GET and HEAD (`middleware/security_headers.py`). The page gets an origin of
  its own (`null`) with no storage and no cookies, whether framed or opened directly from a link;
* the editor's iframe has `sandbox="allow-scripts"` too (`PhonePreview.tsx`); it talks to the page by `postMessage` only, checked by `e.source`;
* a sandboxed page that touches `localStorage` or `document.cookie` gets an error, so each page starts with a small stand-in that keeps them in
  memory where the real ones throw (`services/phone_sandbox.py`; the built picture gets it when it is served, so one built earlier does too);
* a sandboxed page is a different origin, so its fonts need CORS on every hop. The dev web server in front of the backend answers `/assets/?x` with
  a redirect that has none, so the bundle's asset address is written without that slash (`/assets?x`; Metro serves both).
* Checked in Chrome through Playwright: origin `null`, a decoy in the platform's storage not readable, the editor's messages and both sockets working,
  fonts and icons loading, no failed request, no console error, and a hot update arriving without a reload.
* Not covered: the website editor's own preview (`/preview/serve`), which has the same weakness and is a different route.

## Fail safe

The editor falls back to the built picture (and its Redraw button) whenever the live preview is not ready: while it starts (about 30 s the
first time), if it cannot start, if the Expo files are not as expected, or if Metro stops answering (the next status poll shows `failed`).
Only the Editor asks for the live preview; the Phone tab on its own keeps the build.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `FORGE_PHONE_LIVE_IDLE` | 600 | seconds without use before a project's dev server is stopped |
| `FORGE_PHONE_LIVE_MAX` | 4 | dev servers at once on the platform (over all workers). A start beyond it is refused, with a sentence; the editor keeps the built picture. Nobody else's server is ended to make room. |
| `FORGE_PHONE_LIVE_PER_ORG` | 2 | dev servers one organisation may run. A start beyond it ends THAT organisation's least recently used one. |

Each dev server holds about 300 MB (Metro 230 MB plus the `npx` wrapper 65 MB, measured on Cart Buddy) and more after many bundles: size the
backend container for `FORGE_PHONE_LIVE_MAX` of them. Dev servers are stopped when the backend shuts down.

## Keeping the copy current

`phone_live.sync_files` copies what changed in `native/app` and `native/src` into the live copy and removes what is gone; the preview's own
files (`src/sdk/api.ts`, `preview.ts`, `preview-data.json`) are never touched. A watcher checks every 0.3 s, so a change made by the editor,
by Smith or by a build all arrive; the editor also asks for a sync as soon as it has saved a change.

A change to the app's packages (`package.json`) needs the live preview restarted.
