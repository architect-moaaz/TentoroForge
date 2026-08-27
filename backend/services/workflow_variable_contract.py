"""Workflow variable-provenance contract (working-app reliability — Part B).

A gateway/condition node branches on an EXPRESSION that reads variables:

    "overallRecommendation = 'Hire'"   ->  reads {overallRecommendation}

For the branch to be live, every variable it reads must be PRODUCED somewhere
upstream — by a `set_variable` node, an `ai_*` node's declared output, a
`db_query` result var, a trigger input field, or (when a registry is supplied)
a column on the trigger entity. If a referenced variable has NO producer, the
expression can never be satisfied and the branch is dead — every record routes
to the else path. This module DETECTS that so the pipeline can flag it.

Real example (output/f4pw5y5k/workflows/feedbackscoringworkflow.json): two
`exclusive_gateway` nodes branch on `overallRecommendation`, but the only
`set_variable` writes `compute_aggregate_score_done` and the `ai_generate` node
declares no output — so `overallRecommendation` is never produced.

SIMPLIFICATION: producers are collected over the WHOLE workflow (not
per-reachable-path). Path-sensitive reachability would tighten this, but a
whole-workflow producer set only ever SUPPRESSES findings (a var produced on a
sibling branch is treated as available), so it stays false-positive-safe. The
`referenced_vars(...) - producers(...)` residue is what gets reported.
"""
from __future__ import annotations

import re
from typing import Iterable

# FEEL-lite reserved words + string functions (mirrors
# templates/runtime/feel-lite/tokenizer.ts) — identifiers that are NOT variables.
_FEEL_KEYWORDS = {
    "if", "then", "else", "and", "or", "not", "in", "between",
    "true", "false", "null",
}
_FEEL_FUNCTIONS = {
    "starts", "ends", "contains", "matches", "with",
    "sum", "count", "min", "max", "avg",
    "string", "number", "date", "now", "duration",
    "abs", "floor", "ceiling", "round",
}
# Roots that name a namespace/ambient, not a produced variable.
_AMBIENT_ROOTS = {"input", "variables", "trigger", "user", "env", "now"}

_RESERVED = _FEEL_KEYWORDS | _FEEL_FUNCTIONS

# A dotted identifier path: `application.stage`, `foo`, `a.b.c`.
_IDENT_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# String literals (single- or double-quoted) — stripped before tokenizing.
_STRING_LIT = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
# `{{ ... }}` mustache wrappers — unwrap so `{{overallRecommendation}}` reads too.
_MUSTACHE = re.compile(r"\{\{\s*|\s*\}\}")


def referenced_vars(expr: str) -> set[str]:
    """Root identifiers a FEEL-lite expression reads, EXCLUDING string/number/
    boolean literals, FEEL keywords/operators and string functions.

    Dotted paths collapse to their root (`application.stage` -> `application`),
    and a leading namespace root (`input`/`variables`) is peeled so the actual
    variable name survives (`input.overallRecommendation` -> `overallRecommendation`)."""
    if not expr or not isinstance(expr, str):
        return set()
    # Drop string literals first so their contents ('Hire') aren't tokenized.
    cleaned = _STRING_LIT.sub(" ", expr)
    cleaned = _MUSTACHE.sub(" ", cleaned)

    out: set[str] = set()
    for m in _IDENT_PATH.finditer(cleaned):
        path = m.group(0)
        segments = path.split(".")
        root = segments[0]
        # Peel a namespace root: `input.foo` / `variables.foo` -> `foo`.
        if root.lower() in {"input", "variables"} and len(segments) > 1:
            root = segments[1]

        low = root.lower()
        # A KEYWORD is never a variable.
        if low in _FEEL_KEYWORDS:
            continue
        # A FUNCTION name only counts as a function when it is CALLED.
        #
        # The reserved list was applied to bare identifiers too, so a column
        # genuinely named `count`, `min`, `max`, `sum`, `avg`, `contains`,
        # `matches`, `starts`, `ends` or `with` was silently discarded — and
        # those are ordinary column names. The dead-branch detector therefore
        # could not see a branch that reads one, so a branch depending on
        # `count` looked like it referenced nothing and was never flagged
        # (register VC-1). Only skip the name when a `(` follows it.
        if low in _FEEL_FUNCTIONS and len(segments) == 1:
            rest = cleaned[m.end():]
            if rest.lstrip().startswith("("):
                continue
        out.add(root)
    return out


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------

def _nodes(defn: dict) -> list[dict]:
    d = defn.get("definition") if isinstance(defn.get("definition"), dict) else defn
    nodes = d.get("nodes") if isinstance(d, dict) else None
    return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def _cfg(node: dict) -> dict:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cfg = data.get("config") if isinstance(data.get("config"), dict) else {}
    return cfg


def _iter_output_names(node: dict) -> Iterable[str]:
    """Every variable a node writes back to process state."""
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    cfg = _cfg(node)

    # set_variable / assignment
    for key in ("variableName", "name", "var", "outputVariable", "resultVar",
                "resultVariable", "assignTo"):
        v = cfg.get(key)
        if isinstance(v, str) and v:
            yield v

    # data.outputParams[].target|name  (the runtime writeOutputParams shape)
    for src in (data.get("outputParams"), cfg.get("outputParams")):
        if isinstance(src, list):
            for p in src:
                if isinstance(p, dict):
                    t = p.get("target") or p.get("name")
                    if isinstance(t, str) and t:
                        yield t

    # data.outputs[].name
    outs = data.get("outputs")
    if isinstance(outs, list):
        for o in outs:
            if isinstance(o, dict):
                t = o.get("name") or o.get("target")
                if isinstance(t, str) and t:
                    yield t


def _trigger_entity(defn: dict) -> str | None:
    for n in _nodes(defn):
        if n.get("type") == "trigger":
            ent = _cfg(n).get("entity")
            if isinstance(ent, str) and ent:
                return ent
    return None


def _trigger_input_fields(defn: dict) -> set[str]:
    """Variables the trigger makes available: its inputMapping targets + any
    declared input schema fields."""
    out: set[str] = set()
    d = defn.get("definition") if isinstance(defn.get("definition"), dict) else defn
    trig = d.get("trigger") if isinstance(d, dict) else None
    if isinstance(trig, dict):
        im = trig.get("inputMapping")
        if isinstance(im, dict):
            out.update(str(v) for v in im.values())
        for key in ("inputs", "inputFields", "fields"):
            fields = trig.get(key)
            if isinstance(fields, list):
                for f in fields:
                    if isinstance(f, str):
                        out.add(f)
                    elif isinstance(f, dict) and isinstance(f.get("name"), str):
                        out.add(f["name"])
    # Trigger NODE config (inputMapping/inputs on the node too).
    for n in _nodes(defn):
        if n.get("type") == "trigger":
            cfg = _cfg(n)
            im = cfg.get("inputMapping")
            if isinstance(im, dict):
                out.update(str(v) for v in im.values())
    return out


def _registry_entity_columns(registry: dict | None, entity: str | None) -> set[str]:
    """Columns of `entity` from a registry (`registry.json` shape:
    {entities: {Name: {fields: {col: {...}}}}}). Empty if unavailable."""
    if not registry or not entity:
        return set()
    entities = registry.get("entities")
    if not isinstance(entities, dict):
        return set()
    ent = entities.get(entity)
    # Tolerate slug/table/case drift by falling back to a case-insensitive match.
    if not isinstance(ent, dict):
        for k, v in entities.items():
            if isinstance(k, str) and k.lower() == entity.lower():
                ent = v
                break
    if not isinstance(ent, dict):
        return set()
    fields = ent.get("fields")
    cols: set[str] = set()
    if isinstance(fields, dict):
        cols.update(str(k) for k in fields.keys())
    elif isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict) and isinstance(f.get("name"), str):
                cols.add(f["name"])
            elif isinstance(f, str):
                cols.add(f)
    return cols


def producers(defn: dict, registry: dict | None = None) -> set[str]:
    """The set of variables produced upstream in the workflow.

    Includes: every node's declared output (set_variable `variableName`, ai_*
    `outputVariable`, `db_query` `outputParams[].target`, `data.outputs[].name`);
    trigger input fields; and — when a `registry` is supplied — the trigger
    entity's columns. Deliberately LIBERAL: over-including a producer only
    suppresses a finding, which is safer than a false positive."""
    prod: set[str] = set()
    for n in _nodes(defn):
        prod.update(_iter_output_names(n))
    prod.update(_trigger_input_fields(defn))
    prod.update(_registry_entity_columns(registry, _trigger_entity(defn)))
    return prod


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

_GATEWAY_TYPES = {"condition", "exclusive_gateway", "decision"}


def _branch_expression(node: dict) -> str | None:
    cfg = _cfg(node)
    for key in ("expression", "condition"):
        v = cfg.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return None


def analyze_workflow(defn: dict, registry: dict | None = None) -> list[dict]:
    """For each gateway/condition node with a branch expression, report every
    referenced variable that has no producer anywhere in the workflow.

    Returns a list of findings:
        {"type": "unproduced_gateway_var",
         "node": <node id>, "variable": <name>, "expression": <expr>}

    See the module docstring for the whole-workflow (non-path-sensitive)
    producer-set simplification."""
    prod = producers(defn, registry)
    findings: list[dict] = []
    for n in _nodes(defn):
        if n.get("type") not in _GATEWAY_TYPES:
            continue
        expr = _branch_expression(n)
        if not expr:
            continue
        for var in sorted(referenced_vars(expr) - prod):
            findings.append({
                "type": "unproduced_gateway_var",
                "node": n.get("id"),
                "variable": var,
                "expression": expr,
            })
    return findings
