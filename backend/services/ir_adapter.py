"""IR Adapter — converts planner output (plan JSON) to AppSpec for the pattern library.

The planner already identifies entities, fields, relationships, pages, and capabilities.
This adapter normalizes the format to what @tentoroforge/patterns expects.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field type mapping: plan schema types → IR field types
# ---------------------------------------------------------------------------

FIELD_TYPE_MAP = {
    # String types
    "String": "string",
    "string": "string",
    "Text": "text",
    "text": "text",
    "VARCHAR": "string",
    # Number types
    "Int": "number",
    "int": "number",
    "Integer": "number",
    "Float": "number",
    "float": "number",
    "Decimal": "number",
    "BigInt": "number",
    # Boolean
    "Boolean": "boolean",
    "boolean": "boolean",
    "bool": "boolean",
    # Date/time
    "DateTime": "datetime",
    "datetime": "datetime",
    "Date": "date",
    "date": "date",
    "Timestamp": "datetime",
    # Special
    "Email": "email",
    "email": "email",
    "Url": "url",
    "url": "url",
    "Json": "json",
    "json": "json",
    "Enum": "enum",
    "enum": "enum",
    # Files
    "Image": "image",
    "image": "image",
    "File": "file",
    "file": "file",
    "Avatar": "avatar",
    "avatar": "avatar",
}


def plan_to_app_spec(
    plan: dict[str, Any],
    app_name: str | None = None,
    domain_context: dict[str, Any] | None = None,
    figma_tokens: dict[str, Any] | None = None,
    design_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert a planner output JSON to an AppSpec dict.

    The returned dict matches the TypeScript AppSpec interface expected
    by @tentoroforge/patterns' generateApp().

    Priority for design decisions:
      1. design_spec (from LLM Design Agent) — highest priority
      2. domain_context (from static industry_design mapping) — fallback
    """
    name = app_name or plan.get("module_name", "My App")
    description = plan.get("description", "")

    entities = _convert_entities(plan)
    relationships = _convert_relationships(plan)

    spec: dict[str, Any] = {
        "name": name,
        "description": description,
        "entities": entities,
        "relationships": relationships,
    }

    if design_spec:
        # Use LLM-generated design spec (highest priority)
        spec = _apply_design_spec(spec, design_spec)
        logger.info("AppSpec enriched with LLM Design Agent output")
    elif domain_context:
        # Fall back to static industry mapping
        from services.industry_design import inject_design_into_app_spec
        domain = domain_context.get("domain", "")
        if domain:
            spec = inject_design_into_app_spec(spec, domain, figma_tokens)
            logger.info("AppSpec enriched with %s industry design (static)", domain)

    return spec


def _apply_design_spec(spec: dict[str, Any], design: dict[str, Any]) -> dict[str, Any]:
    """Apply an LLM-generated design spec to the AppSpec."""
    # Theme: map design spec colors to a custom theme
    colors = design.get("colorPalette", {})
    if colors:
        if "tokenOverrides" not in spec:
            spec["tokenOverrides"] = {}
        for key in ("primary", "secondary", "accent", "error", "warning", "success", "muted"):
            if key in colors:
                mapped = "danger" if key == "error" else key
                spec["tokenOverrides"][mapped] = colors[key]
        if colors.get("background"):
            spec["tokenOverrides"]["background"] = colors["background"]
        if colors.get("surface"):
            spec["tokenOverrides"]["surface"] = colors["surface"]

    # Layout
    layout = design.get("layout", {})
    if "userContext" not in spec:
        spec["userContext"] = {}

    if layout.get("navigation"):
        spec["userContext"]["navigation"] = layout["navigation"]

    if layout.get("density"):
        density = layout["density"]
        spec["userContext"]["priority"] = (
            "density" if density == "compact"
            else "aesthetics" if density == "spacious"
            else "speed"
        )

    if layout.get("borderRadius"):
        spec["userContext"]["borderRadius"] = layout["borderRadius"]

    if layout.get("spacing"):
        spec["userContext"]["spacing"] = layout["spacing"]

    # Dashboard widgets
    widgets = design.get("dashboardWidgets")
    if widgets:
        spec["userContext"]["dashboardWidgets"] = widgets

    # Entity-specific pattern overrides
    entity_patterns = design.get("entityPatterns", {})
    for entity in spec.get("entities", []):
        entity_name = entity.get("name", "")
        pattern = entity_patterns.get(entity_name)
        if pattern:
            if "viewOverrides" not in entity:
                entity["viewOverrides"] = {}
            entity["viewOverrides"]["browse"] = pattern

    # Typography
    typo = design.get("typography", {})
    if typo.get("fontFamily"):
        spec["userContext"]["fontFamily"] = typo["fontFamily"]

    # Component style hints
    comp_style = design.get("componentStyle", {})
    if comp_style:
        spec["userContext"]["componentStyle"] = comp_style

    return spec


# ---------------------------------------------------------------------------
# Entity conversion
# ---------------------------------------------------------------------------

def _convert_entities(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert plan data_models to EntitySpec[].

    Infers capabilities from plan pages, api_routes, and workflows.
    """
    data_models = plan.get("data_models", [])
    api_routes = plan.get("api_routes", [])
    pages = plan.get("pages", [])
    workflows = plan.get("workflows", [])
    access_control = plan.get("access_control", {})

    entities = []
    for model in data_models:
        entity_name = model.get("name", "")
        if not entity_name:
            continue

        # Convert fields
        fields = _convert_fields(model.get("fields", []))

        # Infer capabilities from routes and pages
        capabilities = _infer_capabilities(
            entity_name, api_routes, pages, workflows
        )

        # Convert relations (field-level)
        relations = _convert_field_relations(model.get("fields", []), entity_name)

        entity: dict[str, Any] = {
            "name": entity_name,
            "fields": fields,
            "capabilities": capabilities,
        }
        if relations:
            entity["relations"] = relations

        entities.append(entity)

    return entities


def _convert_fields(plan_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert plan field definitions to FieldSpec[]."""
    fields = []
    for pf in plan_fields:
        name = pf.get("name", "")
        if not name:
            continue

        raw_type = pf.get("type", "String")
        # Handle enum type
        is_enum = raw_type.lower() == "enum" or bool(pf.get("enum_values"))
        field_type = "enum" if is_enum else FIELD_TYPE_MAP.get(raw_type, "string")

        field: dict[str, Any] = {
            "name": name,
            "type": field_type,
        }

        if pf.get("primaryKey"):
            # Skip primary keys — IR handles them implicitly
            continue

        if pf.get("nullable") is False:
            field["required"] = True

        if is_enum and pf.get("enum_values"):
            field["values"] = pf["enum_values"]

        # Detect relation fields
        if name.endswith("_id") or name.endswith("Id"):
            # Likely a foreign key
            target = name.replace("_id", "").replace("Id", "")
            target = target[0].upper() + target[1:]  # capitalize
            field["type"] = "relation"
            field["relationTo"] = target

        # Detect special fields by name
        lower_name = name.lower()
        if "email" in lower_name and field_type == "string":
            field["type"] = "email"
        elif "avatar" in lower_name or "profile_image" in lower_name:
            field["type"] = "avatar"
            field["isIdentityImage"] = True
        elif "image" in lower_name or "thumbnail" in lower_name or "photo" in lower_name:
            field["type"] = "image"
            field["isIdentityImage"] = True
        elif "phone" in lower_name or "tel" in lower_name:
            field["type"] = "tel"
        elif "url" in lower_name or "website" in lower_name:
            field["type"] = "url"
        elif "description" in lower_name or "body" in lower_name or "content" in lower_name:
            if field_type == "string":
                field["type"] = "text"
        elif "bio" in lower_name or "notes" in lower_name:
            if field_type == "string":
                field["type"] = "text"

        # Searchable / sortable / filterable heuristics
        if field_type == "string" and "name" in lower_name or "title" in lower_name:
            field["searchable"] = True
            field["sortable"] = True
        if field_type == "enum":
            field["filterable"] = True
        if field_type in ("date", "datetime"):
            field["sortable"] = True

        fields.append(field)

    return fields


def _convert_field_relations(
    plan_fields: list[dict[str, Any]], entity_name: str
) -> list[dict[str, Any]]:
    """Extract relation specs from fields that end in _id/Id."""
    relations = []
    for pf in plan_fields:
        name = pf.get("name", "")
        if name.endswith("_id") or name.endswith("Id"):
            target = name.replace("_id", "").replace("Id", "")
            target = target[0].upper() + target[1:]
            relations.append({
                "from": name,
                "to": target,
                "type": "many-to-one",
            })
    return relations


# ---------------------------------------------------------------------------
# Capability inference
# ---------------------------------------------------------------------------

def _infer_capabilities(
    entity_name: str,
    api_routes: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    workflows: list[dict[str, Any]],
) -> list[str]:
    """Infer entity capabilities from API routes and pages."""
    caps: set[str] = set()
    entity_lower = entity_name.lower()

    # From API routes
    for route in api_routes:
        path = route.get("path", "").lower()
        method = route.get("method", "").upper()
        route_entity = (route.get("entity") or "").lower()

        if route_entity == entity_lower or entity_lower in path:
            if method == "GET" and "{id}" not in path and "[id]" not in path:
                caps.add("list")
                caps.add("search")
                caps.add("filter")
            elif method == "GET":
                caps.add("detail")
            elif method == "POST":
                caps.add("create")
            elif method in ("PUT", "PATCH"):
                caps.add("edit")
            elif method == "DELETE":
                caps.add("delete")

    # From pages
    for page in pages:
        page_name = (page.get("name") or "").lower()
        page_desc = (page.get("description") or "").lower()
        if entity_lower in page_name or entity_lower in page_desc:
            caps.add("list")
            if "detail" in page_name or "detail" in page_desc:
                caps.add("detail")
            if "create" in page_name or "new" in page_name or "add" in page_name:
                caps.add("create")

    # From workflows
    for wf in workflows:
        wf_desc = (wf.get("description") or "").lower()
        if entity_lower in wf_desc:
            caps.add("activity-log")

    # Default minimums
    if not caps:
        caps = {"list", "search", "create", "detail"}

    return sorted(caps)


# ---------------------------------------------------------------------------
# Relationship conversion
# ---------------------------------------------------------------------------

def _convert_relationships(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert plan relations to RelationSpec[]."""
    relations = plan.get("relations", [])
    result = []
    for rel in relations:
        result.append({
            "from": rel.get("foreignKey", ""),
            "to": rel.get("to", ""),
            "type": rel.get("type", "many-to-one"),
        })
    return result
