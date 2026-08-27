"""Project, conversation, agent job, and version models."""

import uuid
import string
import random
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    Integer,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Enum,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectStatus(str, PyEnum):
    draft = "draft"
    generating = "generating"
    ready = "ready"
    error = "error"
    archived = "archived"


class MessageRole(str, PyEnum):
    user = "user"
    assistant = "assistant"
    system = "system"


class MessageType(str, PyEnum):
    chat = "chat"
    plan = "plan"
    generation = "generation"
    error = "error"


class AgentType(str, PyEnum):
    code_generator = "code_generator"
    validator = "validator"
    indexer = "indexer"
    refinement = "refinement"
    planner = "planner"
    refiner = "refiner"
    explainer = "explainer"
    scaffolder = "scaffolder"
    code_editor = "code_editor"
    seed_generator = "seed_generator"


class AgentJobStatus(str, PyEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


def _generate_short_id(length: int = 8) -> str:
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choices(chars, k=length))


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_project_org", "org_id"),
        Index("ix_project_owner", "owner_id"),
        Index("ix_project_short_id", "short_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    short_id: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, default=_generate_short_id
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        default=ProjectStatus.draft,
    )
    output_dir: Mapped[str | None] = mapped_column(String(500))
    preview_port: Mapped[int | None] = mapped_column(Integer)
    db_port: Mapped[int | None] = mapped_column(Integer)
    # Design brief (Phase 1) — LLM-authored aesthetic contract, persisted
    # so subsequent pipeline runs + Smith turns see the same brief. Null
    # for legacy projects and while FORGE_BRIEF_AUTHOR is off.
    brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="projects")
    owner: Mapped["PlatformUser"] = relationship(back_populates="owned_projects")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="Conversation.created_at",
    )
    agent_jobs: Mapped[list["AgentJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
    )
    versions: Mapped[list["Version"]] = relationship(
        back_populates="project", cascade="all, delete-orphan",
        order_by="Version.created_at.desc()",
    )


# ---------------------------------------------------------------------------
# Enums – Modules
# ---------------------------------------------------------------------------

class DependencyType(str, PyEnum):
    uses = "uses"
    extends = "extends"
    imports = "imports"


class ModuleFileType(str, PyEnum):
    page = "page"
    component = "component"
    api = "api"
    model = "model"
    service = "service"
    hook = "hook"
    util = "util"
    config = "config"
    style = "style"
    test = "test"
    other = "other"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

class Module(Base):
    __tablename__ = "modules"
    __table_args__ = (
        Index("ix_module_project", "project_id"),
        Index("ix_module_slug", "project_id", "slug", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship()
    dependencies: Mapped[list["ModuleDependency"]] = relationship(
        back_populates="module", cascade="all, delete-orphan",
        foreign_keys="ModuleDependency.module_id",
    )
    files: Mapped[list["ModuleFile"]] = relationship(
        back_populates="module", cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# ModuleDependency
# ---------------------------------------------------------------------------

class ModuleDependency(Base):
    __tablename__ = "module_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    dependency_type: Mapped[DependencyType] = mapped_column(
        Enum(DependencyType, name="dependency_type"),
        default=DependencyType.uses,
    )

    # Relationships
    module: Mapped["Module"] = relationship(
        foreign_keys=[module_id], back_populates="dependencies"
    )
    depends_on: Mapped["Module"] = relationship(foreign_keys=[depends_on_id])


# ---------------------------------------------------------------------------
# ModuleFile
# ---------------------------------------------------------------------------

class ModuleFile(Base):
    __tablename__ = "module_files"
    __table_args__ = (
        Index("ix_module_file_module", "module_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[ModuleFileType] = mapped_column(
        Enum(ModuleFileType, name="module_file_type"),
        default=ModuleFileType.other,
    )

    # Relationships
    module: Mapped["Module"] = relationship(back_populates="files")


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conv_project", "project_id"),
        Index("ix_conv_created", "created_at"),
        Index("ix_conv_project_seq", "project_id", "seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role"), nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type"),
        default=MessageType.chat,
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Monotonic insertion-order key. created_at is func.now() = the transaction
    # timestamp, identical for rows written together, so it can't order the
    # transcript. This BIGINT identity (Postgres sequence default, see migration
    # cf3a91b2d7e4) gives a stable per-row order the restore endpoint sorts by.
    # Monotonic insertion-order key for stable transcript restore. TWO things
    # make this crash-proof:
    #  1. server_default (declared on the MODEL, not just the migration) — so the
    #     ORM OMITS seq from every INSERT and the Postgres sequence fills it. The
    #     10+ Conversation(...) call sites never set seq; without this the ORM
    #     sent an explicit NULL and every chat/Smith/generation write 500'd.
    #  2. nullable=True — even a hypothetical stray NULL (raw SQL, a future code
    #     path) can NEVER 500 a message write again; the restore query sorts
    #     `seq ASC NULLS LAST, created_at` so a null just sorts last.
    seq: Mapped[int | None] = mapped_column(
        BigInteger,
        server_default=text("nextval('conversations_seq_seq'::regclass)"),
        nullable=True,
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="conversations")


# ---------------------------------------------------------------------------
# AgentJob
# ---------------------------------------------------------------------------

class AgentJob(Base):
    __tablename__ = "agent_jobs"
    __table_args__ = (
        Index("ix_job_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agent_type"), nullable=False,
    )
    status: Mapped[AgentJobStatus] = mapped_column(
        Enum(AgentJobStatus, name="agent_job_status"),
        default=AgentJobStatus.pending,
    )
    instruction: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="agent_jobs")


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (
        Index("ix_version_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    commit_hash: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    agent_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_jobs.id", ondelete="SET NULL"),
    )
    files_changed: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project: Mapped["Project"] = relationship(back_populates="versions")
    agent_job: Mapped["AgentJob | None"] = relationship()
