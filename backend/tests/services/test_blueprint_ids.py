"""An ID that moves is worse than no ID at all.

§21 lets Smith answer "which files implement REQ-017" and §92 lets change
history follow an artifact across revisions. Both are lookups keyed on an ID.
If a re-run renumbers ``Candidate`` from ENTITY-001 to ENTITY-007, every one of
those lookups still resolves — to the wrong artifact. Nothing throws. The
codeMap just quietly points at another entity's files.

So these tests are mostly about the property that is easy to lose and
impossible to notice: allocating twice must be indistinguishable from
allocating once.
"""
import json
import re
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from services.blueprint.ids import (
    ID_PREFIXES,
    IdAllocator,
    InvalidArtifactId,
    UnknownPrefix,
    api_key,
    component_key,
    entity_key,
    integration_key,
    is_valid_id,
    module_key,
    natural_key_for,
    page_key,
    parse_id,
    permission_key,
    prose_key,
    role_key,
    widget_key,
    workflow_key,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TS_IDS = REPO_ROOT / "packages" / "schema" / "src" / "blueprint" / "ids.ts"


# --- format ----------------------------------------------------------------

def test_id_format_matches_section_12():
    assert is_valid_id("REQ-001")
    assert is_valid_id("ENTITY-1000")  # grows past three digits
    assert not is_valid_id("REQUIREMENT-1")
    assert not is_valid_id("REQ-1")
    assert not is_valid_id("")
    assert parse_id("FLOW-042") == ("FLOW", 42)


def test_malformed_id_raises_rather_than_returning_none():
    with pytest.raises(InvalidArtifactId):
        parse_id("nonsense")


# --- the core property -----------------------------------------------------

def test_same_natural_key_returns_same_id(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    first = alloc.allocate("ENTITY", entity_key("Candidate"))
    second = alloc.allocate("ENTITY", entity_key("candidate "))  # trivial edits
    assert first == second == "ENTITY-001"


def test_regeneration_after_reload_does_not_renumber(tmp_path):
    with IdAllocator.session(output_dir=tmp_path) as alloc:
        alloc.allocate("ENTITY", entity_key("Candidate"))
        alloc.allocate("ENTITY", entity_key("Interview"))
        alloc.allocate("PAGE", page_key("/candidates"))

    # a second generation run, fresh process state, keys arriving in a
    # different order than the first time
    with IdAllocator.session(output_dir=tmp_path) as alloc:
        page = alloc.allocate("PAGE", page_key("/candidates"))
        interview = alloc.allocate("ENTITY", entity_key("Interview"))
        candidate = alloc.allocate("ENTITY", entity_key("Candidate"))

    assert candidate == "ENTITY-001"
    assert interview == "ENTITY-002"
    assert page == "PAGE-001"


def test_page_rename_keeps_its_id_because_route_is_the_identity(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    before = alloc.allocate("PAGE", page_key("/candidates"))
    # page title changes from "Candidates" to "Talent Pool"; route is unchanged
    after = alloc.allocate("PAGE", page_key("/candidates/"))
    assert before == after


def test_distinct_artifacts_get_distinct_ids(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    a = alloc.allocate("API", api_key("GET", "/api/candidates"))
    b = alloc.allocate("API", api_key("POST", "/api/candidates"))
    assert a != b
    assert alloc.allocated("API") == ["API-001", "API-002"]


# --- §116 seam: the model judges sameness, this service assigns the number ---

def test_reworded_requirement_allocates_a_new_id_by_default(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    original = alloc.allocate("REQ", prose_key("REQ", "Recruiter can schedule interviews."))
    reworded = alloc.allocate(
        "REQ", prose_key("REQ", "A recruiter is able to book interview slots.")
    )
    # Merging these silently would fuse two requirements. Default is to keep
    # them apart and let Smith decide.
    assert original != reworded


def test_rebind_carries_the_id_across_a_rewording(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    old = prose_key("REQ", "Recruiter can schedule interviews.")
    original = alloc.allocate("REQ", old)

    new = prose_key("REQ", "A recruiter is able to book interview slots.")
    carried = alloc.rebind(old_key=old, new_key=new)

    assert carried == original
    assert alloc.lookup(new) == original
    assert alloc.lookup(old) is None


def test_rebind_refuses_to_collapse_two_live_artifacts(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    a = prose_key("RULE", "Expenses above 50000 need approval.")
    b = prose_key("RULE", "Managers approve vehicle entry.")
    alloc.allocate("RULE", a)
    alloc.allocate("RULE", b)
    with pytest.raises(InvalidArtifactId):
        alloc.rebind(old_key=a, new_key=b)


# --- monotonicity ----------------------------------------------------------

def test_retired_ids_are_never_reissued(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    gone = alloc.allocate("ENTITY", entity_key("Applicant"))
    alloc.retire(gone)
    fresh = alloc.allocate("ENTITY", entity_key("Placement"))
    assert fresh != gone
    assert alloc.is_retired(gone)


def test_restoring_a_deprecated_artifact_reuses_its_own_id(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    key = entity_key("Applicant")
    original = alloc.allocate("ENTITY", key)
    alloc.retire(original)
    assert alloc.allocate("ENTITY", key) == original
    assert not alloc.is_retired(original)


def test_bind_advances_the_counter_so_imported_ids_cannot_be_reminted(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    alloc.bind(entity_key("Candidate"), "ENTITY-050")
    nxt = alloc.allocate("ENTITY", entity_key("Interview"))
    assert nxt == "ENTITY-051"


# --- refusals --------------------------------------------------------------

def test_unknown_prefix_is_refused():
    alloc = IdAllocator()
    with pytest.raises(UnknownPrefix):
        alloc.allocate("GADGET", "GADGET:thing")


def test_anonymous_allocation_is_refused():
    alloc = IdAllocator()
    with pytest.raises(ValueError):
        alloc.allocate("ENTITY", "")


def test_corrupt_registry_raises_instead_of_resetting_to_zero(tmp_path):
    p = IdAllocator.path_for(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ not json", "utf-8")
    # Silently starting from zero would renumber the whole application.
    with pytest.raises(InvalidArtifactId):
        IdAllocator.load(output_dir=tmp_path)


# --- concurrency (§28 permits parallel agents) ------------------------------

def test_threaded_allocation_never_duplicates_an_id(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    out: list[str] = []
    lock = threading.Lock()

    def worker(n: int) -> None:
        got = alloc.allocate("ENTITY", entity_key(f"Entity{n}"))
        with lock:
            out.append(got)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(out) == 50
    assert len(set(out)) == 50


def test_two_processes_do_not_mint_the_same_id(tmp_path):
    """The in-process lock cannot help across agent subprocesses; the file
    lock in ``session()`` is what stops two agents both reading counter N."""
    script = textwrap.dedent(
        """
        import sys
        from services.blueprint.ids import IdAllocator, entity_key
        out_dir, tag = sys.argv[1], sys.argv[2]
        with IdAllocator.session(output_dir=out_dir) as alloc:
            for i in range(20):
                alloc.allocate("ENTITY", entity_key(f"{tag}-{i}"))
        """
    )
    runner = tmp_path / "runner.py"
    runner.write_text(script, "utf-8")
    backend = str(Path(__file__).resolve().parents[2])

    procs = [
        subprocess.Popen(
            [sys.executable, str(runner), str(tmp_path), tag],
            cwd=backend,
            env={"PYTHONPATH": backend, "PATH": "/usr/bin:/bin"},
        )
        for tag in ("a", "b")
    ]
    for p in procs:
        assert p.wait(timeout=60) == 0

    registry = json.loads(IdAllocator.path_for(tmp_path).read_text("utf-8"))
    ids = list(registry["bindings"].values())
    assert len(ids) == 40
    assert len(set(ids)) == 40, "two processes minted the same id"


# --- dropping a key --------------------------------------------------------

def test_unbind_drops_a_duplicate_route_to_an_artifact(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    alloc.bind("PERM:entity 002:read", "PERM-004")            # the old scheme
    alloc.bind("PERM:entity 002:read:role.read", "PERM-004")  # the current one
    assert alloc.unbind("PERM:entity 002:read") == "PERM-004"
    assert alloc.lookup("PERM:entity 002:read") is None
    assert alloc.key_for("PERM-004") == "PERM:entity 002:read:role.read"


def test_unbind_refuses_to_drop_an_artifacts_last_key(tmp_path):
    """Counters never rewind, so the id cannot go to something else — but the
    artifact itself would be renumbered if it were ever re-proposed, and §22
    revival coming back under its own id is what the registry is for."""
    alloc = IdAllocator(_output_dir=str(tmp_path))
    alloc.allocate("ENTITY", entity_key("Candidate"))
    with pytest.raises(InvalidArtifactId):
        alloc.unbind(entity_key("Candidate"))
    assert alloc.lookup(entity_key("Candidate")) == "ENTITY-001"


def test_unbinding_something_that_was_never_bound_raises(tmp_path):
    alloc = IdAllocator(_output_dir=str(tmp_path))
    with pytest.raises(InvalidArtifactId):
        alloc.unbind(entity_key("Nothing"))


# --- one scheme, every section ---------------------------------------------
#
# The key an artifact is written under and the key it is looked up under have
# to be the same string. When they are not, nothing fails: the lookup misses,
# the allocator mints a second id, and the document ends up holding the same
# artifact twice.

SECTION_KEYS = [
    ("data.entities", {"name": "Candidate"}, entity_key("Candidate")),
    ("pages", {"route": "/candidates"}, page_key("/candidates")),
    ("apis", {"method": "GET", "path": "/api/candidates"},
     api_key("GET", "/api/candidates")),
    ("roles", {"name": "Recruiter"}, role_key("Recruiter")),
    ("permissions", {"name": "candidate.read", "subject": "ENTITY-001",
                     "action": "read"},
     permission_key("ENTITY-001", "read", "candidate.read")),
    ("modules", {"name": "Candidate Management"}, module_key("Candidate Management")),
    ("components", {"name": "CandidateTable"}, component_key("CandidateTable")),
    ("workflows", {"name": "Advance Stage"}, workflow_key("Advance Stage")),
    ("businessRules", {"name": "Open on create", "statement": "A role starts open."},
     prose_key("RULE", "A role starts open.")),
    ("requirements", {"description": "Recruiters can post roles."},
     prose_key("REQ", "Recruiters can post roles.")),
    ("tests", {"name": "A new role is open", "kind": "business_rule"},
     prose_key("TEST", "A new role is open")),
    ("integrations", {"name": "Email + Password Session Auth", "kind": "auth"},
     integration_key("Email + Password Session Auth")),
]


@pytest.mark.parametrize("section,artifact,expected", SECTION_KEYS)
def test_natural_key_for_matches_the_documented_scheme(section, artifact, expected):
    assert natural_key_for(section, artifact) == expected


def test_a_widget_is_keyed_on_the_route_behind_its_page_id():
    """Widgets carry a PAGE id; the key wants the route, so the mapping needs
    the document. Without it there is no key rather than a wrong one."""
    widget = {"page": "PAGE-001", "label": "Open Roles", "kind": "metric"}
    routes = {"PAGE-001": "/overview"}
    assert natural_key_for("widgets", widget, page_routes=routes) == \
        widget_key("/overview", "Open Roles")
    assert natural_key_for("widgets", widget) is None


def test_two_grants_of_the_same_action_on_the_same_subject_are_two_artifacts():
    """§12's subject + action is too coarse for a real authorisation model.
    Unscoped read over every role and read over only the role reached through
    an offer under review are both `read` on ENTITY-002; keyed on the pair they
    would be one artifact, and re-proposing either would rewrite the other's
    scope."""
    broad = {"name": "role.read", "subject": "ENTITY-002", "action": "read"}
    narrow = {"name": "role.read_offer_context", "subject": "ENTITY-002",
              "action": "read"}
    assert natural_key_for("permissions", broad) != \
        natural_key_for("permissions", narrow)


def test_a_permission_without_a_subject_still_keys_distinctly():
    """`subject` is optional in the contract. An empty first segment is fine
    now that the name is in the key — it was not when the key was the pair."""
    sign_in = {"name": "session.sign_in", "action": "execute"}
    sign_out = {"name": "session.sign_out", "action": "execute"}
    assert natural_key_for("permissions", sign_in) == \
        permission_key("", "execute", "session.sign_in")
    assert natural_key_for("permissions", sign_in) != \
        natural_key_for("permissions", sign_out)


def test_a_permission_without_a_name_has_no_key():
    """The contract requires it; an artifact that lacks it cannot be told
    apart from its siblings, so it gets no key rather than a colliding one."""
    assert natural_key_for("permissions", {"subject": "ENTITY-002",
                                           "action": "read"}) is None


def test_sections_with_no_scheme_of_their_own_return_none():
    """Not a failure — decisions are keyed on the artifact they decide, and
    codeMap entries have no id to bind. The caller decides what to do."""
    assert natural_key_for("decisions", {"decision": "x", "source": "user"}) is None
    assert natural_key_for("codeMap", {"artifact": "PAGE-001"}) is None
    assert natural_key_for("pages", {"name": "No route here"}) is None


def test_every_id_bearing_section_has_a_key(ats):
    """A new section added to the Blueprint without a key scheme would silently
    fall back to binding artifacts under their own ids, which registers them
    without making them findable."""
    from services.blueprint.orchestrator import graph_pool

    routes = {p["id"]: p.get("route", "") for p in ats["pages"]}
    unkeyed = {
        section for section, art in graph_pool(ats)
        if art.get("id") and natural_key_for(section, art, page_routes=routes) is None
    }
    assert unkeyed == set()


def test_the_same_document_keys_the_same_way_twice(ats):
    """The property the allocator depends on, stated directly."""
    routes = {p["id"]: p.get("route", "") for p in ats["pages"]}
    once = [natural_key_for(s, a, page_routes=routes) for s, a in graph_pool_of(ats)]
    twice = [natural_key_for(s, a, page_routes=routes) for s, a in graph_pool_of(ats)]
    assert once == twice and any(once)


def graph_pool_of(doc):
    from services.blueprint.orchestrator import graph_pool
    return [(s, a) for s, a in graph_pool(doc) if a.get("id")]


# --- cross-language drift ---------------------------------------------------

def test_prefixes_match_the_typescript_schema():
    """The TS side validates IDs; this side mints them. If the two lists drift,
    Python allocates a prefix the Blueprint schema will reject at parse time —
    a failure that would otherwise surface only in generated output."""
    source = TS_IDS.read_text("utf-8")
    block = source.split("export const ID_PREFIXES = [", 1)[1].split("] as const", 1)[0]
    # Entries carry trailing `// comment` annotations; take the quoted tokens.
    ts_prefixes = tuple(re.findall(r'"([A-Z]+)"', block))
    assert ts_prefixes == ID_PREFIXES
