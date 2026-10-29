"""A converted frame's markup as a tree of numbered elements.

`tsx` writes one element per line — an opening tag, a closing tag, a text
with its words, an image, a shared component in its sizing box — so its
output reads back exactly. `params` numbers every element for the model,
which says which numbered element is which prop; the view is then this tree
written out again with those bindings, so the drawing cannot change.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field


@dataclass
class Node:
    tag: str
    #: ``(name, value)`` with the value as written: ``"…"`` or ``{…}``.
    attrs: list[tuple[str, str]] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)
    #: The words between the tags of a text (or `{props.children}`), as written.
    body: str | None = None
    id: str = ""
    parent: "Node | None" = field(default=None, repr=False, compare=False)

    @property
    def is_component(self) -> bool:
        return self.tag[:1].isupper()

    def attr(self, name: str) -> str | None:
        return next((v for k, v in self.attrs if k == name), None)

    def classes(self) -> str:
        v = self.attr("className") or ""
        return v[1:-1] if v.startswith('"') else v

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def unit(self) -> "Node":
        """A sizing box around one shared component is that component."""
        if self.tag == "div" and len(self.children) == 1 and self.children[0].is_component and self.body is None:
            return self.children[0]
        return self


def _value(s: str, i: int) -> int:
    """The end of an attribute value starting at ``s[i]``."""
    if s[i] == '"':
        j = i + 1
        while j < len(s) and s[j] != '"':
            j += 2 if s[j] == "\\" else 1
        return j + 1
    depth, j, quote = 0, i, ""
    while j < len(s):
        ch = s[j]
        if quote:
            if ch == "\\":
                j += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError(f"unclosed attribute value: {s[i:i + 40]}")


def _open_tag(s: str) -> tuple[str, list[tuple[str, str]], bool, str]:
    """``<tag a="…" b={…}`` → tag, attrs, self-closing, what follows the tag."""
    m = re.match(r"<([A-Za-z][A-Za-z0-9]*)", s)
    if not m:
        raise ValueError(f"not a tag: {s[:40]}")
    tag, i, attrs = m.group(1), m.end(), []
    while True:
        while i < len(s) and s[i] == " ":
            i += 1
        if s.startswith("/>", i):
            return tag, attrs, True, s[i + 2:]
        if s.startswith(">", i):
            return tag, attrs, False, s[i + 1:]
        n = re.match(r"[A-Za-z_][A-Za-z0-9_-]*", s[i:])
        if not n or s[i + n.end():i + n.end() + 1] != "=":
            raise ValueError(f"unreadable attribute in: {s[:80]}")
        name, i = n.group(0), i + n.end() + 1
        end = _value(s, i)
        attrs.append((name, s[i:end]))
        i = end


def _element(line: str) -> tuple[Node, bool]:
    """One line as a node, and whether it stays open for the lines after."""
    tag, attrs, closed, rest = _open_tag(line)
    node = Node(tag=tag, attrs=attrs)
    if closed:
        return node, False
    if not rest:
        return node, True
    close = f"</{tag}>"
    if not rest.endswith(close):
        raise ValueError(f"a line that is not one element: {line[:80]}")
    inner = rest[:-len(close)]
    if tag == "div" and re.match(r"<[A-Z]", inner):
        child, _open = _element(inner)
        child.parent = node
        node.children.append(child)
    else:
        node.body = inner
    return node, False


def parse(static: str) -> Node:
    """The root element of a frame's markup (`tsx.Emitter.frame`, `shell.shell_markup`)."""
    lines = static.split("\n")
    start = next(i for i, l in enumerate(lines) if l.strip() == "return (") + 1
    stack: list[Node] = []
    root: Node | None = None
    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            continue
        if line == ");":
            break
        if line.startswith("</"):
            stack.pop()
            continue
        node, open_ = _element(line)
        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        elif root is None:
            root = node
        else:
            raise ValueError("the markup has more than one root")
        if open_:
            stack.append(node)
    if root is None:
        raise ValueError("no markup")
    n = 0
    for node in root.walk():
        if node.parent is not None and node.parent.unit() is node:
            node.id = node.parent.id + "c"
        else:
            n += 1
            node.id = str(n)
    return root


def index(root: Node) -> dict[str, Node]:
    return {n.id: n for n in root.walk()}


def plain(node: Node) -> str:
    """The words a text or component shows, as drawn."""
    node = node.unit()
    if node.is_component:
        for _k, v in node.attrs:
            if v.startswith("{\"") and v.endswith("\"}"):
                try:
                    return str(json.loads(v[1:-1]))
                except json.JSONDecodeError:
                    pass
        return ""
    if node.tag == "img":
        v = node.attr("src") or ""
        return v[1:-1] if v.startswith('"') else v
    if node.body is None:
        return " ".join(w for w in (plain(c) for c in node.children) if w)
    text = re.sub(r"<br\s*/>", "\n", node.body)
    text = re.sub(r"<[^>]+>", "", text)
    for k, v in (("&#123;", "{"), ("&#125;", "}"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(k, v)
    return text


def prop_value(node: Node, prop: str) -> str:
    raw = node.unit().attr(prop) or ""
    if raw.startswith("{\"") and raw.endswith("\"}"):
        try:
            return str(json.loads(raw[1:-1]))
        except json.JSONDecodeError:
            return ""
    return raw.strip('"')


def look(node: Node) -> tuple:
    """What a node looks like, without its words: its pictures are part of it."""
    return (node.tag, node.attr("className"), node.attr("style"), node.attr("src") if node.tag == "img" else None,
            tuple(look(c) for c in node.children))


def counterpart(root: Node, other: Node, node: Node) -> Node | None:
    """The node of ``other`` at the place ``node`` has in ``root``."""
    path = []
    at = node
    while at is not root:
        if at.parent is None:
            return None
        path.append(at.parent.children.index(at))
        at = at.parent
    out = other
    for i in reversed(path):
        if i >= len(out.children):
            return None
        out = out.children[i]
    return out


def relook(content: Node, look_of: Node, valued: set[str], *, own_pictures: bool = False) -> Node:
    """``content`` in ``look_of``'s look: where ``look_of`` draws an element
    of the same kind at the same place, ``content``'s element with
    ``look_of``'s classes, style and component; an element only ``look_of``
    draws is drawn as it is there; one only ``content`` draws is left out.
    Elements are paired in order by kind, so a selected tab drawn with a tick
    before its label still pairs label with label.

    THE WORDS ARE THE ELEMENT'S OWN. "Pro" drawn unselected beside "Premium"
    selected is still "Pro" when selected; taken with the look, every option
    of a group read as the one it was given the look of (Pro, Pro, Pro;
    DITANS A-12, 2026-10-29). A picture is the look's — a rule's tick or
    cross is its look — unless its src is a value (``valued``), or
    ``own_pictures`` (an option's icon is the option's).

    THE SAME ROW, NOT THE SAME ELEMENTS. An expired promo code is drawn with
    an Extend button beside its pill; refused as no look of the active row,
    the screen failed three rounds (DITANS A-11, 2026-10-29)."""
    out = _relook(content, look_of, valued, own_pictures)
    # It stands where ``content`` stands, whichever element it is drawn from.
    out.id, out.parent = content.id, content.parent
    return out


def same_kind(a: Node, b: Node) -> bool:
    return a.is_component == b.is_component and (a.is_component or a.tag == b.tag) \
        and (a.body is None) == (b.body is None) and (a.unit() is a) == (b.unit() is b)


def _relook(content: Node, look_of: Node, valued: set[str], own_pictures: bool) -> Node:
    if content is not look_of and same_kind(content, look_of):
        out = copy.copy(content)
        taken = {"className", "style"}
        if content.tag == "img" and content.id not in valued and not own_pictures:
            taken.add("src")
        if look_of.is_component and look_of.tag != content.tag:
            # ANOTHER COMPONENT TAKES ITS OWN PROPS: the look's, with this
            # element's words where the two name the same one. A selected tab
            # drawn as a component with a tick lost the tick prop and did not
            # type-check (DITANS A-PB1, 2026-10-29).
            mine = dict(content.attrs)
            out.attrs = [(k, mine.get(k, v)) for k, v in look_of.attrs]
            out.tag = look_of.tag
        else:
            attrs = dict(content.attrs)
            for k, v in look_of.attrs:
                if k in taken:
                    attrs[k] = v
            out.attrs = list(attrs.items())
        kids, at = [], 0
        for c in look_of.children:
            k = next((i for i in range(at, len(content.children)) if same_kind(content.children[i], c)), None)
            if k is None:
                kids.append(_relook(c, c, valued, own_pictures))
            else:
                kids.append(_relook(content.children[k], c, valued, own_pictures))
                at = k + 1
    else:
        out = copy.copy(look_of)
        kids = [_relook(c, c, valued, own_pictures) for c in look_of.children]
    out.children = kids
    for c in out.children:
        c.parent = out
    return out


def numbered(root: Node) -> str:
    """The markup as the model is shown it: each element's number before it."""
    out: list[str] = []

    def write(node: Node, depth: int) -> None:
        pad = " " * depth
        attrs = "".join(f" {k}={v}" for k, v in node.attrs)
        head = f"{node.id}|{pad}<{node.tag}{attrs}"
        unit = node.unit()
        if unit is not node:
            u_attrs = "".join(f" {k}={v}" for k, v in unit.attrs)
            out.append(f"{head}><{unit.tag}{u_attrs} /></{node.tag}>")
        elif node.body is not None:
            out.append(f"{head}>{node.body}</{node.tag}>")
        elif not node.children:
            out.append(f"{head} />")
        else:
            out.append(head + ">")
            for c in node.children:
                write(c, depth + 1)
            out.append(f"{' ' * len(node.id)}|{pad}</{node.tag}>")

    write(root, 0)
    return "\n".join(out)
