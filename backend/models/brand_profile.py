"""What a company is and what it looks like — discovered once, held by the org.

A person signing up for Forge is signing up on behalf of a company that
already exists: it has a website, a name, a mark, a palette somebody chose,
and a sentence it uses to say what it does. Every application built here is
built for that company, and until now each one re-invented all of it from a
chat message — a different blue each time, a product description the model
wrote from the brief alone.

WHY THE ORGANISATION OWNS IT, not the user and not the project. §22 makes the
organisation the root entity: people, roles and projects all hang off it, and
a design language is the same kind of fact. The second person to join a
company should not be asked what the company looks like, and the fifth app
should not have to be told again.

WHY BOTH A STRUCTURE AND A DOCUMENT. `identity` and `design` are read by code
— the projection writes `designSystem` colour roles from `design`, and the
question Smith asks names `company_name`. `design_md` is read by models: it is
the same facts written as the prose a designer would have been handed, and it
reaches the agents as an addendum the way a supplied specification does
(`services.blueprint.brand_language`). Generated from the structure, never
typed beside it, so the two cannot disagree: an edit to the structure
regenerates the document in the same call.

ONE PER ORGANISATION, and it may be absent. Discovery is optional at signup
(§25 — the gate invites, it does not block), so most of the states this
carries are "not yet": `skipped` is a person who said not now and can finish
it from Settings, `failed` is a site that could not be read, and no row at all
is an organisation created before any of this existed. Every one of those
means the same thing to a build — there is no company design language to
offer — and the application-level question is simply not asked.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class BrandDiscoveryStatus(str, PyEnum):
    """Where the discovery got to.

    `skipped` is deliberately a state rather than the absence of a row: it is
    the difference between "they were asked and said not now" — which Settings
    shows as an unfinished thing they can pick up — and "nobody has ever been
    asked", which is every organisation that predates this.
    """

    pending = "pending"        # a row exists, nothing read yet
    extracting = "extracting"  # a read is in flight
    ready = "ready"            # there is a design language to offer
    failed = "failed"          # the site could not be read; the reason is kept
    skipped = "skipped"        # asked, declined, resumable from Settings


class OrgBrandProfile(Base):
    __tablename__ = "org_brand_profiles"
    __table_args__ = (
        UniqueConstraint("org_id", name="uq_brand_profile_org"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Who ran it. Kept for the audit trail only — the profile belongs to the
    # organisation, so this user leaving does not take the company's design
    # language with them, which is why it is SET NULL rather than CASCADE.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL")
    )
    status: Mapped[BrandDiscoveryStatus] = mapped_column(
        Enum(BrandDiscoveryStatus, name="brand_discovery_status"),
        default=BrandDiscoveryStatus.pending,
        nullable=False,
    )
    #: The URL the person gave, exactly as they gave it. Kept so Settings can
    #: offer to read it again when a company redesigns.
    source_url: Mapped[str | None] = mapped_column(String(500))
    #: Why a `failed` run failed, in words meant to be shown to the person.
    failure_reason: Mapped[str | None] = mapped_column(Text)

    company_name: Mapped[str | None] = mapped_column(String(255))
    #: Path under the platform's brand store, not a URL into someone else's
    #: site: a mark served from the company's CDN is a mark that disappears
    #: from every generated app the day they move it.
    logo_path: Mapped[str | None] = mapped_column(String(500))

    #: WHO YOU ARE, WHAT YOU DO, HOW YOU DO IT — the three discovery answers,
    #: plus what the reading inferred around them (industry, audience, tone).
    #: Free-shaped on purpose: this is evidence for a model to read, and a
    #: column per question would need a migration every time the interview
    #: changes. The keys the code depends on are documented in
    #: `services.brand_discovery.profile`.
    identity: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    #: THE DESIGN LANGUAGE, in the shape `designSystem` uses — `colors`,
    #: `typography`, `spacing`, `radius`, `elevation`, `visualPersonality`,
    #: `informationDensity`. Same shape deliberately: the projection into a
    #: Blueprint is then a merge rather than a translation, and a translation
    #: is where a colour role quietly becomes a different one.
    design: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    #: The design.md the generation process reads. Generated from `identity`
    #: and `design`; never authored independently of them.
    design_md: Mapped[str | None] = mapped_column(Text)

    #: What the read actually saw — the page title, the og:image URL, the
    #: colour census, the fonts, the screenshot's path. Kept so a person can
    #: see why a colour was chosen and so a re-run can be compared against the
    #: last one rather than silently replacing it.
    evidence: Mapped[dict | None] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped["Organization"] = relationship("Organization")

    def __repr__(self) -> str:
        return f"<OrgBrandProfile org={self.org_id} {self.status}>"

    @property
    def usable(self) -> bool:
        """Whether there is a design language here to offer an application.

        `ready` alone is not enough: a profile whose extraction found nothing
        it could name a colour from is ready and empty, and offering "use your
        company's design language" for an empty one asks the user to choose
        between a design and nothing.
        """
        if self.status != BrandDiscoveryStatus.ready:
            return False
        design = self.design or {}
        return bool(design.get("colors") or design.get("typography"))
