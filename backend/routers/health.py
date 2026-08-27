"""Health check endpoints — liveness and readiness probes."""

from fastapi import APIRouter
from sqlalchemy import text

from database import async_session

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    """Liveness probe — returns 200 if the service is running."""
    return {"status": "ok"}


@router.get("/ready")
async def ready():
    """Readiness probe — checks database connectivity."""
    checks = {"database": False}

    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database_error"] = str(e)

    all_ready = all(v is True for v in checks.values() if isinstance(v, bool))
    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
    }
