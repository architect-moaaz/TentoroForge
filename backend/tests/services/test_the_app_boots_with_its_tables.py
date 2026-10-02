"""0l133sp2 could not be signed into, and its editor showed no page.

* push ran before pgvector was switched on, failed on `type "vector"`, exited
  0, and start.sh said "Migrations applied" over a database with no tables —
  `users` included;
* `kycStatus: {type: "string", embedding: {of: "none"}}` became a vector column;
* the SDK's sign-in forms import next-auth/react, every page's preview pulled
  it in, and it read Node's `process` in the browser.
"""
import subprocess
import tempfile
from pathlib import Path

from services.blueprint.embeddings import is_embedding_field
from services.runtime_injector import _generate_startup_script

_STATIC = Path(__file__).resolve().parents[2] / "static"


def test_start_enables_extensions_first_and_a_push_error_stops_it():
    d = Path(tempfile.mkdtemp())
    _generate_startup_script(d)
    script = (d / "start.sh").read_text()
    assert script.index("npx tsx src/db/extensions.ts") < script.index("npx drizzle-kit push")
    assert "PIPESTATUS[0]" in script and "PostgresError" in script
    assert subprocess.run(["bash", "-n", str(d / "start.sh")]).returncode == 0


def test_only_a_vector_is_an_embedding_column():
    assert is_embedding_field({"name": "photoEmbedding", "type": "vector", "embedding": {"of": "photo"}})
    assert not is_embedding_field({"name": "kycStatus", "type": "string", "embedding": {"of": "none"}})
    assert is_embedding_field({"name": "e", "embedding": {"of": "photo"}}), "untyped, it says what it is"


def test_the_editor_draws_sign_in_without_next_auth():
    jit = (_STATIC / "react-jit.mjs").read_text()
    assert 'next-auth\\/react$/ }, () => ({ path: join(shims, "next-auth.tsx")' in jit
    shim = (_STATIC / "jit-shims" / "next-auth.tsx").read_text()
    for name in ("signIn", "signOut", "useSession", "SessionProvider", "getSession"):
        assert f"export {'async function' if name in ('signIn', 'signOut', 'getSession') else 'function'} {name}" in shim
    code = [l for l in shim.splitlines() if not l.lstrip().startswith("//")]
    assert not any("process" in l for l in code), "the stub reads nothing from Node"


def test_demo_rows_link_to_real_parents_and_a_failed_seed_is_not_remembered():
    import json
    import tempfile
    from services.blueprint.projection import project_seed

    member, tool, rental = "ENTITY-001", "ENTITY-002", "ENTITY-003"
    doc = {"data": {"entities": [
        {"id": member, "name": "Member", "table": "members", "account": True, "fields": [{"name": "name", "type": "string"}]},
        {"id": tool, "name": "Tool", "table": "tools", "fields": [{"name": "ownerId", "type": "uuid"}]},
        {"id": rental, "name": "Rental", "table": "rentals", "fields": [
            {"name": "toolId", "type": "uuid"}, {"name": "borrowerId", "type": "uuid"}, {"name": "caseId", "type": "uuid"}]},
    ], "relationships": [{"from": member, "fromField": "id", "to": tool, "toField": "ownerId", "kind": "one_to_many"}]}}
    out = Path(tempfile.mkdtemp())
    project_seed(doc, out)
    seed = json.loads((out / "src/db/seed.json").read_text())
    assert seed["tools"][0]["ownerId"] == "ref:members[0]", "from the declared relationship"
    rental_row = seed["rentals"][0]
    assert rental_row["toolId"] == "ref:tools[0]", "from the entity the name says"
    assert rental_row["borrowerId"] == "ref:members[0]", "a person is the account entity"
    seed_ts = (Path(__file__).resolve().parents[2] / "templates/runtime/seed.ts").read_text()
    assert "if (SEED_MISMATCHES > 0) {" in seed_ts
    assert seed_ts.index("if (SEED_MISMATCHES > 0) {") < seed_ts.index("await recordSeedFingerprint(currentFp);")
