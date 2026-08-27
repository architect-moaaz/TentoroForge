"""Seed rows that read like an app rather than like a schema dump.

Once opmk18qr's activity feed was finally bound to the right columns it read:

    Notification 10 · Type 10 · Message 10

Every string column in the seeder becomes ``"<ColumnName> <n>"``, so a
person's name came out as "Notification 10" — the table is `notifications`
and the column is `recipientName`. Type-valid, and completely uninformative:
with every row echoing its own column name you cannot tell a working screen
from a broken one, which is exactly what seed data exists to let you do.

**Why inventing these is right, when inventing a KPI was not.** A fabricated
metric puts a number on screen that nobody computed and a person may act on
it — that is why the unbound gauge got an empty state instead of a plausible
figure. Seed rows are the opposite: they are declared fake, they exist only
so the UI can be seen working, and a realistic name teaches more than
"Notification 10" while claiming no more.

Determinism is kept throughout: every value is a pure function of the column
and the row index, so reseeding never churns rows.
"""

from __future__ import annotations

import re

# Deliberately small, plainly synthetic, and drawn from several language
# backgrounds so a seeded app does not look like it serves one demographic.
_FIRST = ("Priya", "Marcus", "Ines", "Tomas", "Aisha", "Daniel", "Mei",
          "Olu", "Sofia", "Ravi", "Hannah", "Yusuf", "Clara", "Kenji")
_LAST = ("Raman", "Okafor", "Nguyen", "Silva", "Haddad", "Novak", "Chen",
         "Adeyemi", "Kowalski", "Ferreira", "Bauer", "Osei", "Lindqvist")

_PLACES = ("North Depot", "Harbour Point", "Westfield", "Central Hub",
           "Riverside", "Old Mill", "Station Road", "Kings Cross",
           "Eastgate", "Southbank")

# Column-name signals. Order matters: id checks run first so `recipientId`
# never reads as a person.
_PERSON_QUALIFIERS = ("recipient", "assignee", "assigned", "owner", "author",
                      "createdby", "updatedby", "requester", "approver",
                      "manager", "employee", "user", "member", "staff",
                      "contact", "customer", "person", "reviewer")
# Entities that ARE people, so their bare `name` is somebody's name.
_PERSON_ENTITIES = ("employee", "manager", "user", "admin", "person", "staff",
                    "member", "customer", "contact", "candidate", "recipient")

_PROSE = ("message", "description", "notes", "note", "comment", "body",
          "bio", "summary", "reason", "detail")
_PLACE = ("location", "city", "address", "warehouse", "site", "branch",
          "region", "venue")
_CODE = ("reference", "code", "sku", "barcode", "serial", "ticket", "invoice")

_ID_RE = re.compile(r"(^|[a-z])(id|Id|ID)$")


def _is_id(col: str) -> bool:
    return bool(_ID_RE.search(col)) or col.lower() == "id"


def column_role(column: str, entity: str = "") -> str | None:
    """What this column is *for*, as far as a plausible value is concerned."""
    if not isinstance(column, str) or not column:
        return None
    if _is_id(column):
        return None                      # an id is never prose or a person
    c = column.lower()
    e = (entity or "").lower()

    if "name" in c or c in ("title",) or c.endswith("title"):
        if any(q in c for q in _PERSON_QUALIFIERS):
            return "person"
        if c in ("name", "fullname", "displayname") and \
                any(p in e for p in _PERSON_ENTITIES):
            return "person"
        return "label"                   # a thing's name, not somebody's

    if any(k in c for k in _PROSE):
        return "prose"
    if any(k in c for k in _PLACE):
        return "place"
    if any(k in c for k in _CODE):
        return "code"
    # The concept can live in the column name itself: `Notification.type` is a
    # type, `LeaveRequest.status` is a status. Last, so the more specific roles
    # above keep the columns they already own.
    if _concept(column):
        return "label"
    return None


def person_name(i: int) -> str:
    """A plausible person, stable for a given row index."""
    first = _FIRST[i % len(_FIRST)]
    # Stride the surnames so the pairing does not repeat every 14 rows.
    last = _LAST[(i * 5 + i // len(_FIRST)) % len(_LAST)]
    return f"{first} {last}"


def place_name(i: int) -> str:
    return _PLACES[i % len(_PLACES)]


def reference_code(entity: str, i: int) -> str:
    """`LeaveRequest`, 41 -> `LR-0042`. Readable, sortable, obviously synthetic."""
    letters = "".join(ch for ch in (entity or "REF") if ch.isupper())[:3]
    if not letters:
        letters = (entity or "ref")[:2].upper()
    return f"{letters}-{i + 1:04d}"


def sentence_for(column: str, entity: str, i: int) -> str:
    """A short sentence that says something about the row.

    Deliberately generic in wording — the seeder cannot know the domain — but
    it reads as a sentence rather than as a column name, which is the point.
    """
    subject = (_humanish(entity) or "record").lower()
    # No row numbers: a sentence that cites its own index is the schema dump
    # again in longer form. Variety comes from the index picking the sentence,
    # not from the index appearing inside it.
    openers = (
        "Updated and awaiting review.",
        f"Routine {subject} activity recorded.",
        "Completed without issues.",
        "Follow-up has been scheduled.",
        "Progressing normally.",
        "Submitted and queued for approval.",
        f"Reassigned to a different {subject} owner.",
        "Approved by the reviewing manager.",
        "Returned with a request for more detail.",
        "Closed after the scheduled check.",
    )
    return openers[i % len(openers)]


def _humanish(token: str) -> str:
    spaced = re.sub(r"[_\-]+", " ", token or "")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    return " ".join(w.capitalize() for w in spaced.split())


def value_for_role(role: str | None, column: str, entity: str, i: int):
    """The seeded value for a recognised role, or None to keep the old default."""
    if role == "person":
        return person_name(i)
    if role == "place":
        return place_name(i)
    if role == "code":
        return reference_code(entity, i)
    if role == "prose":
        return sentence_for(column, entity, i)
    if role == "label":
        # May decline: an unknown domain has no vocabulary we can honestly
        # supply, and the caller's fallback is better than an invented word.
        return label_value(column, entity, i)
    return None


# ── label vocabulary ─────────────────────────────────────────────────────
# A label column names a thing the domain already has words for. "Department 1"
# is the column name wearing a row's clothes; "Engineering" is a department.
#
# Only concepts we actually know get an entry. An unknown concept returns None
# and the caller keeps its own fallback — inventing vocabulary for a domain we
# cannot read produces rows that sound authoritative and mean nothing.

_LEXICON: dict[str, list[str]] = {
    "department": ["Engineering", "Marketing", "Finance", "Operations",
                   "People", "Sales", "Legal", "Customer Support",
                   "Product", "Facilities"],
    "team": ["Platform", "Growth", "Design", "Data", "Infrastructure",
             "Quality", "Research", "Mobile", "Security", "Billing"],
    "role": ["Administrator", "Manager", "Team Lead", "Analyst",
             "Coordinator", "Specialist", "Reviewer", "Approver",
             "Contributor", "Observer"],
    "priority": ["Critical", "High", "Medium", "Low", "Deferred"],
    "status": ["Draft", "Submitted", "In Review", "Approved", "Rejected",
               "Cancelled", "Completed"],
    "leave_type": ["Annual Leave", "Sick Leave", "Parental Leave",
                   "Unpaid Leave", "Compassionate Leave", "Study Leave",
                   "Sabbatical", "Public Holiday", "Time Off in Lieu",
                   "Jury Service"],
    "expense_type": ["Travel", "Accommodation", "Meals", "Equipment",
                     "Software", "Training", "Client Entertainment",
                     "Mileage", "Office Supplies", "Conference"],
    "document_type": ["Contract", "Invoice", "Policy", "Report",
                      "Certificate", "Statement", "Agreement", "Receipt",
                      "Proposal", "Handbook"],
    # Generic `<X>Type` / `<X>Category` — real type names in shape, no
    # pretence of knowing what X is.
    "type": ["Standard", "Expedited", "Provisional", "Recurring",
             "One-off", "Internal", "External", "Seasonal",
             "Emergency", "Scheduled"],
    "category": ["General", "Operational", "Financial", "Technical",
                 "Administrative", "Compliance", "Commercial",
                 "Environmental", "Strategic", "Regulatory"],
}

# Entity name (normalised) -> lexicon key. Ordered longest-first at lookup so
# `LeaveType` picks leave_type, not the generic type.
_CONCEPTS: dict[str, str] = {
    "department": "department", "division": "department", "unit": "department",
    "team": "team", "squad": "team", "crew": "team",
    "role": "role", "position": "role", "jobtitle": "role",
    "priority": "priority", "severity": "priority",
    "status": "status", "state": "status", "stage": "status",
    "leavetype": "leave_type", "absencetype": "leave_type",
    "expensetype": "expense_type", "costtype": "expense_type",
    "documenttype": "document_type", "filetype": "document_type",
    "type": "type", "kind": "type",
    "category": "category", "classification": "category",
}


def _concept(entity: str) -> str | None:
    norm = re.sub(r"[^a-z]", "", (entity or "").lower())
    if not norm:
        return None
    # Longest key first: `leavetype` must beat the `type` suffix.
    for key in sorted(_CONCEPTS, key=len, reverse=True):
        if norm == key or norm.endswith(key):
            return _CONCEPTS[key]
    return None


def label_value(column: str, entity: str, i: int) -> str | None:
    """A domain word for a label column, or None when we don't know the domain.

    Distinct per index even past the end of the word list, because a label
    column is often `.unique()` and a duplicate fails the insert — which would
    trade unreadable rows for missing ones.
    """
    # The concept can live in either name: `LeaveType.name` is a leave type,
    # `Notification.type` is a type. The column is more specific, so it wins.
    concept = _concept(column) or _concept(entity)
    if not concept:
        return None
    words = _LEXICON[concept]
    if i < len(words):
        return words[i]
    # Past the list: cycle, and disambiguate with the lap number.
    return f"{words[i % len(words)]} {i // len(words) + 1}"
