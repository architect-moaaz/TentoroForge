"""The components a design repeats, as one React component each.

A Figma component used across the screens — a status tag, a button, a table
row — is drawn the same each time but for its words. Converted inline it is
the same markup forty times; here each such component becomes one React
component whose words are its props, and every use is `<DhTag label="Live" />`.

Only what is provably the same is shared: an instance joins its component
when its markup, with its words taken out, is exactly the others'. A variant
painted another colour, or an instance with an override, stays inline — a
shared component that draws some of its uses wrong would be worse than none.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from services.drawn.tsx import Emitter, _box, _px, _walk, is_vector_only

#: A component is shared when at least this many of its uses are alike.
MIN_USES = 3
#: How a component's file is written. A build writes the files again when it
#: changes (`orchestrator._drawn_present`): they come from the drawing with no
#: model, and a file written before its words could be typed into kept an app's
#: forms read-only (DITANS, 2026-10-30).
FORMAT = 2


def _texts(node: dict) -> list[dict]:
    return [n for n in _walk(node) if str(n.get("type") or "") == "TEXT"]


def _prop_keys(texts: list[dict]) -> list[str]:
    keys: list[str] = []
    for i, text in enumerate(texts):
        words = re.findall(r"[A-Za-z0-9]+", str(text.get("name") or ""))
        key = (words[0].lower() + "".join(w[:1].upper() + w[1:] for w in words[1:])) if words else ""
        if not key or key[0].isdigit() or len(key) > 24:
            key = f"text{i + 1}"
        while key in keys:
            key = f"{key}{i + 1}"
        keys.append(key)
    return keys


def _name(instance_name: str, taken: set[str]) -> str:
    words = re.findall(r"[A-Za-z0-9]+", instance_name)
    base = "".join(w[:1].upper() + w[1:].lower() if w.isupper() and len(w) <= 3 else w[:1].upper() + w[1:]
                   for w in words)[:40] or "Part"
    if base[0].isdigit():
        base = "Part" + base
    name, n = base, 2
    while name in taken:
        name, n = f"{base}{n}", n + 1
    taken.add(name)
    return name


@dataclass
class Shared:
    name: str
    keys: list[str]
    template: str
    uses: int = 0


@dataclass
class Library:
    """The shared components of a set of frames, and how a use is written."""
    shared: dict[str, Shared] = field(default_factory=dict)       # template -> Shared

    @staticmethod
    def _template(node: dict, emitter: Emitter) -> tuple[str, list[str]]:
        """``node`` drawn as a component's own markup, its words as props."""
        texts = _texts(node)
        keys = _prop_keys(texts)
        by_id = {str(t.get("id")): k for t, k in zip(texts, keys)}
        inner = Emitter(assets=emitter.assets, skip=emitter.skip, trace=False,
                        text_slot=lambda t: by_id.get(str(t.get("id"))))
        body = inner.element(node, None, 2, own_size=True)
        return body, keys

    @classmethod
    def build(cls, documents: Iterable[dict], emitter: Emitter) -> "Library":
        lib = cls()
        candidates: dict[str, list[dict]] = {}
        for document in documents:
            for node in _walk(document):
                if str(node.get("type") or "") == "INSTANCE" and node.get("componentId") \
                        and str(node.get("id")) not in emitter.skip and not is_vector_only(node) and _texts(node):
                    candidates.setdefault(str(node["componentId"]), []).append(node)
        taken: set[str] = set()
        for uses in candidates.values():
            if len(uses) < MIN_USES:
                continue
            groups: dict[str, list] = {}
            for node in uses:
                template, keys = cls._template(node, emitter)
                groups.setdefault(template, []).append((node, keys))
            for template, members in groups.items():
                if len(members) >= MIN_USES:
                    node, keys = members[0]
                    # Named by the component and the variant it is: DhButtonPrimaryLarge,
                    # not DhButton7.
                    variant = " ".join(str(v.get("value")) for v in (node.get("componentProperties") or {}).values()
                                       if isinstance(v, dict) and v.get("type") == "VARIANT")
                    lib.shared[template] = Shared(name=_name(f"{node.get('name') or ''} {variant}", taken),
                                                  keys=keys, template=template, uses=len(members))
        return lib

    def use(self, node: dict, emitter: Emitter) -> str | None:
        """``<Name key="words" />`` for an instance of a shared component, else None."""
        if not self.shared or not node.get("componentId"):
            return None
        template, keys = self._template(node, emitter)
        shared = self.shared.get(template)
        if shared is None:
            return None
        props = " ".join(f"{k}={{{json.dumps(str(t.get('characters') or ''))}}}"
                         for k, t in zip(keys, _texts(node)))
        return f"<{shared.name} {props} />"

    def files(self) -> dict[str, str]:
        """``{Name: component file}`` for every shared component.

        EACH WORD CAN BE TYPED INTO. A design system's text field is a
        component whose words are its label, its value and its help; a screen
        that uses it as an input gives the value word an ``<word>Input`` and the
        component draws an input in that word's own place and look (its font and
        colour are inherited from the drawn text)."""
        out = {}
        for shared in self.shared.values():
            props = "; ".join(f"{k}: React.ReactNode; {k}Input?: FieldInput" for k in shared.keys)
            template = shared.template
            for k in shared.keys:
                template = template.replace("{props." + k + "}", "{" + _typed(k) + "}")
            out[shared.name] = (
                FIELD_INPUT
                + f"export default function {shared.name}(props: {{ {props} }}) {{\n"
                f"  return (\n{template}  );\n}}\n")
        return out


#: What a screen hands a component's word to make it an input.
FIELD_INPUT = ("type FieldInput = { value: string; onChange(value: string): void; placeholder?: string; "
               "options?: string[] };\n\n")
_FIELD_CLASSES = "w-full min-w-0 bg-transparent outline-none border-0 p-0 m-0 appearance-none"


def _typed(key: str) -> str:
    """The word, or the input a screen made of it."""
    field = f"props.{key}Input"
    return (f"{field} ? ({field}.options ? <select className=\"{_FIELD_CLASSES}\" value={{{field}.value}} "
            f"onChange={{(e) => {field}!.onChange(e.target.value)}}>{{{field}.options.map((o) => "
            f"<option key={{o}} value={{o}}>{{o}}</option>)}}</select> : <input className=\"{_FIELD_CLASSES}\" "
            f"value={{{field}.value}} placeholder={{{field}.placeholder}} "
            f"onChange={{(e) => {field}!.onChange(e.target.value)}} />) : props.{key}")
