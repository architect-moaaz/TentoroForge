"""Seed rows should read like an app, not like a schema dump.

opmk18qr's activity feed, once its bindings were finally correct, read:

    Notification 10 · Type 10 · Message 10

Every string column in the seeder becomes "<ColumnName> <n>": a person's name
is "Notification 10" because the column is `recipientName` and the table is
`notifications`. The values are type-valid and completely uninformative, so a
correctly-wired screen still cannot be judged — you cannot tell a working
feed from a broken one when every row is the column name.

Fabricating a KPI would be lying: it puts a number on screen that nobody
computed. Fabricating a seed row is the entire point of seed data — the rows
are declared fake and exist so the UI can be seen working. So these are
plausible, and deliberately so.

Determinism still matters: reseeding must not churn rows, so every value is a
pure function of (column, index).
"""
import re

from services.seed_values import (
    label_value,
    column_role, person_name, place_name, reference_code, sentence_for,
    value_for_role,
)


class TestReadingWhatAColumnIsFor:
    def test_a_qualified_name_column_is_a_person(self):
        assert column_role("recipientName", "Notification") == "person"
        assert column_role("assigneeName", "Task") == "person"
        assert column_role("createdByName", "Order") == "person"

    def test_a_bare_name_on_a_person_entity_is_a_person(self):
        assert column_role("name", "Employee") == "person"
        assert column_role("fullName", "Manager") == "person"

    def test_a_bare_name_on_a_thing_is_not_a_person(self):
        # "Annual Leave" is a leave type's name, not somebody's.
        assert column_role("name", "LeaveType") != "person"
        assert column_role("title", "Holiday") != "person"

    def test_prose_columns_are_prose(self):
        for c in ("message", "description", "notes", "comment", "body"):
            assert column_role(c, "Notification") == "prose", c

    def test_place_columns_are_places(self):
        for c in ("location", "city", "address", "warehouse"):
            assert column_role(c, "Movement") == "place", c

    def test_code_columns_are_codes(self):
        for c in ("reference", "code", "sku"):
            assert column_role(c, "Order") == "code", c

    def test_a_reference_ID_is_an_id_not_a_code(self):
        # `referenceId` points at another row. Seeding it with a pretty code
        # like "OR-0001" instead of a uuid would break the reference — the id
        # guard has to win over the "reference" keyword.
        assert column_role("referenceId", "Notification") is None

    def test_an_id_column_is_never_prose_or_a_person(self):
        assert column_role("recipientId", "Notification") not in ("person", "prose")

    def test_anything_else_has_no_special_role(self):
        assert column_role("colour", "Widget") is None


class TestTheValuesThemselves:
    def test_a_person_name_looks_like_a_person(self):
        n = person_name(0)
        assert " " in n and n[0].isupper() and "0" not in n

    def test_person_names_vary_across_rows(self):
        names = {person_name(i) for i in range(8)}
        assert len(names) >= 6, "a feed of eight identical names teaches nothing"

    def test_the_same_index_always_gives_the_same_name(self):
        # Reseeding must not churn rows.
        assert person_name(3) == person_name(3)

    def test_a_place_looks_like_a_place(self):
        assert place_name(2)[0].isupper()

    def test_a_code_looks_like_a_code(self):
        c = reference_code("LeaveRequest", 41)
        assert any(ch.isdigit() for ch in c) and c.upper() == c

    def test_prose_is_a_sentence_about_the_thing(self):
        s = sentence_for("message", "Notification", 0)
        assert s.endswith(".") and len(s.split()) >= 4

    def test_prose_does_not_just_echo_the_column_name(self):
        s = sentence_for("message", "Notification", 9)
        assert s != "Message 10"
        assert "Message 10" not in s


class TestTheLiveDefect:
    def test_a_recipient_name_is_no_longer_the_table_name(self):
        assert column_role("recipientName", "Notification") == "person"
        assert "Notification" not in person_name(9)


class TestLabelVocabulary:
    """`Leave Type 1` / `Department 1` is a schema dump wearing a row's clothes.
    A label column names a thing the domain already has words for."""

    def test_departments_get_department_names(self):
        vals = [label_value("name", "Department", i) for i in range(6)]
        assert "Engineering" in vals
        assert all(v and not v[-1].isdigit() for v in vals), vals

    def test_typed_entities_get_type_names(self):
        vals = [label_value("name", "LeaveType", i) for i in range(6)]
        assert "Annual Leave" in vals, vals

    def test_unknown_concepts_decline_rather_than_invent(self):
        # No lexicon entry means no opinion — the caller keeps its own
        # fallback. Inventing words for a concept we don't know produces
        # rows that read confidently and mean nothing.
        assert label_value("name", "Sprocket", 0) is None

    def test_values_are_distinct_so_unique_columns_survive(self):
        vals = [label_value("name", "Department", i) for i in range(8)]
        assert len(set(vals)) == len(vals), vals

    def test_more_rows_than_words_still_yields_distinct_values(self):
        vals = [label_value("name", "Department", i) for i in range(40)]
        assert len(set(vals)) == 40

    def test_label_role_routes_through_the_vocabulary(self):
        assert value_for_role("label", "name", "Department", 0) == \
            label_value("name", "Department", 0)


class TestConceptCarriedByTheColumn:
    """`Notification.type` holds the concept in the COLUMN, not the entity —
    the entity is a Notification, the column is a type. Keying only on the
    entity left these as `Type 10`."""

    def test_a_concept_column_is_a_label(self):
        assert column_role("type", "Notification") == "label"
        assert column_role("status", "LeaveRequest") == "label"
        assert column_role("category", "Expense") == "label"

    def test_the_column_concept_wins_over_the_entity(self):
        assert label_value("type", "Notification", 0) == "Standard"
        assert label_value("status", "LeaveRequest", 0) == "Draft"

    def test_a_plain_name_column_still_defers_to_the_entity(self):
        assert label_value("name", "Department", 0) == "Engineering"

    def test_a_person_column_is_not_hijacked_by_a_concept_column_name(self):
        # `Employee.role` is a concept; `Employee.name` is still a person.
        assert column_role("name", "Employee") == "person"


class TestProseReadsLikeProse:
    def test_a_sentence_never_cites_its_own_row_number(self):
        # "Notification 10 is progressing normally." is the schema dump again,
        # wearing a sentence. Nothing a real app writes numbers its own rows.
        for i in range(12):
            s = sentence_for("message", "Notification", i)
            assert not re.search(r"\b\d+\b", s), s

    def test_sentences_still_vary_by_row(self):
        seen = {sentence_for("message", "Notification", i) for i in range(5)}
        assert len(seen) >= 4, seen

    def test_the_same_row_always_gets_the_same_sentence(self):
        assert sentence_for("message", "Notification", 3) == \
            sentence_for("message", "Notification", 3)
