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
    entity_key,
    is_valid_id,
    page_key,
    parse_id,
    prose_key,
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
