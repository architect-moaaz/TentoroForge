# Draft: let `data_model` reply in the shape it can afford

**Status:** draft, nothing built. Written 2026-09-01, from the reference of the
legacy generation pipeline's entity planner.

## The problem, measured

`data_model` authors every entity in one reply. On the Palestinian Legislative
Council brief it does not finish:

```
RAISED after 564s — MalformedEnvelope: data_model: reply was not JSON:
Unterminated string starting at: line 1 column 45183
```

Truncated JSON does not parse, so it repairs and retries — ~9 minutes an
attempt. Two runs spent ~38 minutes each producing nothing, stopped at 3/18
with `data.entities` missing and no error logged.

`22eb606` took `data_model` off the default `high` effort, because on Opus 5
the reply and the reasoning share `max_tokens` and thinking was crowding out
the answer. That helped — the same whole-application call returned 109
proposals at `medium` — but it is not enough. A later run at 49 requirements
and 12 modules ran its full 8m40s, failed to commit, and started again.

Effort was one lever. This is the other, and it is the larger one.

## Where the tokens go

Agents reply in an artifact envelope: `{section, natural_key, body}`, and
`body` is **the artifact encoded as a JSON string**. So every quote inside
every field is escaped — `{"name":"x"}` travels as `"{\"name\":\"x\"}"`.

Measured on the largest data model on disk (21 entities,
`output/ee946f21-…/current.json`):

| shape | chars |
|---|---|
| envelope, `body` as JSON-in-JSON | **47,715** |
| the same entities as a legacy-style dict (`name: type`) | 6,123 |
| **compact, losing nothing** (below) | **17,301** |

The reply truncated at 45,183 characters. A **21-entity** model already exceeds
that as envelopes. The PLC domain needs around thirty — twenty terminology
terms plus join entities. It was never going to fit, at any effort.

The legacy pipeline never met this ceiling because it emitted
`entities: {Name: {fields: {...}}}` — one dict, no envelope, no escaping. It
was not faster because Sonnet is faster. It was smaller.

## What to change

**One node's reply shape. Not the Blueprint, not the contract, not the
storage.** The envelope is how artifacts are *stored* and identified; there is
no reason the model should pay tokens to write one. Let `data_model` answer in
the compact shape and expand it into proposals in code.

The compact shape keeps everything the pipeline actually consumes — types,
`sensitive`, `references`, `required`, `enumValues`, constraints — and drops
only the ceremony. Flags appear when true and are absent when false, which is
where most of the 2.8× comes from:

```json
{"entities": {
  "Customer": {
    "fields": {
      "id":    {"type": "uuid", "required": true},
      "name":  {"type": "string", "sensitive": true, "required": true},
      "blocId": {"type": "uuid", "references": "Bloc"}
    },
    "description": "…"
  }
}}
```

### The edit

1. **A per-node reply schema.** `PROPOSAL_SCHEMA` is currently the one shape
   every agent answers in. `data_model` gets its own — `{entities, confidence,
   assumptions, issues, change_requests}` — so the constraint the model is held
   to is the shape we want, not a shape we then hope it fills correctly.

2. **Expand in `make_executor`.** Where the reply is parsed, a `data_model`
   branch turns each `entities` key into an `ArtifactProposal(section=
   "data.entities", natural_key=<name>, body=<expanded>)`. Field dicts become
   the field list the contract expects; a bare `"type"` string expands to
   `{"name": …, "type": …}`. Everything downstream — `svc.upsert`, the
   allocator, `natural_key` identity, re-run idempotency — is untouched,
   because it still receives exactly the proposals it receives today.

3. **Nothing else moves.** `data.entities` stays an ID-bearing list keyed by
   name. The Blueprint contract, `database` projection and page planner all
   read what they read now.

### Why not the alternatives

- **Raise `max_tokens`.** The ceiling is already 32,000 and shared with
  thinking; the previous raise from 16,000 bought one app's headroom and this
  brief ate it. Paying 7.8× for escaping and then buying more budget is the
  wrong end of the problem.
- **Fan out per module** (`d65eda2`, reverted). Twelve calls and a new DAG
  dependency to work around the reply shape. It also splits a data model whose
  join entities — `BlocMembership`, `CommitteeMembership`, `StaffAssignment` —
  span modules, and stitches them together by name-matching afterwards.
- **A smaller model for this node.** Worth measuring separately. It addresses
  latency, not size: Sonnet emitting envelopes would truncate too, just sooner.

## What this does not fix

There is still **no timeout on the Anthropic client and no bound on a wave**
(`executors.py:341`, `orchestrator._gather`). A node that stops returning stops
the build in silence. The truncation was survivable; the silence was not, and
it is what made this take three runs to find.

## How to know it worked

The PLC brief is the test: 49 requirements, 12 modules, ~30 entities. Today it
reaches 3/18 and stops. It should write `data.entities` and continue. The
compact reply for thirty entities is ~25,000 characters against a 32,000-token
budget — comfortable rather than marginal, which is the point. Sitting just
inside the limit is what produced a bug that appeared on some briefs and not
others.
