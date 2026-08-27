"""Background job worker using asyncio task queue.

Uses Redis-backed simple job queue. For production at scale, swap for
arq, celery, or a managed queue service.
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Any

from cache import get_redis

logger = logging.getLogger(__name__)

# Job registry
_job_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}


def register_job(name: str):
    """Decorator to register a background job handler."""
    def decorator(func: Callable[..., Awaitable[Any]]):
        _job_handlers[name] = func
        return func
    return decorator


async def enqueue_job(
    job_type: str,
    payload: dict,
    job_id: str | None = None,
) -> str:
    """Enqueue a background job. Returns the job ID."""
    job_id = job_id or str(uuid.uuid4())

    job_data = {
        "id": job_id,
        "type": job_type,
        "payload": payload,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    r = await get_redis()
    if r:
        # Push to Redis queue
        await r.rpush("tentoroforge:jobs", json.dumps(job_data))
        await r.set(f"tentoroforge:job:{job_id}", json.dumps(job_data), ex=86400)
        logger.info("Enqueued job %s (type=%s)", job_id, job_type)
    else:
        # No Redis — execute inline as a background asyncio task
        logger.info("No Redis — executing job %s inline", job_id)
        handler = _job_handlers.get(job_type)
        if handler:
            asyncio.create_task(_execute_job(job_data, handler))

    return job_id


async def get_job_status(job_id: str) -> dict | None:
    """Get the current status of a job."""
    r = await get_redis()
    if not r:
        return None
    raw = await r.get(f"tentoroforge:job:{job_id}")
    if raw:
        return json.loads(raw)
    return None


async def _execute_job(job_data: dict, handler: Callable) -> None:
    """Execute a job and update its status."""
    job_id = job_data["id"]
    r = await get_redis()

    try:
        job_data["status"] = "running"
        job_data["started_at"] = datetime.now(timezone.utc).isoformat()
        if r:
            await r.set(f"tentoroforge:job:{job_id}", json.dumps(job_data), ex=86400)

        result = await handler(**job_data["payload"])

        job_data["status"] = "completed"
        job_data["result"] = result
        job_data["completed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        job_data["status"] = "failed"
        job_data["error"] = str(e)
        job_data["completed_at"] = datetime.now(timezone.utc).isoformat()

    if r:
        await r.set(f"tentoroforge:job:{job_id}", json.dumps(job_data), ex=86400)


async def run_worker():
    """Run the background worker loop — pops jobs from Redis and executes them."""
    logger.info("Starting background worker...")
    r = await get_redis()
    if not r:
        logger.error("Worker requires Redis — exiting")
        return

    while True:
        try:
            raw = await r.blpop("tentoroforge:jobs", timeout=5)
            if not raw:
                continue

            job_data = json.loads(raw[1])
            job_type = job_data["type"]
            handler = _job_handlers.get(job_type)

            if not handler:
                logger.warning("Unknown job type: %s", job_type)
                continue

            await _execute_job(job_data, handler)

        except asyncio.CancelledError:
            logger.info("Worker shutting down")
            break
        except Exception:
            logger.exception("Worker error")
            await asyncio.sleep(1)
