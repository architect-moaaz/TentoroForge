"""TCommerce (ihf6pjga, forge-v3, 2026-10-05): five record types no page
declared were written into entity-access.ts with empty role lists, which the
data route reads as "no role may" — the admin got 403 reading categories,
and Smith, diagnosing the admin's failing saves, followed it. An entity no
page declares is left out, which the route reads as open to any signed-in role."""
from services.blueprint.projection import entity_access

DOC = {"roles": [{"id": "ROLE-001", "name": "Shopper"}, {"id": "ROLE-002", "name": "Admin"}],
       "data": {"entities": [{"id": "ENTITY-001", "name": "Product", "table": "products"},
                             {"id": "ENTITY-002", "name": "Category", "table": "categories"}]},
       "pages": [{"id": "PAGE-011", "route": "/admin/products", "access": "role_restricted", "users": ["ROLE-002"],
                  "data": {"primaryEntity": "ENTITY-001"}}]}


def test_a_record_type_no_page_declares_is_left_out():
    access = entity_access(DOC)
    assert "categories" not in access
    assert access["products"] == {"read": ["Admin"], "write": ["Admin"]}


# The same reading, for who may launch a process: TCommerce's published app had [] for every
# admin process, and the administrator's every save was "not available to your role".

def test_a_restricted_page_that_names_nobody_lets_the_administrator_launch_as_it_lets_them_open():
    """Since 2026-10-07 (ToroCommerce, forge-v3): such a page is the
    administrator's — never [] (nobody could run it), and never every signed-in
    customer (the admin catalogue was theirs to open and change)."""
    from services.blueprint.projection import launch_roles, role_routes
    doc = {"roles": [{"id": "ROLE-002", "name": "Admin"}],
           "pages": [{"id": "PAGE-011", "route": "/admin/products", "access": "role_restricted"},
                     {"id": "PAGE-014", "route": "/admin/orders", "access": "role_restricted", "users": ["ROLE-002"]}],
           "workflows": [{"id": "FLOW-006", "name": "Create Product", "launchedFrom": ["PAGE-011"]},
                         {"id": "FLOW-014", "name": "Update Order Status", "launchedFrom": ["PAGE-014"]}]}
    roles = launch_roles(doc)
    assert roles["FLOW-006"] == ["Admin"], "never []: nobody could run it — and not every customer"
    assert roles["FLOW-014"] == ["Admin"]
    assert [r["route"] for r in role_routes(doc)] == ["/admin/orders", "/admin/products"], \
        "the page gate reads it the same way"
    assert all(v for v in roles.values())


def test_an_unscoped_role_reads_only_what_its_permissions_let_it():
    """kkb5mzo3 (2026-11-03): Management was left unscoped on RefundCase so its
    cross-property reports counted every hotel, and the data API handed it
    every individual case — REQ-072 keeps it at aggregate level. Where a read
    permission is declared, unscoped widens what a holder sees; it is not a
    grant. Where none is declared, unscoped still grants as before."""
    doc = {"roles": [{"id": "ROLE-001", "name": "Requester", "permissions": ["PERM-009"]},
                     {"id": "ROLE-012", "name": "Management", "permissions": []},
                     {"id": "ROLE-005", "name": "Owner", "permissions": ["PERM-009"]}],
           "permissions": [{"id": "PERM-009", "name": "Read refund case", "action": "read", "subject": "ENTITY-004"}],
           "data": {"entities": [{"id": "ENTITY-004", "name": "RefundCase", "table": "refund_cases"},
                                 {"id": "ENTITY-013", "name": "AuditEvent", "table": "audit_events"}]},
           "security": {"ownershipRules": [
               {"entity": "RefundCase", "kind": "scope", "column": "propertyId", "unscopedRoles": ["Owner", "Management"]},
               {"entity": "AuditEvent", "kind": "scope", "column": "caseId", "unscopedRoles": ["Management"]}]},
           "pages": [{"id": "PAGE-002", "route": "/cases", "access": "role_restricted", "users": ["ROLE-001"],
                      "data": {"primaryEntity": "ENTITY-004"}}]}
    access = entity_access(doc)
    assert access["refund_cases"]["read"] == ["Owner", "Requester"], "Management holds no read permission"
    assert access["audit_events"]["read"] == ["Management"], "no read permission declared: unscoped still grants"
