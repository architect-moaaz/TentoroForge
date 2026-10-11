"""A page declared `role_restricted` names the roles that may open it, or
its author is told so at once. Nameless, the projection makes it the
administrator's — so a vendor's own Product Catalogue answered 403 to every
vendor (ECom L4, 7ttp60zi, 2026-10-11) and nothing in the build said why."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InconsistentPageAccess, check_page_access

DOC = {"roles": [{"id": "ROLE-001", "name": "Shopper"}, {"id": "ROLE-002", "name": "Vendor"}, {"id": "ROLE-003", "name": "Admin"}],
       "modules": [{"id": "MODULE-001", "name": "Vendor"}], "pages": []}


def _pages(*bodies):
    return AgentResult(task_id="t", agent="page_design",
                       proposals=[ArtifactProposal(section="pages", natural_key=b["route"], body=b) for b in bodies])


def test_a_restricted_page_with_no_roles_is_refused_with_what_to_write():
    with pytest.raises(InconsistentPageAccess) as exc:
        check_page_access(_pages({"name": "Product Catalogue", "route": "/vendor/products", "purpose": "list",
                                  "module": "MODULE-001", "access": "role_restricted", "users": []}), DOC)
    assert "/vendor/products: `access: \"role_restricted\"` names no role" in str(exc.value)
    assert "put the roles that may open it in `users`" in str(exc.value)


def test_a_restricted_page_that_names_its_roles_passes():
    check_page_access(_pages({"name": "Product Catalogue", "route": "/vendor/products", "purpose": "list",
                              "module": "MODULE-001", "access": "role_restricted", "users": ["ROLE-002"]}), DOC)
