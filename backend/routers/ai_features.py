"""AI Features endpoints — configuration for smart fields, semantic search, AI components."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from schemas.ai_features import (
    AIConfigSave,
    SemanticSearchConfigSave,
    AIComponentConfigSave,
    SmartFieldTestRequest,
    ScheduledAIConfigSave,
)
from services.project_service import get_project_with_auth

router = APIRouter(tags=["ai-features"])

AI_CONFIG_DIR = "ai-config"  # relative to project output_dir


def _ai_config_path(output_dir: str) -> Path:
    p = Path(output_dir) / AI_CONFIG_DIR
    p.mkdir(exist_ok=True)
    return p


def _read_config(output_dir: str) -> dict:
    """Read the full AI config from the project."""
    config_file = _ai_config_path(output_dir) / "config.json"
    if config_file.exists():
        return json.loads(config_file.read_text(encoding="utf-8"))
    return {
        "config": {
            "provider": "anthropic",
            "primaryModel": "claude-haiku-4-5-20251001",
            "embeddingModel": "text-embedding-3-small",
            "costTrackingEnabled": True,
            "monthlyBudget": 50,
        },
        "semanticSearch": [],
        "aiComponents": [],
        "scheduledAI": [],
    }


def _write_config(output_dir: str, data: dict) -> None:
    config_file = _ai_config_path(output_dir) / "config.json"
    config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# AI Configuration (global settings)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/ai-config")
async def get_ai_config(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the AI features configuration for a project."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return _read_config("")
    return _read_config(project.output_dir)


@router.put("/api/projects/{project_id}/ai-config")
async def update_ai_config(
    project_id: uuid.UUID,
    req: AIConfigSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the AI features configuration."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    data["config"] = req.model_dump()
    _write_config(project.output_dir, data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Semantic Search configs
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/ai-config/semantic-search")
async def list_semantic_search(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List semantic search configurations."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []
    data = _read_config(project.output_dir)
    return data.get("semanticSearch", [])


@router.post("/api/projects/{project_id}/ai-config/semantic-search", status_code=201)
async def add_semantic_search(
    project_id: uuid.UUID,
    req: SemanticSearchConfigSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a semantic search configuration for a model."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    ss_list = data.get("semanticSearch", [])
    # Replace if same model exists
    ss_list = [s for s in ss_list if s.get("model") != req.model]
    ss_list.append(req.model_dump())
    data["semanticSearch"] = ss_list
    _write_config(project.output_dir, data)
    return req.model_dump()


@router.delete("/api/projects/{project_id}/ai-config/semantic-search/{model_name}")
async def delete_semantic_search(
    project_id: uuid.UUID,
    model_name: str,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete semantic search config for a model."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    data["semanticSearch"] = [
        s for s in data.get("semanticSearch", []) if s.get("model") != model_name
    ]
    _write_config(project.output_dir, data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AI Components
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/ai-config/components")
async def list_ai_components(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List AI component configurations."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []
    data = _read_config(project.output_dir)
    return data.get("aiComponents", [])


@router.post("/api/projects/{project_id}/ai-config/components", status_code=201)
async def add_ai_component(
    project_id: uuid.UUID,
    req: AIComponentConfigSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add an AI component configuration."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    components = data.get("aiComponents", [])
    components.append(req.model_dump())
    data["aiComponents"] = components
    _write_config(project.output_dir, data)
    return req.model_dump()


@router.delete("/api/projects/{project_id}/ai-config/components/{idx}")
async def delete_ai_component(
    project_id: uuid.UUID,
    idx: int,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an AI component by index."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    components = data.get("aiComponents", [])
    if 0 <= idx < len(components):
        components.pop(idx)
    data["aiComponents"] = components
    _write_config(project.output_dir, data)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Scheduled AI Tasks
# ---------------------------------------------------------------------------

@router.get("/api/projects/{project_id}/ai-config/scheduled")
async def list_scheduled_ai(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List scheduled AI tasks."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return []
    data = _read_config(project.output_dir)
    return data.get("scheduledAI", [])


@router.post("/api/projects/{project_id}/ai-config/scheduled", status_code=201)
async def add_scheduled_ai(
    project_id: uuid.UUID,
    req: ScheduledAIConfigSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a scheduled AI task."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    data = _read_config(project.output_dir)
    scheduled = data.get("scheduledAI", [])
    scheduled.append(req.model_dump())
    data["scheduledAI"] = scheduled
    _write_config(project.output_dir, data)
    return req.model_dump()


# ---------------------------------------------------------------------------
# Smart Field Test
# ---------------------------------------------------------------------------

@router.post("/api/projects/{project_id}/ai-config/test-smart-field")
async def test_smart_field(
    project_id: uuid.UUID,
    req: SmartFieldTestRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test a smart field configuration with sample data (simulated)."""
    await get_project_with_auth(project_id, user, db)

    smart_type = req.smartConfig.get("type", "ai_classify")
    # Return simulated results for testing
    simulated = {
        "ai_classify": "billing",
        "ai_classify_multi": ["react", "nextjs"],
        "ai_summarize": "This is an auto-generated summary of the provided text.",
        "ai_sentiment": "positive",
        "ai_extract": {"name": "John Doe", "email": "john@example.com"},
        "ai_generate": "Generated content based on the provided context.",
        "ai_translate": "Texto traducido al espa\u00f1ol.",
        "ai_score": 75,
        "ai_predict": "2026-03-15",
    }

    return {
        "output": simulated.get(smart_type, "Test output"),
        "tokens_used": 150,
        "duration_ms": 320,
        "model_used": req.smartConfig.get("model", "claude-haiku-4-5-20251001"),
        "cost_usd": 0.0003,
    }
