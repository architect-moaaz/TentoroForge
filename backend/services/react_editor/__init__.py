"""The visual React editor — the Editor tab over a Blueprint's coded pages.

A coded page is a `pageCode` row: `view.tsx` and `load.ts`, written against the
app SDK and accepted only when they compile. The editor edits those rows —
never a schema beside them, never the rendered DOM — through:

* :mod:`adapter` — the parser-based source adapter (``static/react-model.mjs``)
  that models the JSX with stable ids and applies operations as span splices;
* :mod:`service` — open a page at a revision, apply a transaction with
  optimistic concurrency and the compiler's check, keep per-page history, and
  restore a known-good revision;
* :mod:`registry` — what can be added and how each kind is configured, in the
  words a first-time user reads;
* :mod:`smith` — a scoped Smith proposal: prompt → staged replacement of the
  selected nodes → validation → apply as one revision;
* :mod:`diagnostics` — the compiler's words into plain ones.
"""
