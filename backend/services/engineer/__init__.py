"""The engineer: one owner per app, building by proof.

The build was a graph of 33 steps authored by 22 agent roles, each filling
one slice of the definition from a filtered view of the rest, judged by code
and run only at the end. Nobody was responsible for the app working, and
nobody saw it running while it was built: 9 of 35 apps on forge-v3 shipped
with no page code, 5 processes with no steps were wired to live buttons,
and 126 of 169 statements were never tried (2026-10-09).

The engineer builds the approved definition feature by feature — a module
the person agreed to — and for each: its screens and processes are written
(the specialists draft, as tools), the app is projected and built on the
Workbench, the feature's statements are tried, what fails is fixed, and only
then does the next feature start. See docs/plans/2026-10-09-engineer-owned-build.md.

- `features`: the plan — modules in order of dependence, and what of each
  node belongs to one.
- `journal`: a durable job — what was done, on disk, resumable; a time
  budget; one engineer per app at a time.
- `build`: the loop.
"""
