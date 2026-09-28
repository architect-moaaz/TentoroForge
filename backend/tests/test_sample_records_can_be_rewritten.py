"""Wrong sample records are something Smith can fix, not only explain.

Test2, 2026-09-28: the Area samples paired Nepal with Uttar Pradesh — a
country list of four beside a state list of six, and two countries the app
was not for. The seeder skips a table that has rows, so nothing reached them.
"""
import json

import pytest

from services.smith import sample_data
from services.smith.section_change import SectionChangeError
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

AREA = {"id": "ENT-002", "name": "Area", "table": "areas", "fields": [
    {"name": "id", "type": "uuid", "primaryKey": True},
    {"name": "country", "type": "string", "examples": ["India", "Nepal", "Bangladesh", "Sri Lanka"]},
    {"name": "state", "type": "string", "examples": ["Maharashtra", "Uttar Pradesh", "Gujarat"]},
    {"name": "pincode", "type": "string", "examples": ["400069", "226010", "380009"]},
    {"name": "workerId", "type": "uuid", "references": "ENT-001"},
]}
DOC = {"requirements": [{"description": "Areas are for India and Sri Lanka."}],
       "data": {"entities": [AREA]}}


class Fake:
    def __init__(self, reply):
        self.reply, self.seen = reply, {}

    def __call__(self, *, system, user, schema):
        self.seen = {"system": system, "user": json.loads(user)}
        return json.dumps(self.reply)


def test_the_verb_is_there_and_needs_the_record_type():
    assert REQUIRED_BY_VERB["refresh_sample_data"] == {"entity"}
    assert "rows people entered stay" in VERB_HELP["refresh_sample_data"]


def test_examples_are_asked_for_row_by_row_and_trimmed_to_agree():
    fake = Fake({"fields": [
        {"name": "country", "examples": ["India", "India", "Sri Lanka", "Sri Lanka"]},
        {"name": "state", "examples": ["Maharashtra", "Karnataka", "Western Province", "Central Province", "Extra"]},
        {"name": "pincode", "examples": ["400069", "560066", "00100", "20400"]},
        {"name": "invented", "examples": ["x"]},
    ]})
    out = sample_data.author(DOC, AREA, "only India and Sri Lanka", client=fake)
    assert "ROW BY ROW" in fake.seen["system"]
    assert [f["name"] for f in fake.seen["user"]["fields"]] == ["country", "state", "pincode"]
    assert fake.seen["user"]["asked"] == "only India and Sri Lanka"
    assert set(out) == {"country", "state", "pincode"}          # no invented field, no FK
    assert {len(v) for v in out.values()} == {4}                 # the extra state is dropped
    assert out["state"][2] == "Western Province" and out["country"][2] == "Sri Lanka"


def test_an_empty_reply_changes_nothing():
    with pytest.raises(SectionChangeError):
        sample_data.author(DOC, AREA, "", client=Fake({"fields": []}))


class Svc:
    def __init__(self, doc):
        self.doc, self.commits = json.loads(json.dumps(doc)), []

    def snapshot(self):
        return json.loads(json.dumps(self.doc))

    def validate(self):
        pass

    def commit(self, **kw):
        self.commits.append(kw)


def test_refresh_writes_the_examples_and_says_the_database_was_not_reached(monkeypatch, tmp_path):
    monkeypatch.setattr("services.smith.data_import.database_url", lambda o: "")
    fake = Fake({"fields": [
        {"name": "country", "examples": ["India", "Sri Lanka"]},
        {"name": "state", "examples": ["Maharashtra", "Central Province"]},
        {"name": "pincode", "examples": ["400069", "20400"]},
    ]})
    svc = Svc(DOC)
    out = sample_data.refresh(svc, str(tmp_path), "Area", "only India and Sri Lanka", client=fake)
    fields = {f["name"]: f.get("examples") for f in svc.doc["data"]["entities"][0]["fields"]}
    assert fields["country"] == ["India", "Sri Lanka"] and fields["state"] == ["Maharashtra", "Central Province"]
    assert len(svc.commits) == 1
    said = sample_data.summary_of(out)
    assert "2 of them" in said and "still shows the old ones" in said


def test_imported_data_is_not_sample_data(tmp_path):
    doc = {**DOC, "data": {**DOC["data"], "imports": [{"entity": "ENT-002"}]}}
    with pytest.raises(SectionChangeError, match="imported"):
        sample_data.refresh(Svc(doc), str(tmp_path), "Area", "", client=Fake({}))


def test_a_record_type_seeds_as_many_records_as_its_examples_describe():
    from services.blueprint.projection import SEED_ROWS, seed_rows
    doc = {"data": {"entities": [
        {"id": "ENT-1", "name": "Area", "table": "areas", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "country", "type": "string", "examples": ["India", "India", "Sri Lanka", "Sri Lanka"]},
            {"name": "areaName", "type": "string", "examples": ["Andheri East", "Whitefield", "Colpetty", "Peradeniya"]},
        ]},
        {"id": "ENT-2", "name": "Note", "table": "notes", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "body", "type": "text"},
        ]},
    ]}}
    rows = seed_rows(doc)
    assert [r["areaName"] for r in rows["areas"]] == ["Andheri East", "Whitefield", "Colpetty", "Peradeniya"]
    assert len(rows["notes"]) == SEED_ROWS


def test_the_rows_an_older_seed_wrote_past_the_examples_are_sample_rows_too(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr("services.smith.data_import.database_url", lambda o: "postgresql://x/y")
    monkeypatch.setattr(sample_data, "replace_rows",
                        lambda url, table, names, old, new: seen.update(old=old, new=new) or
                        {"removed": 0, "kept": 0, "inserted": 0, "failed": []})
    from services.blueprint.projection import SEED_ROWS
    fake = Fake({"fields": [{"name": "country", "examples": ["India", "Sri Lanka", "India"]},
                            {"name": "state", "examples": ["Goa", "Uva Province", "Assam"]},
                            {"name": "pincode", "examples": ["403001", "90000", "781001"]}]})
    sample_data.refresh(Svc(DOC), str(tmp_path), "Area", "", client=fake)
    assert len(seen["old"]) == SEED_ROWS and len(seen["new"]) == 3


def test_a_reference_follows_the_label_its_example_names():
    # Test3, 2026-09-28: by position, Tamil Nadu sat in Sri Lanka.
    from services.blueprint.projection import seed_rows
    doc = {"data": {"entities": [
        {"id": "ENT-1", "name": "Country", "table": "countries", "labelField": "name", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "name", "type": "string", "examples": ["India", "Sri Lanka"]}]},
        {"id": "ENT-2", "name": "State", "table": "states", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "name", "type": "string", "examples": ["Maharashtra", "Tamil Nadu", "Western Province"]},
            {"name": "countryId", "type": "uuid", "references": "ENT-1",
             "examples": ["India", "India", "Sri Lanka"]}]},
    ]}}
    rows = seed_rows(doc)
    assert [r["name"] for r in rows["countries"]] == ["India", "Sri Lanka"]      # two, not twelve
    assert [r["countryId"] for r in rows["states"]] == ["ref:countries[0]", "ref:countries[0]", "ref:countries[1]"]


def test_the_field_prompt_asks_references_for_the_parent_label():
    from services.blueprint.executors import NODE_TASKS
    assert "the LABEL of the record it points at" in NODE_TASKS["entity_fields"]
