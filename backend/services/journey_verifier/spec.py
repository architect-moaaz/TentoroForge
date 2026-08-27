"""Machine-readable Journey specification.

A JourneySpec is the pipeline's declaration of "here's what a real user does
to accomplish X, and here's what the app must do in response." It sits between
`plan.json` (declarative but coarse) and Playwright (executable but verbose):
one spec compiles to one Playwright test, and one plan compiles to N specs.

The verifier is DOMAIN-AGNOSTIC. Every step is a small, typed operation with
a controlled action vocabulary — a driver that knows the vocab can run any
spec, whether it's a recruitment app, e-commerce, or visual product search.

Vocabulary rationale: we keep verbs short and typed so a) a deterministic
emitter can synthesize the spec from an archetype without an LLM, b) a
Playwright driver can dispatch on `step.kind` without pattern-matching prose,
and c) failures classify cleanly ("wait_for_workflow timed out" attributes
much better than "the test failed after 90s").
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Step vocabulary
# ---------------------------------------------------------------------------
# Each step is a small typed action. The driver dispatches on `kind`.

# Navigation + auth
StepKind = Literal[
    "visit",             # navigate to a route
    "login_as",          # authenticate as a seed user
    "logout",
    # Form + interaction
    "fill",              # fill a form field
    "upload",            # upload a file to a control
    "click",             # click a button / link / interactive
    "select",            # pick an option in a Select
    # Waits (async state)
    "wait_for_route",    # URL contains substring
    "wait_for_element",  # element becomes visible
    "wait_for_entity",   # DB row matching filter appears (or grows to N)
    "wait_for_workflow", # workflow run reaches a target status
    # Assertions
    "assert_element",    # element visible / contains text
    "assert_route",      # URL matches
    "assert_entity",     # DB row matches filter + field value
    "assert_no_console_errors",  # no JS errors since last checkpoint
]


@dataclass
class Locator:
    """How to find a DOM element.

    Prefer `journey_slug` — it maps to `data-journey="<slug>"` which page
    emitters add for buttons/inputs the plan references. Role + label is
    the fallback (matches shadcn conventions); text is last resort.
    """
    journey_slug: str | None = None   # data-journey="<slug>"
    role: str | None = None            # 'button' | 'textbox' | 'link' | ...
    label: str | None = None           # accessible name (button/link text, aria-label)
    text: str | None = None            # visible text (fallback only)
    css: str | None = None             # raw CSS selector (escape hatch)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class EntityFilter:
    """Filter for `wait_for_entity` / `assert_entity`.

    `min_count` supports "at least N rows appeared" — the workflow-runs-to-
    completion assertion we needed today reads as
    `wait_for_entity(entity="price_results", filter={"scan_session_id": ...},
                    min_count=1)`.
    """
    entity: str                         # entity/table name from the registry
    where: dict[str, str] = field(default_factory=dict)
    min_count: int = 1
    equals: dict[str, Any] | None = None  # for assert_entity: specific field values


@dataclass
class WorkflowFilter:
    """For `wait_for_workflow`. Polls workflow_execution_log."""
    workflow_id: str                    # e.g. "scan-product-workflow"
    target_status: Literal["completed", "failed", "terminal"] = "terminal"
    timeout_ms: int = 90_000


@dataclass
class Step:
    """One action in a journey. The driver dispatches on `kind`.

    Optional `name` gives the step a human-readable label — shown in the
    Playwright report and (eventually) the live view voiceover.
    """
    kind: StepKind
    name: str | None = None

    # Populated per kind — kept flat for JSON-friendliness rather than a
    # per-kind subclass hierarchy. The emitter validates required fields.
    route: str | None = None
    email: str | None = None
    password: str | None = None
    locator: Locator | None = None
    value: str | int | float | bool | None = None
    fixture: str | None = None          # fixture slug for `upload`
    entity_filter: EntityFilter | None = None
    workflow_filter: WorkflowFilter | None = None
    timeout_ms: int = 15_000

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "timeout_ms": self.timeout_ms}
        if self.name: d["name"] = self.name
        if self.route: d["route"] = self.route
        if self.email: d["email"] = self.email
        if self.password: d["password"] = self.password
        if self.locator: d["locator"] = self.locator.to_dict()
        if self.value is not None: d["value"] = self.value
        if self.fixture: d["fixture"] = self.fixture
        if self.entity_filter:
            ef = self.entity_filter
            d["entity_filter"] = {
                "entity": ef.entity, "where": ef.where, "min_count": ef.min_count,
                **({"equals": ef.equals} if ef.equals else {}),
            }
        if self.workflow_filter:
            wf = self.workflow_filter
            d["workflow_filter"] = {
                "workflow_id": wf.workflow_id,
                "target_status": wf.target_status,
                "timeout_ms": wf.timeout_ms,
            }
        return d


@dataclass
class Journey:
    """One user-visible journey the app promises to support.

    Slug is stable across regenerations (`primary-scan`), name is human-
    readable (`Scan a product and see prices`). Actor references an actor
    from the plan; the fixture resolver hands the driver a seeded user
    with that role.
    """
    slug: str
    name: str
    actor: str                           # role from plan.actors, e.g. "Member"
    steps: list[Step]
    tags: list[str] = field(default_factory=list)   # 'primary', 'admin', 'optional'

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "actor": self.actor,
            "tags": self.tags,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class JourneySpec:
    """Top-level bundle: all journeys for one app + the fixture registry.

    `fixtures` maps slug → filesystem path (resolved at emit time), so the
    driver can just `page.setInputFiles(locator, fixtures[slug])`. The
    seed_users list drives `login_as`.
    """
    app_slug: str
    archetype: str                        # e.g. "visual_product_search"
    base_url: str = "http://localhost:3000"
    seed_users: list[dict[str, str]] = field(default_factory=list)
    fixtures: dict[str, str] = field(default_factory=dict)
    journeys: list[Journey] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "app_slug": self.app_slug,
            "archetype": self.archetype,
            "base_url": self.base_url,
            "seed_users": self.seed_users,
            "fixtures": self.fixtures,
            "journeys": [j.to_dict() for j in self.journeys],
        }
