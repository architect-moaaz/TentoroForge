"""Module lifecycle service — create, update, delete, dependency tracking."""

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.project import (
    Module,
    ModuleDependency,
    ModuleFile,
    DependencyType,
    ModuleFileType,
)


def _slugify(name: str) -> str:
    """Convert a module name to a URL-friendly slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "module"


async def create_module(
    project_id: uuid.UUID,
    name: str,
    description: str | None,
    dependency_ids: list[uuid.UUID],
    db: AsyncSession,
) -> Module:
    """Create a module and optionally link initial dependencies."""
    slug = _slugify(name)

    # Ensure slug uniqueness within project
    existing = await db.execute(
        select(Module).where(
            Module.project_id == project_id,
            Module.slug == slug,
        )
    )
    if existing.scalar_one_or_none():
        # Append a short suffix
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    module = Module(
        project_id=project_id,
        name=name,
        slug=slug,
        description=description,
    )
    db.add(module)
    await db.flush()

    # Add initial dependencies
    for dep_id in dependency_ids:
        dep_module = await db.execute(
            select(Module).where(
                Module.id == dep_id,
                Module.project_id == project_id,
            )
        )
        if dep_module.scalar_one_or_none():
            db.add(ModuleDependency(
                module_id=module.id,
                depends_on_id=dep_id,
                dependency_type=DependencyType.uses,
            ))

    await db.flush()
    await db.refresh(module)
    return module


async def get_module(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    db: AsyncSession,
) -> Module:
    """Fetch a single module with dependencies and files eagerly loaded."""
    result = await db.execute(
        select(Module)
        .options(
            selectinload(Module.dependencies),
            selectinload(Module.files),
        )
        .where(
            Module.id == module_id,
            Module.project_id == project_id,
        )
    )
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    return module


async def list_modules(
    project_id: uuid.UUID,
    db: AsyncSession,
) -> list[Module]:
    """List all modules for a project, ordered by creation time."""
    result = await db.execute(
        select(Module)
        .where(Module.project_id == project_id)
        .order_by(Module.created_at)
    )
    return list(result.scalars().all())


async def update_module(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    updates: dict,
    db: AsyncSession,
) -> Module:
    """Update module fields (name, description)."""
    module = await get_module(project_id, module_id, db)

    for field, value in updates.items():
        if field == "name" and value:
            setattr(module, "name", value)
            setattr(module, "slug", _slugify(value))
        elif field == "description":
            setattr(module, "description", value)

    await db.flush()
    await db.refresh(module)
    return module


async def delete_module(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Delete a module and cascade its dependencies/files."""
    module = await get_module(project_id, module_id, db)

    # Also remove any dependency edges pointing TO this module
    await db.execute(
        delete(ModuleDependency).where(
            ModuleDependency.depends_on_id == module_id
        )
    )

    await db.delete(module)
    await db.flush()


async def get_dependencies(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    db: AsyncSession,
) -> list[ModuleDependency]:
    """Get all dependencies for a module."""
    # Verify module exists
    await get_module(project_id, module_id, db)

    result = await db.execute(
        select(ModuleDependency).where(
            ModuleDependency.module_id == module_id
        )
    )
    return list(result.scalars().all())


async def update_dependencies(
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    deps: list[dict],
    db: AsyncSession,
) -> list[ModuleDependency]:
    """Replace all dependencies for a module."""
    # Verify module exists
    await get_module(project_id, module_id, db)

    # Remove existing dependencies
    await db.execute(
        delete(ModuleDependency).where(
            ModuleDependency.module_id == module_id
        )
    )

    # Add new dependencies
    new_deps = []
    for dep in deps:
        dep_id = dep["depends_on_id"]
        dep_type_str = dep.get("dependency_type", "uses")

        # Validate target module exists in same project
        target = await db.execute(
            select(Module).where(
                Module.id == dep_id,
                Module.project_id == project_id,
            )
        )
        if not target.scalar_one_or_none():
            continue

        # Prevent self-dependency
        if dep_id == module_id:
            continue

        try:
            dep_type = DependencyType(dep_type_str)
        except ValueError:
            dep_type = DependencyType.uses

        mod_dep = ModuleDependency(
            module_id=module_id,
            depends_on_id=dep_id,
            dependency_type=dep_type,
        )
        db.add(mod_dep)
        new_deps.append(mod_dep)

    await db.flush()
    return new_deps


async def get_connections_map(
    project_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """Build a connections map with all modules as nodes and dependencies as edges."""
    # Get all modules with file counts
    modules_result = await db.execute(
        select(Module)
        .where(Module.project_id == project_id)
        .order_by(Module.created_at)
    )
    modules = list(modules_result.scalars().all())

    # Get file counts per module
    file_counts_result = await db.execute(
        select(ModuleFile.module_id, func.count(ModuleFile.id))
        .where(ModuleFile.module_id.in_([m.id for m in modules]))
        .group_by(ModuleFile.module_id)
    )
    file_counts = dict(file_counts_result.all())

    # Get all dependencies across project modules
    module_ids = [m.id for m in modules]
    deps_result = await db.execute(
        select(ModuleDependency).where(
            ModuleDependency.module_id.in_(module_ids)
        )
    )
    deps = list(deps_result.scalars().all())

    nodes = [
        {
            "id": m.id,
            "name": m.name,
            "slug": m.slug,
            "file_count": file_counts.get(m.id, 0),
        }
        for m in modules
    ]

    edges = [
        {
            "id": d.id,
            "source_module_id": d.module_id,
            "target_module_id": d.depends_on_id,
            "dependency_type": d.dependency_type.value if hasattr(d.dependency_type, "value") else str(d.dependency_type),
        }
        for d in deps
    ]

    return {"nodes": nodes, "edges": edges}
