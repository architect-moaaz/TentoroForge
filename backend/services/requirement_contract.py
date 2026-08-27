"""Requirement contract — turn USER WORDS into hard constraints.

Extract structured constraints from the raw user prompt so the plan
validator + fidelity critic can hold the LLM to them at generation time.
User-named ROUTES, COMPONENTS, ACTION-TYPES, LANDING declarations, and
OUT-OF-SCOPE negations become checks the LLM cannot silently drop or
rename.

Motivating defect (Banking Archive gen `igi1eqs7`): user said
"Landing: /history", "Table of Batches", "SearchInput on /search",
"ocr_document (PaddleOCR)" — planner emitted `/login` as landing,
Kanban for the batches list, no SearchInput, and `http_call` in place
of `ocr_document`. Every single one was a word-drift the LLM
rationalised past. This contract makes those drifts detectable +
repairable at plan-time (via REVISE) and at post-gen-time (via critic).

Pure module. Read-only over a prompt string. Never raises for shape
issues — an empty / broken prompt returns an empty contract, which the
validator treats as "no user-named constraints" (nothing gates).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any


# ────────────────────────────────────────────────────────────
# Whitelists — kept narrow so the extractor doesn't over-fit
# ────────────────────────────────────────────────────────────

# Registered workflow action-types. Mirrors the union in
# services.workflow_step_translator._ACTIONTYPES + _AI_TYPES + ocr_document.
# Snake_case tokens outside this set are NOT extracted as action-types —
# they'd match too much prose (report_generation, data_pipeline, etc).
_KNOWN_ACTION_TYPES: frozenset[str] = frozenset({
    # Data
    "db_insert", "db_update", "db_delete", "db_query",
    # Comms
    "send_email", "send_notification",
    # AI
    "ai_generate", "ai_classify", "ai_extract", "ai_decide",
    "ai_identify_product",
    # OCR
    "ocr_document",
    # Generic
    "http_call", "generate_document", "set_variable", "transform",
    "custom", "mcp_tool_call",
    # Event bus (R3)
    "emit_event", "wait_for_event",
})

# Component names the user commonly names in prose. Extracted as
# {page, component} pairs so the check knows WHICH page must carry each.
# Kept to the visible-surface set — no layout primitives (Stack, Row,
# Card) since users rarely name those and we don't want to fail-loud on
# their absence.
_KNOWN_COMPONENTS: frozenset[str] = frozenset({
    # Input controls
    "SearchInput", "Input", "Textarea", "Select", "Combobox", "DatePicker",
    "TimePicker", "NumberInput", "Switch", "RadioGroup", "Slider",
    "FileUpload", "Rating", "ColorPicker",
    # Structural surfaces the user asks for by name
    "Table", "Kanban", "Calendar", "Timeline", "Gauge", "Chart",
    "Heatmap", "SplitArc", "Stepper",
    # Feedback / signalling
    "Banner", "Toast", "Tag", "Badge", "Progress", "Spinner",
    # Layout surfaces the user typically names ("show a DescriptionList")
    "DescriptionList", "List", "MetricTile", "Stat", "Card", "EmptyState",
    "Repeat", "Cluster", "Accordion", "Drawer", "Tooltip", "Popover",
    "Menubar", "DropdownMenu",
})


# ────────────────────────────────────────────────────────────
# Types
# ────────────────────────────────────────────────────────────

@dataclass
class RequirementContract:
    """Structured user-named constraints extracted from a prompt.

    Every field represents a HARD constraint the LLM must satisfy in
    the generated app. Empty lists mean "user didn't name any of these"
    (no gate applies), NOT "any output is fine" — the LLM is still
    free to add.
    """
    named_routes: list[dict[str, Any]] = field(default_factory=list)
    named_components: list[dict[str, Any]] = field(default_factory=list)
    named_action_types: list[dict[str, Any]] = field(default_factory=list)
    landing_route: str | None = None
    out_of_scope: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────
# Regex primitives
# ────────────────────────────────────────────────────────────

# A route token — slash-prefixed, may contain / segments and {param}
# placeholders. Excludes trailing punctuation. Anchored by whitespace or
# start-of-line so a mid-URL /api/v1 in "https://x.com/api/v1" doesn't
# match (the `https:` prefix keeps the /api segment glued to the URL
# host — we strip full URLs before scanning).
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_ROUTE_RE = re.compile(r"(?<![\w:/])/(?:[a-z][\w-]*)(?:/(?:[\w-]+|\{[\w-]+\}))*",
                       re.IGNORECASE)

# Landing declaration. Three phrasings seen in the wild:
#   "Landing: /X"           "Landing route: /X"          "landing page is /X"
_LANDING_RE = re.compile(
    r"landing(?:\s+(?:route|page))?\s*(?:is|:)\s*(/[\w/{}-]+)",
    re.IGNORECASE,
)

# Out-of-scope markers. Two shapes:
#   Non-goals ... out of scope ... :  bulleted list underneath
#   parenthetical (out of scope for v1)
_PARENTHETICAL_OOS_RE = re.compile(
    r"\(([^)]*out\s+of\s+scope[^)]*)\)", re.IGNORECASE,
)


# ────────────────────────────────────────────────────────────
# Extraction
# ────────────────────────────────────────────────────────────

def _strip_urls(text: str) -> str:
    """Full URLs would leak `/api/v1`-style tokens into the route
    extractor. Blank them out first."""
    return _URL_RE.sub(" ", text)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _extract_named_routes(prompt: str) -> list[dict[str, Any]]:
    text = _strip_urls(prompt)
    hits = _ROUTE_RE.findall(text)
    # The regex may emit trailing punctuation from raw prose ("/upload.");
    # strip a trailing `.`/`,`/`;`/`:`/`)`.
    cleaned = [re.sub(r"[\.,:;\)]+$", "", h) for h in hits]
    unique = _dedupe_preserve_order([c for c in cleaned if c and c != "/"])
    return [{"path": p} for p in unique]


def _line_of(text: str, position: int) -> str:
    """Return the full line containing byte-offset ``position``."""
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def _extract_named_components(prompt: str) -> list[dict[str, Any]]:
    """For each user-named route in the prompt, walk the description block
    that follows and pick out CapitalCase tokens matching known components.

    A "description block" is the text from the route token up to the
    next blank line OR the next route token — whichever comes first.
    Also honours the ``Multi-file dropzone → FileUpload`` synonym so
    common English descriptions land on the right component.
    """
    text = _strip_urls(prompt)
    # Position-aware route scan.
    matches = list(_ROUTE_RE.finditer(text))
    # Attach each component match to the nearest preceding route.
    pairs: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        route = re.sub(r"[\.,:;\)]+$", "", m.group(0))
        block_start = m.end()
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        # Also stop at a blank line — page description doesn't spill
        # across paragraphs into the next section (Design/Non-goals/etc).
        blank = text.find("\n\n", block_start, block_end)
        if blank != -1:
            block_end = blank
        block = text[block_start:block_end]

        # Whitelisted CapitalCase component names.
        for tok in re.findall(r"\b[A-Z][A-Za-z]+\b", block):
            if tok in _KNOWN_COMPONENTS:
                pairs.append((route, tok))

        # Prose synonyms — pick up common English descriptions the
        # planner would otherwise miss.
        lower = block.lower()
        if re.search(r"\b(multi[- ]?file )?dropzone\b|\bfile upload\b|\bupload button\b", lower):
            pairs.append((route, "FileUpload"))
        if re.search(r"\bsearch (bar|input|box)\b", lower):
            pairs.append((route, "SearchInput"))
        if re.search(r"\bdate picker\b", lower):
            pairs.append((route, "DatePicker"))

    # Dedupe.
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        out.append({"page": pair[0], "component": pair[1]})
    return out


def _extract_named_action_types(prompt: str) -> list[dict[str, Any]]:
    """Pick every snake_case token in the prompt that matches a known
    action-type. Attach the nearest preceding "X workflow" heading
    (case-insensitive) as ``workflow`` when present.
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()

    # Precompute workflow-heading positions.
    # "IngestDocument workflow" / "IngestBatch workflow" — anything with
    # a CapitalCase name immediately followed by the word "workflow".
    wf_headings: list[tuple[int, str]] = []
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9]+)\s+workflow\b", prompt):
        wf_headings.append((m.start(), m.group(1)))

    def _wf_for(pos: int) -> str | None:
        best: str | None = None
        best_pos = -1
        for hp, name in wf_headings:
            if hp <= pos and hp > best_pos:
                best = name
                best_pos = hp
        return best

    # Scan for known action-type tokens.
    at_pattern = re.compile(
        r"\b(" + "|".join(re.escape(a) for a in _KNOWN_ACTION_TYPES) + r")\b"
    )
    for m in at_pattern.finditer(prompt):
        at = m.group(1)
        wf = _wf_for(m.start())
        key = (wf, at)
        if key in seen:
            continue
        seen.add(key)
        entry: dict[str, Any] = {"action_type": at}
        if wf is not None:
            entry["workflow"] = wf
        out.append(entry)
    return out


def _extract_landing_route(prompt: str) -> str | None:
    m = _LANDING_RE.search(prompt)
    if not m:
        return None
    route = m.group(1)
    return re.sub(r"[\.,:;]+$", "", route) or None


def _extract_out_of_scope(prompt: str) -> list[str]:
    """Two patterns:

    1. Section header "Non-goals" / "Out of scope" followed by bullets.
    2. Parenthetical "(out of scope for v1)" — the SURFACE the
       parenthetical annotates counts as out-of-scope.
    """
    out: list[str] = []

    # (a) Bulleted non-goals section — a heading whose line contains
    # "out of scope" OR "non-goal" starts the block; consume bullets
    # (`-`, `*`, `•`) until a blank line or another heading.
    lines = prompt.splitlines()
    in_block = False
    for line in lines:
        if not in_block:
            if re.search(r"\b(non[- ]?goals?|out of scope)\b", line, re.IGNORECASE):
                in_block = True
                continue
        else:
            stripped = line.strip()
            if not stripped:
                in_block = False
                continue
            if re.match(r"^(design|workflow|entities|pages)\s*:", stripped,
                        re.IGNORECASE):
                in_block = False
                continue
            m = re.match(r"^[-*•]\s+(.*?)\.?$", stripped)
            if m:
                out.append(m.group(1).strip())

    # (b) Parenthetical annotations. The surface the parenthetical
    # attaches to is the closest preceding capitalised phrase or the
    # word before "(out of scope…)". Keep the whole line for context so
    # the checker sees the surface name.
    for m in _PARENTHETICAL_OOS_RE.finditer(prompt):
        # Grab the line containing this parenthetical — the surface
        # (e.g. "Admin:") is right at its start.
        line = _line_of(prompt, m.start()).strip()
        if line:
            out.append(line)

    return _dedupe_preserve_order(out)


# ────────────────────────────────────────────────────────────
# Public
# ────────────────────────────────────────────────────────────

def extract_contract(prompt: str) -> RequirementContract:
    """Extract user-named constraints from ``prompt``.

    Empty string → empty contract (all fields empty / None). Never
    raises; malformed prose degrades to fewer extractions, never a
    crash.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return RequirementContract()
    return RequirementContract(
        named_routes=_extract_named_routes(prompt),
        named_components=_extract_named_components(prompt),
        named_action_types=_extract_named_action_types(prompt),
        landing_route=_extract_landing_route(prompt),
        out_of_scope=_extract_out_of_scope(prompt),
    )


__all__ = ["extract_contract", "RequirementContract"]
