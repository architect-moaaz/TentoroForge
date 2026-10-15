"""Platform user model — developers who use the builder tool."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

#: The one platform-wide role. A person with it runs the cockpit: every
#: login, organisation, app and credit on the platform. Granted by another
#: super admin, or at sign-in to an email the platform's configuration names.
SUPER_ADMIN = "super_admin"


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[str | None] = mapped_column(String(50), default="local")
    external_id: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    platform_role: Mapped[str | None] = mapped_column(String(32), index=True)
    # A DISABLED LOGIN IS REFUSED ON ITS NEXT REQUEST. The flag is read where
    # every token is checked, so it holds across workers and needs no
    # blacklist; the reason and the hand that set it are kept for the record.
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(Text)
    disabled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    org_memberships: Mapped[list["OrgMember"]] = relationship(
        "OrgMember", back_populates="user", cascade="all, delete-orphan"
    )
    owned_projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="owner", cascade="all, delete-orphan"
    )

    @property
    def is_super_admin(self) -> bool:
        return self.platform_role == SUPER_ADMIN

    @property
    def is_disabled(self) -> bool:
        return self.disabled_at is not None

    def __repr__(self) -> str:
        return f"<PlatformUser {self.email}>"
