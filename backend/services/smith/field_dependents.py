"""EVERYTHING THAT READS A FIELD, not only where it is listed as a field.

Removing Medicine.preferredTime took it out of 6 places (the form box, two
workflow inputs and their insert/update values, one rule) and left 4 reading
it -- three step expressions and one template -- "for Verify & Fix to repair",
so the app stayed broken until another run (UAT Med Tracker, egqkhylj). The
removal looked only where a field is LISTED.

:func:`scan` finds every dependent by reading expressions, templates and the
known identifier slots (tokens, never substrings: ``preferredTimeZone`` is not
``preferredTime``) in workflow steps and inputs, page layouts (bindings,
``visibleIf``, form-field ``interaction``), business rules, widgets and the
seed plan. A reference is ONLY a dependent when it belongs to the removed
entity's field: ``medicine.preferredTime`` does, ``patient.preferredTime`` does
not (the head names a record, resolved through the workflow's record inputs,
the step that loaded it, the page's data source, or the entity's own name).

Each dependent is classified:

* ``retire``  -- exists only for this field (a form box, a column, a value it
  saved, an input, a check of nothing else): safe to take away;
* ``rewrite`` -- the person said what replaces it (``replacement``);
* ``ask``     -- anything else (an expression that also reads other things, a
  template in a sentence, a branch/row that tests it, a screen condition): it
  has to be decided, so it is shown first; on a yes the reading becomes "no
  value" (``null`` / empty text) or the row/branch is removed. A branch
  condition is NEVER rewritten to a constant;
* ``manual``  -- cannot be changed safely from here (code in a script, a
  filter that would be left empty and so match EVERY record): never applied,
  named in the reply as still referring to it.

:func:`apply` carries out everything but ``manual``; the caller scans again
afterwards, so "nothing still refers to it" is computed, not assumed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

_KEYWORDS = frozenset("""and or not true false null if then else in between instance of some every for return
satisfies contains matches""".split())
_EXPR_KEYS = frozenset({"expression", "condition", "when", "formula", "if", "predicate", "filter", "visibleIf",
                        "hiddenIf", "enabledIf", "requiredIf", "disabledIf", "otherwise_when"})
_CODE_KEYS = frozenset({"script", "code", "function", "js", "javascript", "python", "handler"})
#: Keys whose value, when it IS the field's name, is a reference to it.
_IDREF_KEYS = frozenset({"field", "column", "sortBy", "orderBy", "groupBy", "valueField", "labelField", "xKey", "yKey",
                         "valueKey", "labelKey", "x", "y"})
#: Lists whose items are rows/branches of a decision.
_BRANCH_LISTS = frozenset({"rules", "cases", "branches", "conditions", "outcomes", "choices", "rows"})
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
_IDENT = re.compile(r"(?<![A-Za-z0-9_$.])[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\d+)|\[\d+\])*(?![A-Za-z0-9_(])")
_TEMPLATE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_BARE_HEADS = frozenset({"input", "inputs", "trigger", "variables", "vars", "item", "row", "record", "this"})


def _canon(s: Any) -> str:
    c = re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return c[:-1] if len(c) > 3 and c.endswith("s") else c


class Owner:
    """Whose field does a reference name? "ours" / "other" / "unknown"."""

    def __init__(self, doc: dict, entity: dict, *, wf: dict | None = None, layout: dict | None = None,
                 bare_is_ours: bool = True):
        self.doc, self.entity, self.wf, self.layout, self.bare = doc, entity, wf, layout, bare_is_ours
        self.eid = str(entity["id"])
        self.mine = {_canon(entity.get("name")), _canon(entity.get("table"))} - {""}
        ents = [e for e in ((doc.get("data") or {}).get("entities") or []) if isinstance(e, dict)]
        self.others = {_canon(e.get("name")) for e in ents if str(e.get("id")) != self.eid} | \
                      {_canon(e.get("table")) for e in ents if str(e.get("id")) != self.eid}
        self.others -= self.mine | {""}

    def _is_mine(self, ref: Any) -> bool:
        return str(ref) == self.eid or _canon(ref) in self.mine

    def head(self, head: str) -> str:
        h = _canon(head)
        if head in _BARE_HEADS:
            return "ours" if self.bare else "other"
        if self.wf:
            for i in self.wf.get("inputs") or []:
                if isinstance(i, dict) and _canon(i.get("name")) == h:
                    if i.get("kind") == "record":
                        return "ours" if self._is_mine(i.get("entity")) else "other"
            for st in self.wf.get("steps") or []:
                if isinstance(st, dict) and _canon(st.get("key")) == h and st.get("entity"):
                    return "ours" if self._is_mine(st.get("entity")) else "other"
        if self.layout:
            for s in self.layout.get("dataSources") or []:
                if isinstance(s, dict) and _canon(s.get("name")) == h:
                    return "ours" if self._is_mine(s.get("entity")) else "other"
        if h in self.mine:
            return "ours"
        if h in self.others or h == "user":
            return "other"
        return "unknown"

    def token(self, token: str, name: str) -> str | None:
        """None when the token does not read ``name``; else who owns the read."""
        parts = re.sub(r"\[\d+\]", "", token).split(".")
        if name not in parts:
            return None
        idx = parts.index(name)
        if idx == 0:
            return "ours" if self.bare else "other"
        return self.head(parts[0])


def _expr_tokens(expr: str):
    """(token, start, end) for identifier paths outside quoted literals."""
    pos = 0
    for q in _QUOTED.finditer(expr):
        yield from _tokens_in(expr, pos, q.start())
        pos = q.end()
    yield from _tokens_in(expr, pos, len(expr))


def _tokens_in(expr: str, a: int, b: int):
    for m in _IDENT.finditer(expr, a, b):
        if m.group(0).split(".")[0] not in _KEYWORDS:
            yield m.group(0), m.start(), m.end()


def reads(expr: str, name: str, owner: Owner) -> tuple[bool, bool, bool]:
    """(reads our field, reads ONLY our field, has a read we cannot place)."""
    toks = list(_expr_tokens(expr))
    ours = [t for t, *_ in toks if owner.token(t, name) == "ours"]
    unknown = any(owner.token(t, name) == "unknown" for t, *_ in toks)
    return bool(ours), bool(ours) and len(ours) == len(toks), unknown


def refs_in_expression(expr: str, name: str) -> tuple[bool, bool]:
    """Back-compat: reads/only reads, bare names (no owner resolution)."""
    toks = [t for t, *_ in _expr_tokens(expr or "")]
    hit = [t for t in toks if name in t.split(".")]
    return bool(hit), bool(hit) and len(hit) == len(toks)


def _neutral_expr(expr: str, name: str, owner: Owner, replacement: str | None) -> str:
    out, last = [], 0
    for tok, s, e in _expr_tokens(expr):
        if owner.token(tok, name) != "ours":
            continue
        out.append(expr[last:s])
        parts = tok.split(".")
        out.append(".".join(replacement if p == name else p for p in parts) if replacement else "null")
        last = e
    out.append(expr[last:])
    return "".join(out)


def _neutral_template(text: str, name: str, owner: Owner, replacement: str | None) -> str:
    def sub(m: re.Match) -> str:
        inner = m.group(1)
        if not reads(inner, name, owner)[0]:
            return m.group(0)
        return ("{{" + _neutral_expr(inner, name, owner, replacement) + "}}") if replacement else ""
    return _TEMPLATE.sub(sub, text)


def _dep(cls: str, where: str, what: str, becomes: str, fn: Callable[[], None] | None, *, handled: bool = False,
         detail: str = "") -> dict:
    """``handled``: the removal itself already takes this away (a listed field, a
    column, a saved value, an input); it is shown, not applied twice."""
    return {"class": cls, "where": where, "what": what, "becomes": becomes, "detail": detail,
            "apply": fn or (lambda: None), "handled": handled}


class _Ctx:
    def __init__(self, name: str, replacement: str | None, owner: Owner, where: str, label: Callable[[str], str]):
        self.name, self.replacement, self.owner, self.where, self.label = name, replacement, owner, where, label
        self.step: dict | None = None          # the workflow step being scanned, if any
        self.cfg: dict | None = None
        self.wf: dict | None = None


def _canon_name(s: Any) -> str:
    return _canon(s)


def step_tables(wf: dict) -> set[str]:
    return {_canon(st.get("entity") or (st.get("config") or {}).get("table")) for st in wf.get("steps") or []
            if isinstance(st, dict) and isinstance(st.get("config"), dict)
            and str(st["config"].get("actionType") or "").startswith("db_")} - {""}


def step_is_ours(entity: dict, wf: dict, st: dict, cfg: dict, targets: bool) -> bool:
    """Does this step act on the removed entity? By its own entity id/name, else its
    table; a step that names neither is ours only in a workflow that touches one
    record type. Never by "the workflow targets the entity somewhere"."""
    mine = {_canon(entity.get("name")), _canon(entity.get("table")), _canon(entity.get("id"))} - {""}
    ent = st.get("entity")
    if ent:
        return _canon(ent) in mine
    table = cfg.get("table")
    if table:
        return _canon(table) in mine
    return targets and len(step_tables(wf)) <= 1


def _scan_tree(node: Any, ctx: _Ctx, out: list[dict], parents: list[tuple[Any, Any]] | None = None,
               unit: str = "", skip: frozenset = frozenset()) -> None:
    """Every place in ``node`` that reads the field, by what the place IS.
    ``skip`` names top-level keys left to the caller (the containers scanned
    are the live ones, so a rewrite lands in the real document)."""
    parents = parents or []
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in skip:
                continue
            _scan_leaf(node, k, v, ctx, out, parents)
            if isinstance(v, (dict, list)):
                _scan_tree(v, ctx, out, parents + [(node, k)], unit)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                _scan_leaf(node, i, v, ctx, out, parents)
            elif isinstance(v, (dict, list)):
                _scan_tree(v, ctx, out, parents + [(node, i)], unit)


def _branch_of(parents: list[tuple[Any, Any]]):
    """(list, item) when the leaf sits in a row/branch of a decision."""
    if len(parents) >= 2:
        (cont, key), (item_parent, item_key) = parents[-2], parents[-1]
        if isinstance(item_parent, list) and isinstance(cont, dict) and key in _BRANCH_LISTS:
            return item_parent, item_parent[item_key]
    return None


def _scan_leaf(c: Any, k: Any, v: Any, ctx: _Ctx, out: list[dict], parents: list) -> None:
    name, rep, owner = ctx.name, ctx.replacement, ctx.owner
    key = str(k) if isinstance(k, str) else ""
    if key == "dependsOn" and isinstance(v, list) and name in v:
        out.append(_dep("retire", ctx.where, f"{ctx.where}: another box waits on {name}", "stop waiting on it",
                        lambda v=v: v.__setitem__(slice(None), [x for x in v if x != name])))
        return
    if not isinstance(v, str):
        return
    if key in _IDREF_KEYS and v == name:
        out.append(_dep("ask", ctx.where, f"{ctx.where}: {ctx.label(key)} uses it", "lose that setting",
                        lambda c=c, key=key: c.pop(key, None)))
        return
    if key in _CODE_KEYS:
        if name in {t.split(".")[-1] for t, *_ in _expr_tokens(v)} or any(name in t.split(".") for t, *_ in _expr_tokens(v)):
            out.append(_dep("manual", ctx.where, f"{ctx.where}: code ({key}) reads it", "stay as it is - code is not rewritten from chat",
                            None, detail=v[:120]))
        return
    if key in _EXPR_KEYS:
        mine, pure, unknown = reads(v, name, owner)
        if not mine:
            if unknown and name in v:
                out.append(_dep("manual", ctx.where, f"{ctx.where}: {ctx.label(key)} reads a {name} I cannot place",
                                "stay as it is", None, detail=v[:120]))
            return
        branch = _branch_of(parents)
        step = ctx.step
        if step is not None and c is ctx.cfg and key in ("expression", "condition") and (
                isinstance(c.get("branches"), dict) or len(step.get("next") or []) > 1):
            names = {str(x.get("key")): str(x.get("name") or x.get("key")) for x in (ctx.wf or {}).get("steps") or [] if isinstance(x, dict)}
            ways = " and ".join(f"\"{names.get(str(x), x)}\"" for x in (step.get("next") or []))
            out.append(_dep("manual", ctx.where, f"{ctx.where} decides between {ways or 'two ways'} based on it",
                            "stay as it is - a decision is never made always-true; tell me which way it should go",
                            None, detail=v[:120]))
            return
        new = _neutral_expr(v, name, owner, rep)
        if branch is not None and not rep:
            lst, item = branch
            # A decision row is NEVER dropped (the case would fall through to the next row or the else)
            # and never made always-true: it stays, named, and the person says which way it should go.
            out.append(_dep("manual", ctx.where, f"{ctx.where} decides between its paths based on it (a row tests it)",
                            "stay as it is - a decision row is never dropped or made always-true; tell me which path to keep",
                            None, detail=v[:120]))
            return
        if pure and not rep:
            if key in ("expression", "condition") and not branch:
                out.append(_dep("retire", ctx.where, f"{ctx.where}: a check of nothing but it", "stop checking anything",
                                lambda c=c, k=k: c.__setitem__(k, "true"), detail=v[:120]))
            else:
                out.append(_dep("ask", ctx.where, f"{ctx.where}: {ctx.label(key)} depends only on it", "read as no value",
                                lambda c=c, k=k, new=new: c.__setitem__(k, new), detail=v[:120]))
            return
        out.append(_dep("rewrite" if rep else "ask", ctx.where, f"{ctx.where}: {ctx.label(key)} also uses it",
                        f"read {rep} instead" if rep else "treat it as having no value",
                        lambda c=c, k=k, new=new: c.__setitem__(k, new), detail=v[:120]))
        return
    if "{{" in v and any(reads(m, name, owner)[0] for m in _TEMPLATE.findall(v)):
        new = _neutral_template(v, name, owner, rep)
        out.append(_dep("rewrite" if rep else "ask", ctx.where, f"{ctx.where}: some text uses it", f"read {rep} instead" if rep else "leave that part empty",
                        lambda c=c, k=k, new=new: c.__setitem__(k, new), detail=v[:120]))


def _step_label(wf: dict, st: dict) -> str:
    return f"the step \"{st.get('name') or st.get('key')}\" of \"{wf.get('name') or wf.get('id')}\""


def scan(doc: dict, entity: dict, name: str, *, replacement: str | None = None,
         output_dir: str | Path | None = None) -> list[dict]:
    """Every dependent of ``entity.name``, classified. Each carries an ``apply``
    closure over ``doc``; nothing changes until it is called."""
    from services.smith.field_change import _touches_entity, _walk
    from services.blueprint.functional_completeness import _workflow_targets_entity
    eid, ename = str(entity["id"]), str(entity.get("name") or "")
    out: list[dict] = []

    for wf in [w for w in doc.get("workflows") or [] if isinstance(w, dict) and w.get("status") != "DEPRECATED"]:
        targets = _workflow_targets_entity(doc, wf, eid)
        own_input = any(isinstance(i, dict) and i.get("kind") == "field" and i.get("name") == name for i in wf.get("inputs") or [])
        multi = len(step_tables(wf)) >= 2
        wname = str(wf.get("name") or wf.get("id"))
        for st in wf.get("steps") or []:
            cfg = st.get("config") if isinstance(st, dict) else None
            if not isinstance(cfg, dict):
                continue
            ours_step = step_is_ours(entity, wf, st, cfg, targets)
            # In a workflow over several record types a bare name belongs to THIS step's record.
            owner = Owner(doc, entity, wf=wf, bare_is_ours=(ours_step if multi else (targets or own_input)))
            where = _step_label(wf, st)
            atype = str(cfg.get("actionType") or "")
            vals = cfg.get("values")
            if multi and not ours_step and _bare_reads(cfg, name):
                if st.get("entity") or cfg.get("table"):
                    out.append(_dep("note", wname, f"{where} also reads a bare {name}, but it works on another record",
                                    "be left as it is (it is not this record's field)", None))
                else:      # names no record in a workflow over several: whose {name} it is cannot be told
                    out.append(_dep("manual", wname, f"{where} reads a bare {name} in a workflow over several records",
                                    "stay as it is - I cannot tell whose it is; tell me if it is this record's", None))
            if ours_step and isinstance(vals, dict) and name in vals:
                out.append(_dep("retire", wname, f"{where} saves {name}", "stop saving it",
                                lambda m=vals: m.pop(name, None), handled=True))
            wh = cfg.get("where")
            if ours_step and isinstance(wh, dict) and name in wh:
                rest = [k for k in wh if k != name]
                if rest:
                    out.append(_dep("ask", wname, f"{where} looks records up by {name} as well as {', '.join(rest)}",
                                    "look them up without it", lambda m=wh: m.pop(name, None)))
                else:
                    kind = "change" if atype == "db_update" else "delete" if atype == "db_delete" else "read"
                    out.append(_dep("manual", wname, f"{where} finds its records only by {name}",
                                    f"stay as it is - without it the step would {kind} EVERY record", None))
            skip_cfg = {"values", "where"}
            ctx = _Ctx(name, replacement, owner, where,
                       lambda key, atype=atype: {"expression": "its check", "condition": "its condition", "value": "its value"}.get(key, f"its {key}"))
            ctx.step, ctx.cfg, ctx.wf = st, cfg, wf
            if atype == "set_variable" and isinstance(cfg.get("value"), str):
                mine, pure, _u = reads(cfg["value"], name, owner)
                if mine:
                    new = _neutral_expr(cfg["value"], name, owner, replacement)
                    out.append(_dep("rewrite" if replacement else "ask", wname,
                                    f"{where} works out {cfg.get('variableName')} from it",
                                    f"read {replacement} instead" if replacement else "work it out from nothing",
                                    lambda c=cfg, new=new: c.__setitem__("value", new), detail=cfg["value"][:120]))
                skip_cfg.add("value")
            if isinstance(vals, dict):
                _scan_tree(vals, ctx, out, parents=[(cfg, "values")], skip=frozenset({name}))
            _scan_tree(cfg, ctx, out, skip=frozenset(skip_cfg))
        for i in wf.get("inputs") or []:
            if isinstance(i, dict) and i.get("kind") == "field" and str(i.get("name")) == name and (targets or own_input):
                out.append(_dep("retire", wname, f"\"{wname}\" asks for {name}", "stop asking for it",
                                lambda wf=wf, i=i: wf.__setitem__("inputs", [x for x in wf["inputs"] if x is not i]), handled=True))

    for rule in [r for r in doc.get("businessRules") or [] if isinstance(r, dict) and r.get("status") != "DEPRECATED"
                 and str(r.get("entity") or "") in (eid, ename)]:
        rn = str(rule.get("name"))
        owner = Owner(doc, entity)
        texts = [rule[k] for k in ("when", "expression") if isinstance(rule.get(k), str)]
        acts = [a for a in list(rule.get("then") or []) + list(rule.get("otherwise") or [])
                if isinstance(a, dict) and str(a.get("field") or "") == name]
        rd = [reads(t, name, owner) for t in texts]
        if any(r[0] for r in rd) or acts:
            only = all(r[1] for r in rd if r[0]) and all(r[0] for r in rd) if texts else True
            out.append(_dep("retire" if only else "ask", rn, f"the rule \"{rn}\" checks it", "be retired",
                            lambda r=rule: r.__setitem__("status", "DEPRECATED"),
                            detail="; ".join(t[:80] for t in texts)))

    for layout in [l for l in doc.get("pageLayouts") or [] if isinstance(l, dict) and l.get("status") != "DEPRECATED"]:
        if not _touches_entity(doc, layout, eid, ename):
            continue
        page = next((p for p in doc.get("pages") or [] if isinstance(p, dict) and str(p.get("id")) == str(layout.get("page"))), {})
        where = str(page.get("name") or page.get("route") or layout.get("page"))
        owner = Owner(doc, entity, layout=layout)
        for node in _walk(layout.get("root")):
            props = node.get("props") or {}
            for f in props.get("fields") or []:
                if isinstance(f, dict) and str(f.get("name") or "") == name:
                    out.append(_dep("retire", where, f"the {name} box on {where}", "come off the form",
                                    lambda props=props, f=f: props.__setitem__("fields", [x for x in props["fields"] if x is not f]), handled=True))
            for col in props.get("columns") if isinstance(props.get("columns"), list) else []:
                if isinstance(col, dict) and str(col.get("key") or "") == name:
                    out.append(_dep("retire", where, f"the {name} column on {where}", "come off the table",
                                    lambda props=props, col=col: props.__setitem__("columns", [x for x in props["columns"] if x is not col]), handled=True))
        ctx = _Ctx(name, replacement, owner, f"the \"{where}\" screen", lambda key: f"its {key}")
        _scan_tree(layout, _prune_fields(ctx), out, skip=frozenset(k for k in layout if k not in ("root", "clientState")))
    for w in [w for w in doc.get("widgets") or [] if isinstance(w, dict) and w.get("status") != "DEPRECATED"]:
        src = w.get("dataSource") if isinstance(w.get("dataSource"), dict) else None
        if src and str(src.get("entity") or "") in (eid, ename):
            for key in ("groupBy", "sortBy", "valueField", "labelField", "field"):
                if str(src.get(key) or "") == name:
                    out.append(_dep("ask", str(w.get("label") or w.get("id")), f"the widget \"{w.get('label') or w.get('id')}\" uses it as its {key}",
                                    "lose that setting", lambda src=src, key=key: src.pop(key, None)))
            fields = src.get("fields")
            if isinstance(fields, list) and name in fields:
                out.append(_dep("retire", str(w.get("id")), f"the widget \"{w.get('label') or w.get('id')}\" shows it", "stop showing it",
                                lambda src=src: src.__setitem__("fields", [f for f in src["fields"] if f != name]), handled=True))
    out += _seed_deps(entity, name, output_dir)
    # A decision whose EVERY row would go is left with none: say so.
    by_list: dict[int, list[dict]] = {}
    for d in out:
        if d.get("lst") is not None:
            by_list.setdefault(id(d["lst"]), []).append(d)
    for ds in by_list.values():
        if len(ds) >= len(ds[0]["lst"]):
            for d in ds:
                d["empties"] = True
                d["becomes"] += " - leaving the decision with no rows at all"
    return out


def _bare_reads(cfg: Any, name: str) -> bool:
    """Does anything in ``cfg`` read the BARE name (an expression token, a {{name}})?"""
    def walk(o: Any, key: str = "") -> bool:
        if isinstance(o, dict):
            return any(walk(v, str(k)) for k, v in o.items())
        if isinstance(o, list):
            return any(walk(v, key) for v in o)
        if isinstance(o, str):
            if key in _EXPR_KEYS:
                return any(t == name for t, *_ in _expr_tokens(o))
            return any(any(t == name for t, *_ in _expr_tokens(m)) for m in _TEMPLATE.findall(o))
        return False
    return walk(cfg)


def _prune_fields(ctx: _Ctx) -> _Ctx:
    return ctx


def _seed_deps(entity: dict, name: str, output_dir: str | Path | None) -> list[dict]:
    """The column in the sample rows of ``contracts/seed-plan.json``."""
    if not output_dir:
        return []
    path = Path(output_dir) / "contracts" / "seed-plan.json"
    if not path.is_file():
        return []
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mine = {_canon(entity.get("name")), _canon(entity.get("table"))} - {""}
    tables = [t for t in plan.get("tables") or [] if isinstance(t, dict) and _canon(t.get("name")) in mine]
    bags = [b for k, b in (plan.get("sample_data") or {}).items() if _canon(k) in mine]
    rows = [r for t in tables for r in (t.get("seed_data") or []) if isinstance(r, dict) and name in r] + \
           [r for b in bags for r in b if isinstance(r, dict) and name in r]
    if not rows:
        return []

    def drop() -> None:
        from services.guard_io import dump_like, read_raw, write_atomic
        raw = read_raw(str(path))
        data = json.loads(raw)
        for t in data.get("tables") or []:
            if isinstance(t, dict) and _canon(t.get("name")) in mine:
                for r in t.get("seed_data") or []:
                    if isinstance(r, dict):
                        r.pop(name, None)
        for k, b in (data.get("sample_data") or {}).items():
            if _canon(k) in mine:
                for r in b:
                    if isinstance(r, dict):
                        r.pop(name, None)
        write_atomic(str(path), dump_like(raw, data))
    return [_dep("retire", "sample data", f"the sample records carry a value for {name}", "lose that value", drop)]


def needs_confirmation(deps: list[dict], *, data_exists: bool = False) -> bool:
    """When the person must be asked first: anything not plainly safe (ask or
    manual), or any saved data that would go."""
    return data_exists or any(d["class"] in ("ask", "manual", "note") for d in deps)


def describe(deps: list[dict]) -> list[str]:
    """One everyday-words line per dependent: what it is and what it becomes;
    the raw expression only as a secondary detail."""
    lines = []
    for d in deps:
        s = f"{d['what']} - it would {d['becomes']}"
        if d.get("detail"):
            s += f" (written as: {d['detail']})"
        lines.append(s)
    return lines


def apply(deps: list[dict]) -> int:
    """Carry out what the removal does not already do itself (never ``manual``)."""
    todo = [d for d in deps if not d.get("handled") and d["class"] not in ("manual", "note")]
    for d in todo:
        d["apply"]()
    return len(todo)


def references_left(doc: dict, entity: dict, name: str, *, output_dir: str | Path | None = None) -> list[str]:
    """What still reads the field afterwards (a fresh scan, in words)."""
    return [d["what"] for d in scan(doc, entity, name, output_dir=output_dir) if d["class"] != "note"]


__all__ = ["scan", "apply", "describe", "needs_confirmation", "references_left", "refs_in_expression", "reads", "Owner"]
