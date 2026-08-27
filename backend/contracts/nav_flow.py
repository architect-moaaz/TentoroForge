"""nav-flow.json artifact: routes, initial page, transitions, guards."""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class NavFlowPageEntry(BaseModel):
    id: str = Field(..., description="Stable id referenced by transitions + links")
    route: str = Field(..., description='Next.js route pattern, e.g. "/users/[id]"')
    title: str
    schema_file: str = Field(..., alias="schemaFile",
                             description="Path relative to project root")
    layout: Optional[str] = None
    guard: Optional[str] = Field(None, description="Name of a guard in NavFlow.guards")
    params: Optional[list[str]] = Field(default_factory=list,
                                        description="Dynamic-segment param names")
    shell: bool = Field(
        True,
        description=(
            "When True (default), this route renders inside the app shell. "
            "Set to False for auth-style pages (login, signup, etc.) that "
            "should render bare with no nav chrome."
        ),
    )

    class Config:
        populate_by_name = True


class NavFlowTransition(BaseModel):
    id: str
    from_page: str = Field(..., alias="from")
    trigger: str
    to: str
    params: Optional[dict] = None

    class Config:
        populate_by_name = True


class NavFlowGuard(BaseModel):
    redirect_to: str = Field(..., alias="redirectTo")
    condition: str = Field(..., description="Expression evaluated against context")

    class Config:
        populate_by_name = True


class NavFlow(BaseModel):
    version: str = "1.0"
    initial_page: str = Field(..., alias="initialPage")
    pages: list[NavFlowPageEntry]
    transitions: list[NavFlowTransition] = Field(default_factory=list)
    guards: dict[str, NavFlowGuard] = Field(default_factory=dict)
    auth_routes: list[str] = Field(
        default_factory=list,
        description="Routes that bypass the app shell. Derived from pages[].shell == False. "
                    "Emitted snake_case (the render scaffold reads nav_flow.auth_routes).",
    )
    post_login_redirect: Optional[str] = Field(
        None,
        description="After auth.signIn / auth.signUp, navigate here.",
    )
    post_logout_redirect: Optional[str] = Field(
        None,
        description="After auth.signOut, navigate here.",
    )
    auth_gated: bool = Field(
        False,
        alias="authGated",
        description="Whether the app requires authentication. Drives the entry "
                    "point (/login when true, / when false) and the scaffold gate.",
    )

    class Config:
        populate_by_name = True


def empty_nav_flow() -> NavFlow:
    return NavFlow(initial_page="", pages=[], transitions=[], guards={})
