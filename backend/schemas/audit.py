"""Pydantic schemas for audit log."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: str | None
    changes: dict | None
    ip_address: str | None
    request_id: str | None
    timestamp: datetime

    model_config = {"from_attributes": True}
