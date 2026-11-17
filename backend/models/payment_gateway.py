"""The payment gateways an organisation takes money through — set up once in
Settings → Payments, chosen per application.

One row per connected account (a Razorpay account for India, a Stripe account
for everyone else, a PayPal business account). Each holds two sets of keys,
encrypted at rest (`services.platform_integrations_crypto`, a subkey per row
and mode): **test** for previews and the test version, **live** for
production. Values never leave the platform except into the environment of an
application that chose the gateway, and live values only into production.

`payment_gateway_webhooks` is where each application's webhook at each
gateway is kept: the address registered, the gateway's id for it, and the
signing secret (encrypted), so a publish registers it once and every later
publish reuses it.

Spec: docs/PAYMENT-GATEWAYS-PLAN.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PaymentGateway(Base):
    __tablename__ = "payment_gateways"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    #: stripe | razorpay | paypal (`services.payments.providers.PROVIDERS`).
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    #: domestic | international | both — who it takes money from.
    coverage: Mapped[str] = mapped_column(String(16), nullable=False, default="both")
    #: ISO 3166-1 alpha-2: where "domestic" is.
    home_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    #: ISO 4217 codes it is used for.
    currencies: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Each mode's keys: one JSON object, encrypted. Null = not set.
    test_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    test_iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: What each verification found, per mode: {ok, account, accountId, country,
    #: currency, checkedAt, error, hint}. Never a secret.
    checks: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    #: Removed from Settings. Kept so an application that chose it can say
    #: which gateway it was and that it is gone.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentGatewayWebhook(Base):
    __tablename__ = "payment_gateway_webhooks"
    __table_args__ = (
        UniqueConstraint("gateway_id", "project_id", "side", name="uq_payment_gateway_webhooks_gateway_project_side"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gateway_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_gateways.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    #: test | production
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    #: The gateway's id for this endpoint (Stripe `we_…`, PayPal webhook id).
    provider_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    secret_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: registered (by Forge) | manual (the owner pastes it) | failed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
