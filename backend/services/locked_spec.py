"""Locked Spec — Layer 1 of the contracts-before-generation architecture.

The planner's job is to fill in structure the spec ALLOWS. It must not add
new entities, actors, or features that weren't extracted here. Everything
downstream (page manifest, workflow generator, page schemas) READS this
spec — nothing else re-derives entity lists from the prompt.

Extraction is deterministic-first (keyword heuristics against a curated
vocab) with optional LLM refinement. When ANTHROPIC_API_KEY is missing the
deterministic path still produces a usable spec so the pipeline never blocks
on model availability.

Contract (JSON, persisted to contracts/locked_spec.json):

    {
      "actors":    [{"role": "user", "permissions_hint": []}],
      "entities":  [{"name": "Scan", "kind": "event", "cardinality": "many"}],
      "features":  [{"name": "scan-product", "actor": "user",
                     "verb": "scan", "target_entity": "Scan"}],
      "externals": [{"type": "mcp", "provider": "Firecrawl"}]
    }

Entity kinds:
- entity   : managed record (Retailer, Customer). Gets CRUD.
- event    : append-only record (Scan, PriceResult). Gets list+detail only.
- role     : an actor label (User, Admin). No pages, no table.
- external : lives in another system (Firecrawl MCP). No pages, no table.
- derived  : computed view of other data. No table, may get list page.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


EntityKind = Literal["entity", "event", "role", "external", "derived"]


@dataclass
class Actor:
    role: str
    permissions_hint: list[str] = field(default_factory=list)


@dataclass
class Entity:
    name: str
    kind: EntityKind
    cardinality: Literal["one", "many"] = "many"


@dataclass
class Feature:
    name: str
    actor: str
    verb: str
    target_entity: str | None = None


@dataclass
class ExternalDep:
    type: Literal["mcp", "api", "webhook"]
    provider: str


@dataclass
class LockedSpec:
    actors: list[Actor] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)
    externals: list[ExternalDep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "actors": [asdict(a) for a in self.actors],
            "entities": [asdict(e) for e in self.entities],
            "features": [asdict(f) for f in self.features],
            "externals": [asdict(x) for x in self.externals],
        }


# ---------- deterministic classifiers -------------------------------------

# Entity kind hints. Order matters: role and event win over entity when
# a word matches multiple.
_ROLE_WORDS = {
    "user", "users", "admin", "admins", "customer", "customers",
    "operator", "operators", "member", "members", "guest", "guests",
    "manager", "managers", "owner", "owners", "buyer", "buyers",
    "seller", "sellers", "visitor", "visitors",
}

_EVENT_WORDS = {
    "scan", "scans", "event", "events", "log", "logs", "click",
    "impression", "view", "views", "activity", "activities",
    "history", "record", "records", "session", "sessions", "attempt",
    "submission", "submissions", "reading", "readings",
    "measurement", "measurements", "result", "results",
    "message", "messages", "notification", "notifications",
}

_EXTERNAL_HINTS = {
    "firecrawl": ("mcp", "Firecrawl"),
    "stripe":    ("api", "Stripe"),
    "twilio":    ("api", "Twilio"),
    "openai":    ("api", "OpenAI"),
    "anthropic": ("api", "Anthropic"),
    "sendgrid":  ("api", "SendGrid"),
    "resend":    ("api", "Resend"),
    "slack":     ("api", "Slack"),
    "github":    ("api", "GitHub"),
    "s3":        ("api", "S3"),
    "aws":       ("api", "AWS"),
    "gcp":       ("api", "GCP"),
}

# Nouns that commonly appear as first-class entities in the domain. Extended
# ad-hoc by the extractor when Capitalized words show up in the prompt.
_ENTITY_HINT_NOUNS = {
    "product", "item", "retailer", "seller", "order", "invoice",
    "customer", "supplier", "vendor", "category", "brand", "tag",
    "post", "article", "comment", "review", "rating", "message",
    "task", "project", "milestone", "epic", "story", "bug", "ticket",
    "candidate", "applicant", "job", "role", "interview", "offer",
    "asset", "file", "document", "report", "invoice", "receipt",
    "booking", "reservation", "appointment", "slot", "room",
    "channel", "workspace", "organization", "team", "department",
}


# Verb→feature-name normalizer. Keeps `_extract_features` from producing
# free-form names.
_VERB_ALIASES = {
    "scan": "scan", "scans": "scan", "scanning": "scan",
    "upload": "upload", "uploads": "upload", "uploading": "upload",
    "view": "view", "views": "view", "viewing": "view", "see": "view",
    "browse": "view", "list": "view",
    "compare": "compare", "comparison": "compare",
    "identify": "identify", "identifies": "identify", "detect": "identify",
    "manage": "manage", "control": "manage", "administer": "manage",
    "allow": "manage", "disallow": "manage", "enable": "manage", "disable": "manage",
    "prioritize": "manage",
    "store": "record", "save": "record", "log": "record",
    "add": "create", "create": "create", "new": "create",
    "edit": "update", "update": "update", "modify": "update",
    "delete": "delete", "remove": "delete",
    "search": "search", "find": "search",
    "login": "auth", "sign-in": "auth", "signin": "auth", "register": "auth", "signup": "auth", "sign-up": "auth",
}


def _canon_noun(word: str) -> str:
    """Trim plurals and lowercase — a naive singularizer good enough for
    the vocab. `retailers` → `retailer`, `products` → `product`."""
    w = word.lower().rstrip(",.;:'\"?!)(")
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("ses"):
        return w[:-2]
    if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _classify_entity(word: str) -> EntityKind:
    w = _canon_noun(word)
    if w in _ROLE_WORDS or word.lower() in _ROLE_WORDS:
        return "role"
    if w in _EVENT_WORDS or word.lower() in _EVENT_WORDS:
        return "event"
    return "entity"


def _titlecase(word: str) -> str:
    w = _canon_noun(word)
    return w[:1].upper() + w[1:] if w else word


def _tokenize(prompt: str) -> list[str]:
    """Split into cleanish word tokens — punctuation stripped, hyphens kept
    (single-page-app → single-page-app), retains original casing."""
    return re.findall(r"[A-Za-z][A-Za-z\-]*", prompt)


# ---------- extractors -----------------------------------------------------

def extract_actors(prompt: str) -> list[Actor]:
    """Pull roles/personas from the prompt.

    Heuristic: any word that matches _ROLE_WORDS becomes an actor. Always
    seed with `user` since almost every app has one; add `admin` if any
    admin-signal word appears."""
    tokens = _tokenize(prompt)
    seen: dict[str, Actor] = {}
    seen["user"] = Actor(role="user")
    for tok in tokens:
        w = _canon_noun(tok)
        if w in _ROLE_WORDS:
            # Normalize role variants: admins→admin, customers→customer
            if w not in seen:
                seen[w] = Actor(role=w)
    return list(seen.values())


def extract_externals(prompt: str) -> list[ExternalDep]:
    """Detect external service dependencies mentioned in the prompt."""
    lp = prompt.lower()
    out: list[ExternalDep] = []
    seen: set[str] = set()
    for hint, (kind, provider) in _EXTERNAL_HINTS.items():
        if hint in lp and provider not in seen:
            out.append(ExternalDep(type=kind, provider=provider))
            seen.add(provider)
    return out


def extract_entities(prompt: str, actors: list[Actor] | None = None) -> list[Entity]:
    """Pull noun phrases and classify each as entity/event.

    ONLY extracts words that match the curated `_ENTITY_HINT_NOUNS` /
    `_EVENT_WORDS` vocab. The previous Capitalized-proper-noun sweep was
    too noisy — sentence-starters ("The", "Mobile-first"), verb forms
    ("Store" as in "Store scan history"), and external provider names
    (Firecrawl, MCP) all leaked in. If the curated vocab misses a domain
    noun, extend the vocab — don't loosen the heuristic.

    Actors (User, Admin) and external providers (Firecrawl, Stripe, …)
    are excluded — they belong in actors[]/externals[] respectively.
    """
    tokens = _tokenize(prompt)
    actor_roles = {a.role for a in (actors or [])}
    external_hints = {k for k in _EXTERNAL_HINTS}
    verb_aliases = set(_VERB_ALIASES)
    hits: dict[str, Entity] = {}

    for tok in tokens:
        canon = _canon_noun(tok)
        low = tok.lower()
        # Exclusions — actors and external providers never become entities.
        if canon in actor_roles or low in actor_roles:
            continue
        if canon in external_hints or low in external_hints:
            continue
        # Verb-vs-noun ambiguity: words like "scan" are BOTH a verb (extract_features
        # will pick them up) AND an event noun (a "Scan" is a recorded event). If
        # the word is in _EVENT_WORDS, it survives the verb exclusion — event nouns
        # take priority over verb interpretation. Pure control verbs (create/update/
        # delete/add) are never in _EVENT_WORDS, so they still get filtered.
        if (canon in verb_aliases or low in verb_aliases) and canon not in _EVENT_WORDS:
            continue
        # Only curated-vocab matches.
        if canon in _ENTITY_HINT_NOUNS or canon in _EVENT_WORDS:
            name = _titlecase(tok)
            if name.lower() not in {k.lower() for k in hits}:
                hits[name] = Entity(name=name, kind=_classify_entity(canon))
    return list(hits.values())


def extract_features(
    prompt: str,
    actors: list[Actor],
    entities: list[Entity],
) -> list[Feature]:
    """Verb→feature mapping.

    Each canonical verb in the prompt becomes a feature. We attribute it
    to the closest actor (admin if the sentence starts with "Admin",
    else 'user') and try to bind a target entity by scanning the same
    clause. Auth features are added if the prompt mentions per-user
    scoping (which implies signup/login).
    """
    out: list[Feature] = []
    seen: set[str] = set()
    entity_names = {e.name.lower() for e in entities}
    entity_lookup = {e.name.lower(): e.name for e in entities}

    # Split by sentence for actor attribution.
    for sentence in re.split(r"[.!?]+", prompt):
        s_lower = sentence.lower()
        # Attribute the sentence to an actor by scanning for the first role word.
        this_actor = "user"
        for a in actors:
            if re.search(rf"\b{re.escape(a.role)}s?\b", s_lower):
                this_actor = a.role
                break
        # Sweep every token for a verb-alias.
        for tok in _tokenize(sentence):
            verb = _VERB_ALIASES.get(tok.lower())
            if not verb:
                continue
            # Bind target entity: first entity name that appears in the
            # sentence (any casing). None if no match.
            target = None
            for name_lower, name in entity_lookup.items():
                if name_lower in s_lower or _canon_noun(name_lower) in s_lower:
                    target = name
                    break
            feature_name = f"{verb}-{target.lower()}" if target else verb
            key = f"{this_actor}:{feature_name}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Feature(name=feature_name, actor=this_actor, verb=verb, target_entity=target))

    # Implicit auth features when prompt implies per-user scoping.
    if any(phrase in prompt.lower() for phrase in ["per user", "per-user", "each user", "for each user"]):
        for name in ("login", "register"):
            key = f"user:{name}"
            if key not in seen:
                seen.add(key)
                out.append(Feature(name=name, actor="user", verb="auth", target_entity=None))
    return out


# ---------- public API -----------------------------------------------------

def build_locked_spec(prompt: str, archetype_hint: str | None = None) -> LockedSpec:
    """Extract the full locked spec from a prompt. Deterministic; safe to
    call with no external services.

    Detection order:
      1. If ``archetype_hint`` is given, use it verbatim.
      2. Otherwise call archetype_detector.detect_archetype(prompt) — the
         keyword classifier over registered archetypes.
      3. If an archetype resolves, its defaults are unioned into the
         extracted spec via apply_archetype_to_spec: actors, entities,
         features, and externals are added if not already present; the
         archetype's kind classification WINS for shared entities; and
         its ANTI_ENTITIES are removed. This is how "user mentions
         product → forge_cart" gets suppressed for a comparison archetype.
      4. If no archetype fires, the freeform extraction stands.
    """
    actors = extract_actors(prompt)
    entities = extract_entities(prompt, actors)
    features = extract_features(prompt, actors, entities)
    externals = extract_externals(prompt)
    spec = LockedSpec(actors=actors, entities=entities, features=features, externals=externals)

    # Archetype resolution + injection.
    try:
        from services.archetype_detector import apply_archetype_to_spec, detect_archetype
        resolved = archetype_hint or detect_archetype(prompt)
        if resolved:
            logger.info("[locked-spec] archetype resolved: %s", resolved)
            spec = apply_archetype_to_spec(spec, resolved)
    except Exception as exc:  # noqa: BLE001 — never block spec build on the detector
        logger.warning("[locked-spec] archetype resolution skipped: %s", exc)
    return spec


def persist_locked_spec(spec: LockedSpec, output_dir: str | Path) -> Path:
    """Write the locked spec to contracts/locked_spec.json. Downstream
    generators read this file as authority."""
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "locked_spec.json"
    path.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")
    return path


async def build_locked_spec_async(prompt: str, archetype_hint: str | None = None) -> LockedSpec:
    """LLM-refined variant of build_locked_spec.

    Same deterministic backbone (actors/entities/features/externals extracted
    from the prompt), then defers to classify_app_archetype so the LLM can:
      1. Confirm/override the archetype pick.
      2. Rename the archetype's default entities to match the description's
         domain (e.g. Scan → ArtworkScan for an art scanner).
      3. Propose extra entities the archetype didn't cover.

    Falls back cleanly to the deterministic behavior when no LLM is
    reachable — same public shape either way. Callers that already know
    the archetype can pass `archetype_hint` to skip classification.
    """
    actors = extract_actors(prompt)
    entities = extract_entities(prompt, actors)
    features = extract_features(prompt, actors, entities)
    externals = extract_externals(prompt)
    spec = LockedSpec(actors=actors, entities=entities, features=features, externals=externals)

    try:
        from services.archetype_classifier import classify_app_archetype
        from services.archetype_detector import apply_archetype_match_to_spec
        match = await classify_app_archetype(prompt)
        if archetype_hint and match.archetype != archetype_hint:
            match.archetype = archetype_hint
        spec = apply_archetype_match_to_spec(spec, match)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[locked-spec] async classifier skipped: %s", exc)
        # Fall through to the sync deterministic detector as a safety net.
        try:
            from services.archetype_detector import apply_archetype_to_spec, detect_archetype
            resolved = archetype_hint or detect_archetype(prompt)
            if resolved:
                spec = apply_archetype_to_spec(spec, resolved)
        except Exception:
            pass
    return spec


def load_locked_spec(output_dir: str | Path) -> LockedSpec | None:
    """Read the persisted spec back. Returns None if the pipeline hasn't
    run Layer 1 yet (soft-fail — callers should fall back to legacy path)."""
    base = Path(output_dir)
    path = base / "contracts" / "locked_spec.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LockedSpec(
            actors=[Actor(**a) for a in data.get("actors", [])],
            entities=[Entity(**e) for e in data.get("entities", [])],
            features=[Feature(**f) for f in data.get("features", [])],
            externals=[ExternalDep(**x) for x in data.get("externals", [])],
        )
    except Exception as exc:
        logger.warning("[locked-spec] failed to load %s: %s", path, exc)
        return None
