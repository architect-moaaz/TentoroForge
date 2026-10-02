// The routes this application declares, and which control runs which
// workflow — the two lookups `error_reporter.ts` needs to describe a crash in
// the owner's own words instead of in ids.
//
// WRITTEN BY THE PROJECTION. `services.blueprint.projection.project_dispatches`
// overwrites this file from the same dispatch contract that feeds the
// build-time dry run (`src/contracts/dispatches.json`), so what the reporter
// can name at run time is exactly what `verify_dispatches` named at build
// time. This copy is the empty one the runtime ships with, so an app that has
// not been projected still compiles: the reporter then sends no route and
// names no control, which is the honest result of knowing neither.

/** Every route the application declares, as patterns (`/cases/[id]`). */
export const ROUTES: string[] = [];

/** workflow id -> the controls wired to it. */
export const CONTROLS: Record<string, Array<{ route: string; control: string; label: string }>> = {};
