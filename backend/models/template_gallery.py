"""What happens TO a template: its review, the projects made from it, and
what people thought of it.

What a template IS — its definition, logo and screenshots — stays on disk
beside it (`services.project_templates`); these rows are the parts many people
write at once, across organisations, and that are counted and sorted on: a
review decision, a use, a rating. See `services.template_gallery`.

A template saved before the Gallery existed, or by Smith from inside a chat
turn, has no listing row until it is first submitted, and reads as a draft.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class TemplateListing(Base):
    """A template's place in the review queue and the Gallery."""

    __tablename__ = "template_listings"
    __table_args__ = (
        Index("ix_template_listings_status", "status"),
        Index("ix_template_listings_org", "org_id"),
        Index("ix_template_listings_lineage", "lineage"),
    )

    #: The template's on-disk id (32 hex characters).
    template_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    #: Not a foreign key: the app a template came from may be deleted, and the
    #: template — a copy — lives on.
    source_project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    #: Every version of one app's template shares it: ``<org>:<source project>``.
    lineage: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: draft | pending | approved | rejected | removed | superseded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    #: free | paid. Only free can be chosen today; the amount is kept for when
    #: paid templates are sold.
    pricing_model: Mapped[str] = mapped_column(String(8), nullable=False, default="free")
    price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    #: The admin's words with the last decision — required when changes are asked for.
    review_note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TemplateEvent(Base):
    """One step of a template's review, for the history its requester reads."""

    __tablename__ = "template_events"
    __table_args__ = (Index("ix_template_events_template", "template_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("template_listings.template_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateUse(Base):
    """A project made from a template — once per project, kept when the
    template is deleted (it happened)."""

    __tablename__ = "template_uses"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_template_uses_project"),
        Index("ix_template_uses_lineage", "lineage"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    lineage: Mapped[str] = mapped_column(String(80), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"))
    org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    #: An admin's test copy during review: kept, never counted as a use.
    is_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                            server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TemplateReview(Base):
    """A person's rating of a template, and what they said. One per person per
    template lineage: rating it again changes their review."""

    __tablename__ = "template_reviews"
    __table_args__ = (
        UniqueConstraint("lineage", "user_id", name="uq_template_reviews_lineage_user"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_template_reviews_rating"),
        Index("ix_template_reviews_lineage", "lineage", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lineage: Mapped[str] = mapped_column(String(80), nullable=False)
    #: The version they were looking at when they last rated it.
    template_id: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
