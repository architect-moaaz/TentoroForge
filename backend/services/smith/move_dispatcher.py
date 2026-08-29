"""The move — the one step in a turn that changes the application.

`run_iteration` does not trust this function, and is right not to: it snapshots
git before calling, then asks git what actually changed and fails the turn
unless the diff mentions `element_label` and `target_file` is among the
modified files. So this returns a LABEL for what it intended, never a report of
what it did.

BLUEPRINT FIRST. A rename changes the `pageLayouts` artifact and re-projects;
it does not patch the generated file. §115 makes the Blueprint the source and
the implementation derived, and editing generated files directly is precisely
what makes the legacy pipeline's Blueprint a post-hoc record of whatever the
code happened to become. The verification still passes honestly — the
projection writes `target_file`, so the diff git sees is the real one.

Deterministic, and no model call. `understand_ask` already decided where, what
and what to write; a second model here would be a second opinion about a
question that has already been answered, and a place for the two to disagree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

#: Props that hold text a person can see and therefore name. `label` is a
#: Button's, `content` a Text's or Heading's or Badge's, `title` a Section's.
#: A prop not in this set is not something anyone would call "the Add plant
#: button" — an `href` matching by accident would edit the wrong thing.
_TEXT_PROPS = ("label", "content", "title", "text", "heading", "placeholder")


def _route_matches(route: str, target: str) -> bool:
    """Whether a page's route is what `target_file` was pointing at.

    Understanding returns a route (`/plants`) or a schema path
    (`src/schemas/plants.json`), depending on what the Blueprint slice showed
    it. Both name the same page, and refusing one of them would turn a good
    understanding into a no-op.
    """
    route, target = (route or "").strip(), (target or "").strip()
    if not route or not target:
        return False
    if route == target:
        return True
    # `/plants/[id]` -> `plants/[id]`, which appears in `src/schemas/...`.
    return route.strip("/") and route.strip("/") in target


def _retitle(node: Any, label: str, new_value: str) -> int:
    """Set every visible text prop equal to `label` to `new_value`. Count them.

    Counted rather than stopped at the first, because a label can legitimately
    appear twice — a button in a header and the same button in an empty state —
    and renaming one of them is the bug a user would report next.
    """
    if isinstance(node, list):
        return sum(_retitle(n, label, new_value) for n in node)
    if not isinstance(node, dict):
        return 0

    hits = 0
    props = node.get("props")
    if isinstance(props, dict):
        for key in _TEXT_PROPS:
            if isinstance(props.get(key), str) and props[key].strip() == label:
                props[key] = new_value
                hits += 1
    return hits + _retitle(node.get("children") or [], label, new_value)


def move_dispatcher(
    understanding: dict[str, Any], output_dir: str
) -> Optional[Any]:
    """(understanding, output_dir) -> IterationMove, or None when nothing matched.

    None is a real answer and `run_iteration` treats it as one: it returns
    `no_op` and says the current state already matches. That is the honest
    result when a label cannot be found — better than editing the nearest thing
    and reporting success.
    """
    from services.blueprint.projection import apply_frontend_projection
    from services.blueprint.service import BlueprintService
    from services.smith_session import IterationMove

    label = str(understanding.get("element_label") or "").strip()
    new_value = str(understanding.get("new_value") or "").strip()
    target = str(understanding.get("target_file") or "").strip()

    # A removal is a different move and is not implemented here; without a
    # replacement there is nothing this function knows how to do.
    if not label or not new_value:
        return None

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return None

    pages = {p.get("id"): p for p in (svc.doc.get("pages") or [])
             if isinstance(p, dict)}
    changed: list[str] = []

    for layout in svc.doc.get("pageLayouts") or []:
        if not isinstance(layout, dict):
            continue
        page = pages.get(layout.get("page")) or {}
        # An unmatched target scopes to nothing rather than to everything: a
        # rename that cannot find its page must not rewrite the whole app.
        if target and not _route_matches(str(page.get("route") or ""), target):
            continue
        if _retitle(layout.get("root"), label, new_value):
            svc.upsert("pageLayouts", layout, natural_key=str(layout["page"]))
            changed.append(str(layout["page"]))

    if not changed:
        return None

    svc.save()
    # The projection is what writes `target_file`, which is what git will show
    # and what `run_iteration` verifies against.
    result = apply_frontend_projection(svc, str(Path(output_dir) / "app"))
    touched = [str(f) for f in (result or {}).get("files", [])]

    return IterationMove(
        move_name=f"rename {label!r} to {new_value!r} on {', '.join(changed)}",
        touched_paths=touched,
    )
