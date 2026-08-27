"""App template model for pre-built application templates."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AppTemplate(Base):
    __tablename__ = "app_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50))
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    plan: Mapped[dict | None] = mapped_column(JSONB)
    complexity: Mapped[str | None] = mapped_column(String(20))  # simple, moderate, complex
    relevant_departments: Mapped[list | None] = mapped_column(JSONB, default=list)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
