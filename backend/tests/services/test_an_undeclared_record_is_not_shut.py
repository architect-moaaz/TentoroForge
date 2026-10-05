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
