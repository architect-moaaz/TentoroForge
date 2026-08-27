"""CTX-2: pre-ground Smith with entity matches for the user's turn.

The problem this cures — the user types "the Recruitment Drive status
dropdown is broken." Smith has the app-map in his system prompt but no
deterministic step that says "extract proper nouns → look up in registry
→ prepend matches." He guesses per-turn; guess quality varies.

``extract_grounding_hints(message, output_dir)`` does that step
deterministically before Smith's loop starts:

  1. Extract capitalized / multi-word noun phrases from the message.
  2. For each candidate, run :func:`services.smith_find_resources.find_resources`.
  3. Return a formatted block naming every match + one-line summary.

The block gets prepended to Smith's memory so he knows on turn 0
"this ask is about X, which has these pages and these dependents."

Silent when nothing matches — no noise added to prompts on ambiguous
turns.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Words we never treat as entity references — English function words +
# the app's own jargon so "Recruitment Drive" matches but "The App" doesn't.
_STOPWORDS: set[str] = {
    "the", "a", "an", "this", "that", "these", "those",
    "my", "your", "our", "their",
    "and", "or", "but", "so", "with", "for", "in", "on", "at", "to", "of",
    "is", "are", "was", "were", "be", "been", "being",
    "can", "could", "should", "would", "will", "may", "might",
    "please", "help", "fix", "make", "add", "remove", "delete", "update",
    "change", "show", "hide", "display", "click", "clicked", "clicking",
    "app", "page", "screen", "form", "button", "component",
    "smith", "chat", "message", "issue", "bug", "problem", "error",
    "it", "its", "they", "them", "he", "she", "we", "us",
    "not", "no", "yes",
}

# Matches capitalised words (PascalCase or Title Case) that could be an entity.
# Also matches all-lowercase multi-word phrases like "recruitment drive" when
# they contain a domain-y word (heuristic: length ≥ 2 tokens, all alpha).
_CAPITALISED_PHRASE = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9]*)(?:\s+(?:[A-Z][a-zA-Z0-9]*|of|the|and))*\b"
)
_LOWERCASE_PHRASE = re.compile(r"\b([a-z]{3,})\s+([a-z]{3,})\b")


def extract_grounding_hints(
    message: str, output_dir: str, *, max_matches: int = 4,
) -> str:
    """Return a compact block naming every entity the user's message
    likely refers to, or ``""`` when nothing matched.

    Runs :func:`services.smith_find_resources.find_resources` on each
    extracted candidate phrase and dedupes by matched entity. Silent on
    any error — grounding is best-effort context enrichment, never a
    blocker on Smith's turn."""
    if not isinstance(message, str) or not message.strip() or not output_dir:
        return ""

    try:
        from services.smith_find_resources import find_resources
    except Exception:  # noqa: BLE001
        logger.exception("[grounding] find_resources import failed")
        return ""

    # Regular candidates (Capitalised phrases, entity-name matches),
    # PLUS layman-vocabulary aliases derived from plan.pages[].name and
    # route stems. The alias pass catches "the intake form has a bug"
    # → entity=CandidateProfile via page name "CandidateApplyWizardPage".
    candidates = _extract_candidates(message)
    candidates.extend(
        c for c in _extract_layman_candidates(message, output_dir)
        if c not in candidates
    )
    if not candidates:
        return ""

    seen_entities: set[str] = set()
    lines: list[str] = []
    for cand in candidates:
        if len(lines) >= max_matches:
            break
        try:
            r = find_resources(output_dir, cand)
        except Exception:  # noqa: BLE001
            logger.exception("[grounding] find_resources errored for %r", cand)
            continue
        ent = r.get("matched_entity") if isinstance(r, dict) else None
        if not ent or ent in seen_entities:
            continue
        seen_entities.add(ent)
        hint = r.get("hint") or ent
        conf = r.get("confidence") or "match"
        lines.append(f"  - `{cand}` → **{ent}** ({conf}): {hint}")

    if not lines:
        return ""

    header = (
        "## Grounding\n"
        "The user's message likely refers to the following resource(s). "
        "Use `find_resources(query)` for the full graph, or read the "
        "referenced schemas directly:\n"
    )
    return header + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Candidate extraction
# --------------------------------------------------------------------------- #

def _extract_layman_candidates(message: str, output_dir: str) -> list[str]:
    """Layman-vocabulary bridge: pull entity aliases the plain
    :func:`_extract_candidates` regex would miss.

    Builds a token → entity map from ``plan.pages[].name`` + route
    stems, then scans the user's message for those tokens. When a token
    hits, returns the target entity's name as a synthetic candidate that
    :func:`find_resources` can resolve.

    Example: with ``pages=[{route:"/apply", name:"CandidateApplyWizardPage",
    entity:"CandidateProfile"}]`` the alias map is ``{apply, wizard,
    candidate → CandidateProfile}``. The layman ask *"the intake form
    is broken"* still misses (no shared token) — but *"the apply
    wizard is missing a field"* now surfaces CandidateProfile.
    """
    if not isinstance(message, str) or not message.strip() or not output_dir:
        return []
    alias_map = _build_layman_alias_index(output_dir)
    if not alias_map:
        return []
    message_lower = " " + message.lower() + " "
    hit_entities: list[str] = []
    seen: set[str] = set()
    for token, entities in alias_map.items():
        # Word-boundary match — avoid "apply" matching "applications".
        if f" {token} " in message_lower or f" {token}." in message_lower or \
           f" {token}," in message_lower or f" {token}'" in message_lower:
            for ent in entities:
                if ent not in seen:
                    seen.add(ent)
                    hit_entities.append(ent)
    return hit_entities


_LAYMAN_ALIAS_STOPWORDS = {
    "page", "screen", "view", "form", "component", "wizard", "detail",
    "list", "create", "new", "edit", "update", "the", "and", "or",
    "with", "from", "to", "of", "in", "on", "at", "for",
}


def _build_layman_alias_index(output_dir: str) -> dict[str, list[str]]:
    """Read ``src/contracts/plan.json`` and return
    ``{token → [entity names]}`` derived from every page's name and
    route. Tokens are lowercased, ≥4 chars, stopwords excluded.

    Cached-per-call (cheap enough to re-read; plan is small)."""
    try:
        from pathlib import Path
        import json
        plan_path = Path(output_dir) / "src" / "contracts" / "plan.json"
        if not plan_path.is_file():
            return {}
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return {}
    idx: dict[str, list[str]] = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        entity = p.get("entity")
        if not isinstance(entity, str) or not entity:
            continue
        tokens: set[str] = set()
        # PascalCase name split.
        name = p.get("name")
        if isinstance(name, str):
            for t in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", name):
                tl = t.lower()
                if len(tl) >= 4 and tl not in _LAYMAN_ALIAS_STOPWORDS:
                    tokens.add(tl)
        # Route stem — each segment except dynamic ones.
        route = p.get("route")
        if isinstance(route, str):
            for seg in route.split("/"):
                seg_clean = re.sub(r"[\[\]:]", "", seg).lower()
                if len(seg_clean) >= 4 and seg_clean not in _LAYMAN_ALIAS_STOPWORDS:
                    tokens.add(seg_clean)
        # Also index the entity's own name tokens so a lowercase mention
        # of the entity noun ("candidate") still hits ("CandidateProfile"
        # → candidate, profile). _extract_candidates does capitalised
        # matches; this covers the all-lowercase turn.
        for t in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", entity):
            tl = t.lower()
            if len(tl) >= 4 and tl not in _LAYMAN_ALIAS_STOPWORDS:
                tokens.add(tl)
        for tok in tokens:
            bucket = idx.setdefault(tok, [])
            if entity not in bucket:
                bucket.append(entity)
    return idx


def _extract_candidates(message: str) -> list[str]:
    """Pull noun-phrase candidates from ``message`` for grounding lookup.

    Yields in priority order: multi-word Capitalised phrases (highest
    signal), single Capitalised words, then multi-word lowercase phrases
    (least reliable, only if no Capitalised match was already tried).
    Stopwords filtered."""
    out: list[str] = []
    seen: set[str] = set()

    def _push(s: str) -> None:
        cleaned = _strip_leading_stopwords(s.strip())
        if not cleaned:
            return
        if any(t in _STOPWORDS for t in cleaned.split()) and " " not in cleaned:
            return
        key = cleaned.lower()
        if key in seen or key in _STOPWORDS:
            return
        seen.add(key)
        out.append(cleaned)

    # (1) Capitalised phrases first — "Recruitment Drive", "PascalName".
    for m in _CAPITALISED_PHRASE.finditer(message):
        phrase = m.group(0).strip()
        if len(phrase) < 3:
            continue
        _push(phrase)

    # (2) Lowercase two-word phrases as backup.
    for m in _LOWERCASE_PHRASE.finditer(message):
        w1, w2 = m.group(1), m.group(2)
        if w1 in _STOPWORDS or w2 in _STOPWORDS:
            continue
        _push(f"{w1} {w2}")

    return out


# --------------------------------------------------------------------------- #
# Nav / menu intent — SMITH-NAV                                                #
# --------------------------------------------------------------------------- #
# The layer-1 scope-check used to enumerate every page an entity owned when
# the user said something like "recruiters menu is showing users page". 12
# pages is not a scope narrowing — it's a punt. The user pointed at a
# specific artifact (the sidebar), and there is ONE clear place to look
# (shell.json / nav-flow.json). Two helpers below detect that class of ask
# and route to a targeted 2-option question instead.


# Menu / sidebar / navigation vocabulary. Match on substring for slightly
# tolerant handling of "SideNav" vs "side nav" etc.
_NAV_NOUNS = (
    "menu", "sidebar", "side nav", "side-nav", "sidenav",
    "navigation", "nav bar", "nav-bar", "navbar",
    "left nav", "left-nav", "leftnav",
)


def _looks_like_nav_intent(message: str) -> bool:
    """True when the user is talking about the sidebar / menu / navigation.

    A layman phrasing "clicking Recruiters shows Users" is intentionally
    NOT flagged here — that's ambiguous (could be nav or page). Only
    explicit nav-noun mentions fire, so a false positive is impossible.
    False negatives are fine — they fall back to Smith's LLM which now
    has an explicit nav row in its artifact-routing table.
    """
    if not isinstance(message, str):
        return False
    m = message.lower()
    return any(noun in m for noun in _NAV_NOUNS)


def _is_question(message: str) -> bool:
    """True when ``message`` reads as a question rather than an instruction.

    Deliberately narrow: an explicit question mark, and nothing else.

    An interrogative OPENER is not enough. "Why recruiters menu is showing
    users page" opens with "why" but is a user reporting a fault and asking
    for it to be fixed — the deterministic nav fix exists precisely to serve
    that phrasing, and ``test_smith_nav_scope`` pins it. Treating every
    "why…" as a question would disable the feature for its main use.

    The register's own SX-2 repro — "why does the Expenses menu go to the
    wrong page?" — ends in "?" and IS caught here.

    WHERE THE LINE SITS IS A PRODUCT CALL: an interrogative opener with no
    question mark is genuinely ambiguous, and this treats it as a fix
    request. Flagged for QA in the batch-23 handoff.
    """
    return isinstance(message, str) and message.strip().endswith("?")


def _load_shell_menu_items(output_dir: str) -> list[dict]:
    """Return the flat list of {label, route, group} items from shell.json.

    The shell schema nests items under SideNav.props.groups[].items[].
    Returns [] on any error — the caller falls back to a generic message.
    """
    if not output_dir:
        return []
    try:
        import json
        from pathlib import Path
        p = Path(output_dir) / "src" / "schemas" / "shell.json"
        if not p.is_file():
            return []
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    def _walk(node: Any, out: list[dict]) -> None:
        if isinstance(node, dict):
            # Match a SideNav component's props.groups shape.
            if node.get("type") == "SideNav":
                for group in (node.get("props") or {}).get("groups") or []:
                    if not isinstance(group, dict):
                        continue
                    group_label = str(group.get("label") or "")
                    for item in group.get("items") or []:
                        if not isinstance(item, dict):
                            continue
                        label = item.get("label")
                        route = item.get("route")
                        if isinstance(label, str) and isinstance(route, str):
                            out.append({
                                "label": label,
                                "route": route,
                                "group": group_label,
                            })
                return  # SideNav found — no need to recurse further.
            for v in node.values():
                _walk(v, out)
        elif isinstance(node, list):
            for v in node:
                _walk(v, out)

    items: list[dict] = []
    _walk(data, items)
    return items


def _match_menu_item(message: str, items: list[dict]) -> dict | None:
    """Find the menu item the user's message most likely refers to.

    Priority: exact whole-word match on label, then substring match on
    label, then substring match on route. Case-insensitive. Returns the
    matched item dict or None.
    """
    if not items or not isinstance(message, str):
        return None
    tokens = set(re.findall(r"[a-z]+", message.lower()))

    # Exact whole-word match on any word in the label.
    #
    # This used to `return item` on the FIRST hit in shell.json order with no
    # ambiguity check (register SX-2), so "Expense Reports" vs "Expense
    # Claims" resolved on file order — and the caller then REWROTE and
    # COMMITTED shell.json. Collect every hit and refuse when more than one
    # menu item is a plausible referent: the same "ambiguous target means
    # ask, never guess" rule the workflow resolver follows (S20-1).
    # SCORE by how much of the label the message actually names, then take a
    # STRICT winner. A bare hit count cannot separate "Expense Reports" from
    # "Expense Claims" when the user says "expense claims": the shared word
    # makes both items hit, so an all-or-nothing rule refuses every menu whose
    # labels share a word — which is most of them. The pre-pass then never
    # fires, and a guard that always abstains is indistinguishable from one
    # that was never wired.
    #
    # Scoring the OVERLAP fixes that without weakening the ambiguity rule:
    # naming both words of a two-word label beats naming one, so the fully
    # specified referent wins outright. A genuine tie still refuses (SX-2) —
    # the "ambiguous target means ask, never guess" rule S20-1 follows.
    def _score(item: dict) -> int:
        words = {w for w in re.findall(r"[a-z]+", str(item.get("label") or "").lower())
                 if len(w) >= 4}
        return len(words & tokens)

    scored = [(item, _score(item)) for item in items]
    best = max((s for _, s in scored), default=0)
    if best > 0:
        top = [item for item, s in scored if s == best]
        if len(top) == 1:
            return top[0]
        logger.info(
            "smith_grounding: %r matches %d menu items equally well (%s) — refusing "
            "to guess which one the user meant; Smith's LLM loop will ask.",
            message[:80], len(top),
            ", ".join(str(h.get("label")) for h in top),
        )
        return None

    # Substring match on route (e.g. "/recruiters" mentioned in message).
    m_lower = message.lower()
    route_hits = [
        item for item in items
        if len(str(item.get("route") or "").lower().rstrip("/")) > 1
        and str(item.get("route") or "").lower().rstrip("/") in m_lower
    ]
    if len(route_hits) == 1:
        return route_hits[0]
    if len(route_hits) > 1:
        logger.info(
            "smith_grounding: %r matches %d menu routes — refusing to guess.",
            message[:80], len(route_hits),
        )
    return None


def _label_stems(label: str) -> list[str]:
    """Return the naïve singular + plural / lowered forms of a menu label,
    used to match against candidate route paths. "Recruiters" → recruiter,
    recruiters. Handles trailing s / es only — deliberately narrow so we
    don't invent stems and mispair unrelated pages."""
    if not isinstance(label, str):
        return []
    words = [w for w in re.split(r"[^A-Za-z]+", label) if w]
    if not words:
        return []
    tail = words[-1].lower()
    stems = {tail}
    if tail.endswith("ies"):
        stems.add(tail[:-3] + "y")
    if tail.endswith("es") and len(tail) > 3:
        stems.add(tail[:-2])
    if tail.endswith("s") and len(tail) > 2:
        stems.add(tail[:-1])
    # Also add the plural form of any singular so `/user` matches
    # `Users` and vice versa.
    if not tail.endswith("s"):
        stems.add(tail + "s")
    return sorted(stems, key=len, reverse=True)


def _route_base(route: str) -> str:
    """Strip leading /, trailing /, dynamic segments, and depth. Just the
    top-level slug so we can compare cheaply. `/recruiters/[id]/edit` →
    `recruiters`."""
    if not isinstance(route, str):
        return ""
    r = route.strip("/")
    first = r.split("/", 1)[0]
    return re.sub(r"[^A-Za-z]", "", first).lower()


def try_fix_menu_route_mismatch(
    message: str, output_dir: str,
) -> dict | None:
    """Deterministic Smith fix for the "menu label points at the wrong
    page" class of ask.

    Fires only when ALL of these hold:
      • message expresses nav-intent (_looks_like_nav_intent)
      • shell.json has a SideNav we can parse
      • the message references exactly one menu item we can match
      • that item's current route base does NOT contain a stem of the
        item's label (Recruiters → /users, mismatch)
      • the app has a top-level page whose route base MATCHES a stem
        of the label (e.g. `/recruiters` exists)

    When all conditions hold, we rewrite shell.json to swap the item's
    route to the matching page and return a success dict. The caller
    commits + emits a success message. Otherwise returns None — Smith's
    normal loop handles the ambiguous cases.
    """
    if not _looks_like_nav_intent(message):
        return None
    # A QUESTION must never mutate the app (register SX-2). This pass runs
    # before the LLM is invoked and commits shell.json, so "why does the
    # Expenses menu go to the wrong page?" silently rewrote navigation with
    # no confirmation and no turn in which anything could have asked. Asking
    # about a mismatch is not the same as authorising a fix; questions fall
    # through to Smith's normal loop, which can answer or offer the change.
    if _is_question(message):
        logger.info(
            "smith_grounding: %r reads as a QUESTION — not auto-fixing "
            "navigation; Smith's LLM loop will answer it.", message[:80],
        )
        return None
    items = _load_shell_menu_items(output_dir)
    if not items:
        return None
    matched = _match_menu_item(message, items)
    if not matched:
        return None

    label = str(matched.get("label") or "")
    current_route = str(matched.get("route") or "")
    stems = _label_stems(label)
    if not stems:
        return None

    current_base = _route_base(current_route)
    # If the menu already points at a route that echoes its label, there's
    # no mismatch — nothing to fix deterministically.
    if any(stem in current_base for stem in stems):
        return None

    # Look for a candidate page whose top-level route base contains one
    # of the label's stems. We pull the list from nav-flow.json when
    # available (authoritative) and fall back to enumerating menu items.
    candidate_routes: list[str] = []
    try:
        import json as _json
        from pathlib import Path as _Path
        nf = _Path(output_dir) / "src" / "contracts" / "nav-flow.json"
        if nf.is_file():
            data = _json.loads(nf.read_text(encoding="utf-8"))
            for p in data.get("pages") or []:
                if isinstance(p, dict):
                    r = p.get("route")
                    if isinstance(r, str):
                        candidate_routes.append(r)
    except Exception:  # noqa: BLE001
        pass
    for it in items:
        r = it.get("route")
        if isinstance(r, str) and r not in candidate_routes:
            candidate_routes.append(r)

    def _score(route: str) -> int:
        base = _route_base(route)
        for stem in stems:
            if base == stem:
                return 100
            if stem in base:
                return 50
        return 0

    scored = [(r, _score(r)) for r in candidate_routes]
    scored = [t for t in scored if t[1] > 0 and t[0] != current_route]
    # Prefer LIST-shaped routes (no /[id], no /new, no /edit) so the
    # menu lands on the entity index page rather than a detail form.
    def _shape_bonus(route: str) -> int:
        r = route.rstrip("/")
        if r.count("/") == 1 and "[" not in r and "new" not in r and "edit" not in r:
            return 10
        return 0
    scored.sort(key=lambda t: (-(t[1] + _shape_bonus(t[0])), len(t[0])))
    if not scored:
        return None
    target_route = scored[0][0]

    # Apply the swap. Rewrite shell.json in place, preserving formatting.
    try:
        import json as _json
        from pathlib import Path as _Path
        shell_path = _Path(output_dir) / "src" / "schemas" / "shell.json"
        raw = shell_path.read_text(encoding="utf-8")
        data = _json.loads(raw)
    except Exception:  # noqa: BLE001
        return None

    def _rewrite(node: Any) -> bool:
        """Walk the tree; when we find the matched item (same label AND
        route), rewrite its route in place. Returns True on match."""
        if isinstance(node, dict):
            if (
                node.get("label") == label
                and node.get("route") == current_route
            ):
                node["route"] = target_route
                return True
            for v in node.values():
                if _rewrite(v):
                    return True
        elif isinstance(node, list):
            for v in node:
                if _rewrite(v):
                    return True
        return False

    if not _rewrite(data):
        return None
    try:
        shell_path.write_text(
            _json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        return None

    group = matched.get("group") or ""
    group_hint = f" (under **{group}**)" if group else ""
    return {
        "status": "fixed",
        "edited_paths": ["src/schemas/shell.json"],
        "message": (
            f"Fixed. **{label}**{group_hint} in the sidebar now opens "
            f"`{target_route}` (it was pointing at `{current_route}`, "
            f"which is why you saw the wrong page). "
            "Let me know if you'd rather the menu opened somewhere else."
        ),
    }


def render_nav_context_block(output_dir: str) -> str:
    """Compact rendering of the sidebar menu structure for prompt
    injection. Smith sees the menu inline on turn 0 so nav asks don't
    need a Read → parse → reason cycle before he can answer.

    Empty string when shell.json is missing/unparseable — memory block
    stays clean."""
    items = _load_shell_menu_items(output_dir)
    if not items:
        return ""
    # Group items by the group label they belong to.
    from collections import defaultdict
    by_group: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_group[it.get("group") or ""].append(it)
    lines = ["## Sidebar menu (src/schemas/shell.json)"]
    for group_label, group_items in by_group.items():
        header = f"- **{group_label}**" if group_label else "- (ungrouped)"
        lines.append(header)
        for it in group_items:
            label = it.get("label") or "?"
            route = it.get("route") or "?"
            lines.append(f"  - {label} → `{route}`")
    return "\n".join(lines)


def build_deterministic_scope_check(
    message: str, output_dir: str,
) -> str:
    """SMITH-SCOPE-1 (deterministic): when the user's message references
    an entity with multiple primary pages AND doesn't name a specific
    route, return an assistant-message string that ENUMERATES the pages
    and asks the user to pick — before Smith's ReAct loop even starts.

    Returns ``""`` (falsy) when:
      - No entity match (nothing to scope-check)
      - Only one primary page (obvious target — Smith can act)
      - Message already names a specific route (`/candidates/[id]/edit`)
      - Ask is clearly a global entity-level change ("add a field to
        CandidateProfile" — touches schema, not any one page)

    Bypasses model-following entirely — Smith's prompt asks him to
    enumerate but he churns for 60s and punts. This is a deterministic
    fallback: if the model won't scope-check, the router will.
    """
    if not isinstance(message, str) or not message.strip() or not output_dir:
        return ""

    try:
        from services.smith_find_resources import find_resources
    except Exception:  # noqa: BLE001
        return ""

    # Skip if the message already contains a concrete route path — user
    # knows what they mean.
    if re.search(r"/[a-z][\w\-/\[\]]*(?:/(new|edit)|\[id\])", message, re.I):
        return ""

    # Skip if the ask is entity-schema-level (add/remove a column, etc.).
    if re.search(r"\b(?:add|remove|drop|rename)\s+(?:a\s+)?(?:field|column|property)\b",
                 message, re.I):
        return ""

    # SMITH-NAV: menu/sidebar/nav asks target a specific artifact
    # (shell.json / nav-flow.json), NOT one of the entity's many pages.
    # Never enumerate pages for nav-intent asks — the router handles
    # them (deterministic fix + nav-context injection, then LLM). Return
    # empty here so control returns to the router.
    if _looks_like_nav_intent(message):
        return ""

    # Workflow-targeted asks ("in the BarcodeSearchWorkflow, change the
    # notification...") edit a workflow JSON, not one of the entity's
    # pages — enumerating pages here derails the ask into a nonsense
    # page-picker. Any explicit workflow mention bypasses the scope-check.
    if re.search(r"workflows?", message, re.I):
        return ""

    candidates = _extract_candidates(message)
    candidates.extend(
        c for c in _extract_layman_candidates(message, output_dir)
        if c not in candidates
    )
    if not candidates:
        return ""

    for cand in candidates:
        try:
            r = find_resources(output_dir, cand)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(r, dict):
            continue
        ent = r.get("matched_entity")
        pages = r.get("pages") or []
        if not ent or len(pages) < 2:
            continue

        # Rank pages by kind so the enumeration reads naturally.
        kind_order = {"list": 0, "detail": 1, "create": 2, "edit": 3}
        pages_sorted = sorted(
            pages, key=lambda p: (kind_order.get(p.get("kind"), 99), p.get("route", "")),
        )

        # Educated guess: which page kind is likely for the ask.
        # Confidence gated — only mark ← likely when TWO signals align
        # (verb-kind match AND the page's name/route echoes a specific
        # keyword from the ask). Otherwise omit, so a layman picks by
        # function rather than following a bad hint.
        guess = _guess_target_kind(message)
        page_lines = []
        msg_lower = (message or "").lower()
        for p in pages_sorted:
            route = p.get("route", "")
            kind = p.get("kind", "")
            plan_name = p.get("name")
            label = _humanize_page_name(plan_name, route, kind)
            # Two-signal check: verb-kind matches AND some token from
            # the page's name appears in the message (excluding stopwords).
            marker = ""
            if kind == guess:
                keyword_hit = _page_name_echoed_in(plan_name, route, msg_lower)
                if keyword_hit:
                    marker = "  ← likely for this ask"
            page_lines.append(f"  • `{route}` — {label}{marker}")

        wf_count = len(r.get("workflows") or [])
        deps = r.get("fks_in") or []
        hint_line = (
            f"**{ent}** has **{len(pages)} primary pages**"
            + (f" and **{wf_count} workflows**" if wf_count else "")
            + (f"; dependent entities: "
               + ", ".join(sorted({d['from'].split('.')[0] for d in deps}))
               if deps else "")
        )

        # Detect if the ask is a feature-add (Kanban, board, drag,
        # workflow-transition wording) → hint that path
        is_feature = _looks_like_feature_add(message)
        feature_hint = ""
        if is_feature:
            feature_hint = (
                "\n\nYour ask sounds like a **new feature** (drag-to-transition, "
                "stage view, board). Two ways to add it:\n"
                "  1. **Replace an existing page** with a Kanban archetype "
                "(e.g. turn `/candidates` into a board)\n"
                "  2. **Add a new page** at a new route (e.g. `/candidates/board`)\n"
                "Which do you prefer, and which page (if replacing)?"
            )

        return (
            f"📍 {hint_line}\n\n"
            f"Pick where you want the change:\n"
            + "\n".join(page_lines)
            + feature_hint
        )

    return ""


def _humanize_page_name(
    plan_name: str | None, route: str, kind: str,
) -> str:
    """Layman-facing label for a page. Preference order:
    1. Plan-authored name ("CandidateApplyWizardPage" → "Candidate Apply
       Wizard") — the LLM already picked meaningful words we can reuse.
    2. Route-derived humanization ("/candidates/new" → "New Candidate",
       "/applications/[id]/edit" → "Edit Application").
    3. Kind alone as last resort ("Detail page", "List page")."""
    if isinstance(plan_name, str) and plan_name.strip():
        # Drop "Page" / "View" suffix; split camel/PascalCase.
        clean = re.sub(r"(?:Page|Screen|View)$", "", plan_name).strip()
        spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", clean).strip()
        if spaced:
            return spaced
    # Route-based fallback (works for /candidates/new, /applications/[id]/edit)
    parts = [p for p in (route or "").strip("/").split("/") if p and not p.startswith("[")
             and p not in (":id", ":slug")]
    if parts:
        last = parts[-1].replace("-", " ").replace("_", " ").title()
        entity_part = parts[0].replace("-", " ").replace("_", " ").title()
        # Singularize a simple trailing "s" so "candidates/new" reads
        # "New Candidate", not "New Candidates".
        singular = entity_part[:-1] if entity_part.endswith("s") else entity_part
        if kind == "create":
            return f"New {singular}"
        if kind == "edit":
            return f"Edit {singular}"
        if kind == "detail":
            return f"{singular} details"
        if kind == "list":
            return f"{entity_part} list"
        return f"{singular} — {last}"
    return f"{(kind or 'page').capitalize()} page"


_PAGE_NAME_STOPWORDS = {
    "page", "screen", "view", "component", "form", "the", "a", "an",
    "and", "or", "list", "detail", "new", "edit", "create", "update",
}


def _page_name_echoed_in(
    plan_name: str | None, route: str, message_lower: str,
) -> bool:
    """True when the page has a keyword that also appears in the user's
    message (case-insensitive, stopwords ignored). Used as the second
    signal for the "← likely" marker so we don't hint on verb match
    alone. E.g. page name "Candidate Apply Wizard" + message "add a
    candidate" → shares "candidate" → confident."""
    tokens: set[str] = set()
    if isinstance(plan_name, str):
        # PascalCase / camelCase split so "CandidateApplyWizardPage" →
        # ["Candidate", "Apply", "Wizard", "Page"]. Without this the
        # whole name comes back as one glob and never matches user
        # words.
        for t in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", plan_name):
            tl = t.lower()
            if len(tl) >= 4 and tl not in _PAGE_NAME_STOPWORDS:
                tokens.add(tl)
    for seg in (route or "").split("/"):
        seg_clean = re.sub(r"[\[\]:]", "", seg)
        if len(seg_clean) >= 4 and seg_clean.lower() not in _PAGE_NAME_STOPWORDS:
            tokens.add(seg_clean.lower())
    if not tokens:
        return False
    return any(t in message_lower for t in tokens)


_FEATURE_VERBS = re.compile(
    r"\b(drag|drop|kanban|board|stages?|columns?|move.*(from|to)|"
    r"transition|swimlane|pipeline|flow)\b", re.I,
)


def _looks_like_feature_add(message: str) -> bool:
    """The message describes a new feature (Kanban view, drag transitions,
    stage columns) — needs archetype + workflow wiring, not a small edit."""
    return bool(_FEATURE_VERBS.search(message))


# Order matters — the FIRST match wins. Create/Edit/List are more
# discriminating verbs than "profile" (which many entity names contain
# incidentally, e.g. "Add Candidate Profile"), so they must be tried
# first. Live-observed on the "In Add Candidate Profile, remove
# duplicate Cv Url" ask — "Profile" matched detail before "Add" got a
# chance, so the create-page target was mismarked.
_KIND_HINTS = [
    (re.compile(r"\b(add|create|new)\b", re.I), "create"),
    (re.compile(r"\b(edit|update|modify|change)\b", re.I), "edit"),
    (re.compile(r"\b(list|table|grid|rows?|all|see everyone|browse)\b", re.I), "list"),
    (re.compile(r"\b(detail|profile|view|inspect|open)\b", re.I), "detail"),
]


def _guess_target_kind(message: str) -> str | None:
    """Which page kind (list/detail/create/edit) does the message most
    likely target? Returns None when the message is ambiguous."""
    for regex, kind in _KIND_HINTS:
        if regex.search(message):
            return kind
    return None


def _strip_leading_stopwords(s: str) -> str:
    """`"The Recruitment Drive"` → `"Recruitment Drive"` — drop leading
    articles/conjunctions the regex may have captured."""
    tokens = s.split()
    while tokens and tokens[0].lower() in _STOPWORDS:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in _STOPWORDS:
        tokens.pop()
    return " ".join(tokens)
