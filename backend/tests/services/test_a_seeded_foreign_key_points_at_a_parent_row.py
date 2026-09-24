"""The projected seed wrote a foreign key as the label "Committee Id 1";
Postgres rejected it as a uuid, every child insert failed, and a demo
database held only the admin. A foreign key seeds as `ref:<table>[i]`,
the token the runtime seeder resolves to the i-th parent row it inserted."""
import json
from pathlib import Path

from services.blueprint.projection import project_seed


def test_a_reference_field_seeds_as_a_ref_token(tmp_path):
    doc = {"data": {"entities": [
        {"id": "ENT-001", "name": "Committee", "table": "committees",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True}, {"name": "name", "type": "string"}]},
        {"id": "ENT-002", "name": "CommitteeMembership", "table": "committee_memberships",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                    {"name": "committeeId", "type": "uuid", "references": "ENT-001"},
                    {"name": "role", "type": "string"}]}]}}
    project_seed(doc, tmp_path)
    seed = json.loads((Path(tmp_path) / "src" / "db" / "seed.json").read_text())
    from services.blueprint.projection import SEED_ROWS
    refs = [r["committeeId"] for r in seed["committee_memberships"]]
    assert refs == [f"ref:committees[{i}]" for i in range(SEED_ROWS)], "a dozen rows point at a dozen parents"
    dates = sorted({str(r.get("joinedAt") or r.get("createdAt") or "")[:7] for r in seed["committee_memberships"]} - {""})
    assert len(dates) >= 3 or not dates, "dated across months, so a trend has a line to draw"
    assert seed["committees"][0]["name"] == "Committee 1"
