"""Tables behind the push-and-rollup agent insights (see services/agent_insights_store.py for how they are written).

A generated app ships one event per assistant turn to the platform. The platform keeps:

* ``agent_insight_keys``      one active key per project (only the sha256 of the key is stored, never the key);
* ``agent_turn_events``       every turn as it arrived (30 days; day-partitioned on Postgres), the source of "which events did we
                              already count" and the place a rating is attached to its turn;
* rollups (minute / hour / day) counters per (project, bucket, agent, role), plus the same per model and per tool;
* ``agent_insight_users``     one row per person: first and last time seen (gives new and returning users and the live count);
* ``agent_insight_users_daily`` one row per person per agent per day with their counters (top users, and the people of one agent);
* ``agent_insight_user_days`` / ``agent_insight_active_daily`` which person was active on which day, and the per-day count of different people;
* ``agent_insight_problems``  the newest problem turns, capped per project;
* ``agent_insight_handoffs``  where each conversation's handoff stands now (the counters change only when its state does);
* ``agent_insight_pending_ratings`` a thumbs that arrived before its turn, held for an hour;
* ``agent_insight_dropped``   events turned away, per project per hour, so the page can be honest about gaps.

The big tables are plain Core tables (the writer is bulk SQL, not one ORM object per event). Keys are written first so the
leading column is always ``project_id``: a project's numbers sit together and one project can never read another's.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Table, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

# ---------------------------------------------------------------------------
# latency histogram: fixed log-scale buckets, so a percentile never needs the rows
# ---------------------------------------------------------------------------

#: Upper edge in milliseconds of each latency bucket; a reply slower than the last edge falls in one final open bucket.
#: Each edge is about 1.4 times the one before (so a percentile read from them is off by at most one such step).
LATENCY_EDGES_MS: tuple[int, ...] = (
    50, 100, 150, 200, 300, 400, 600, 800, 1_000, 1_500, 2_000, 3_000, 4_000, 6_000, 8_000, 12_000, 16_000, 24_000,
    32_000, 48_000, 64_000, 96_000, 128_000, 192_000, 300_000,
)
LATENCY_BUCKETS = len(LATENCY_EDGES_MS) + 1
LATENCY_COLUMNS: tuple[str, ...] = tuple(f"lat_{i}" for i in range(LATENCY_BUCKETS))

#: The counters every rollup row carries, all additive (a row is changed by adding to it, never by overwriting).
COUNTER_COLUMNS: tuple[str, ...] = (
    "turns", "errors", "blocked", "handed_off", "conversations", "input_tokens", "output_tokens", "tool_calls", "tool_errors",
    "ms_sum", "up", "down", "handoff_total", "handoff_open", "handoff_claimed", "handoff_resolved", "handoff_resolve_n",
) + LATENCY_COLUMNS
#: Float counters (the rest are whole numbers).
FLOAT_COLUMNS: tuple[str, ...] = ("handoff_resolve_min_sum",)

GRAINS: tuple[str, ...] = ("minute", "hour", "day")
#: How long each grain is kept. The raw events and the per-day tables have their own limits in the housekeeping.
GRAIN_RETENTION_HOURS: dict[str, int] = {"minute": 48, "hour": 90 * 24, "day": 400 * 24}

#: JSON on every database, JSONB on Postgres.
# (an absent value is SQL NULL, not the JSON text "null": the rows are filtered on it)
JSON_COLUMN = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


def _uuid_col(*, primary_key: bool = True) -> Column:
    return Column("project_id", UUID(as_uuid=True), primary_key=primary_key, nullable=False)


def _rollup_table(name: str, grain: str) -> Table:
    """One counter table per grain. ``bucket`` is the start of the minute, hour or day (UTC) the EVENT happened in, not when it arrived."""
    return Table(
        name, Base.metadata,
        _uuid_col(),
        Column("bucket", DateTime(timezone=True), primary_key=True, nullable=False),
        Column("agent_id", String(80), primary_key=True, nullable=False),
        # "" means the event had no role (a person with no role, or the handoff counters, which carry none)
        Column("role", String(60), primary_key=True, nullable=False, server_default=""),
        *[Column(c, BigInteger, nullable=False, server_default="0") for c in COUNTER_COLUMNS],
        *[Column(c, Float, nullable=False, server_default="0") for c in FLOAT_COLUMNS],
        # retention deletes by time alone
        Index(f"ix_{name}_bucket", "bucket"),
    )


def _model_table(name: str) -> Table:
    return Table(
        name, Base.metadata,
        _uuid_col(),
        Column("bucket", DateTime(timezone=True), primary_key=True, nullable=False),
        Column("agent_id", String(80), primary_key=True, nullable=False),
        Column("role", String(60), primary_key=True, nullable=False, server_default=""),
        Column("model", String(100), primary_key=True, nullable=False, server_default=""),
        Column("turns", BigInteger, nullable=False, server_default="0"),
        Column("input_tokens", BigInteger, nullable=False, server_default="0"),
        Column("output_tokens", BigInteger, nullable=False, server_default="0"),
        Index(f"ix_{name}_bucket", "bucket"),
    )


def _tool_table(name: str) -> Table:
    return Table(
        name, Base.metadata,
        _uuid_col(),
        Column("bucket", DateTime(timezone=True), primary_key=True, nullable=False),
        Column("agent_id", String(80), primary_key=True, nullable=False),
        Column("role", String(60), primary_key=True, nullable=False, server_default=""),
        Column("tool", String(80), primary_key=True, nullable=False),
        Column("calls", BigInteger, nullable=False, server_default="0"),
        Column("errors", BigInteger, nullable=False, server_default="0"),
        Column("ms_sum", BigInteger, nullable=False, server_default="0"),
        Index(f"ix_{name}_bucket", "bucket"),
    )


ROLLUP_TABLES: dict[str, Table] = {g: _rollup_table(f"agent_insight_rollup_{g}", g) for g in GRAINS}
MODEL_TABLES: dict[str, Table] = {g: _model_table(f"agent_insight_models_{g}") for g in GRAINS}
TOOL_TABLES: dict[str, Table] = {g: _tool_table(f"agent_insight_tools_{g}") for g in GRAINS}

# ---------------------------------------------------------------------------
# raw events
# ---------------------------------------------------------------------------

#: The raw turn row. On Postgres the table is created PARTITIONED BY RANGE (at) (migration ai1022 / ``create_partitioned_events``);
#: elsewhere (SQLite in tests) this plain definition is used. A unique key on a partitioned table must contain the partition column,
#: so the primary key is (project, event id, at): an event is the same event only if it carries the same ``at``, which a re-sent row does.
agent_turn_events = Table(
    "agent_turn_events", Base.metadata,
    _uuid_col(),
    Column("event_id", String(64), primary_key=True, nullable=False),
    Column("at", DateTime(timezone=True), primary_key=True, nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("agent_id", String(80), nullable=False),
    Column("conversation_id", String(64), nullable=False),
    Column("user_key", String(64), nullable=False),
    Column("role", String(60), nullable=False, server_default=""),
    Column("env", String(16), nullable=False, server_default="production"),
    Column("model", String(100), nullable=False, server_default=""),
    Column("input_tokens", BigInteger, nullable=False, server_default="0"),
    Column("output_tokens", BigInteger, nullable=False, server_default="0"),
    Column("ms", BigInteger, nullable=False, server_default="0"),
    Column("status", String(16), nullable=False),
    Column("tool_calls", Integer, nullable=False, server_default="0"),
    Column("tool_errors", Integer, nullable=False, server_default="0"),
    Column("tools", JSON_COLUMN, nullable=True),
    Column("handed_off", Boolean, nullable=False, server_default=text("false")),
    Column("turn_number", Integer, nullable=False, server_default="1"),
    Column("rating", SmallInteger, nullable=True),
    # when the rating that is held was given: a later rating replaces it, an older one that arrives late does not
    Column("rating_at", DateTime(timezone=True), nullable=True),
    Column("rating_note", String(300), nullable=True),
    Column("problem", JSON_COLUMN, nullable=True),
    # the dashboard's "last five minutes" reads by time within one project
    Index("ix_agent_turn_events_project_at", "project_id", "at"),
)


class AgentInsightKey(Base):
    """The key an app signs its events with. Only the hash is kept; the key itself is shown once, when it is made."""
    __tablename__ = "agent_insight_keys"
    __table_args__ = (
        Index("ix_agent_insight_keys_project", "project_id"),
        # one ACTIVE key per project, enforced by the database so two simultaneous "create" clicks cannot make two
        Index("uq_agent_insight_keys_active", "project_id", unique=True,
              postgresql_where=text("revoked_at IS NULL"), sqlite_where=text("revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # the newest event time the worker has applied for this project: "synced N seconds ago"
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # when the worker last applied a batch for this project (arrival time, not event time): what tells the people-list refresh a project has news
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


agent_insight_users = Table(
    "agent_insight_users", Base.metadata,
    _uuid_col(),
    Column("user_key", String(64), primary_key=True, nullable=False),
    Column("role", String(60), nullable=False, server_default=""),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Index("ix_agent_insight_users_last", "project_id", "last_seen_at"),
    Index("ix_agent_insight_users_first", "project_id", "first_seen_at"),
)

agent_insight_users_daily = Table(
    "agent_insight_users_daily", Base.metadata,
    _uuid_col(),
    Column("day", Date, primary_key=True, nullable=False),
    Column("agent_id", String(80), primary_key=True, nullable=False),
    Column("user_key", String(64), primary_key=True, nullable=False),
    Column("role", String(60), nullable=False, server_default=""),
    Column("turns", BigInteger, nullable=False, server_default="0"),
    Column("input_tokens", BigInteger, nullable=False, server_default="0"),
    Column("output_tokens", BigInteger, nullable=False, server_default="0"),
    Column("errors", BigInteger, nullable=False, server_default="0"),
    Column("up", BigInteger, nullable=False, server_default="0"),
    Column("down", BigInteger, nullable=False, server_default="0"),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
)

# The same counters per person per WEEK (Monday start, UTC), ALL AGENTS added together (one row per person per week, however many agents they
# used), written with the daily rows. A 90-day top list over all agents is then thirteen weeks plus a few days instead of ninety days of
# rows. A list for ONE agent still sums the daily rows.
agent_insight_users_weekly = Table(
    "agent_insight_users_weekly", Base.metadata,
    _uuid_col(),
    Column("week", Date, primary_key=True, nullable=False),
    Column("user_key", String(64), primary_key=True, nullable=False),
    Column("role", String(60), nullable=False, server_default=""),
    Column("turns", BigInteger, nullable=False, server_default="0"),
    Column("input_tokens", BigInteger, nullable=False, server_default="0"),
    Column("output_tokens", BigInteger, nullable=False, server_default="0"),
    Column("errors", BigInteger, nullable=False, server_default="0"),
    Column("up", BigInteger, nullable=False, server_default="0"),
    Column("down", BigInteger, nullable=False, server_default="0"),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
)

# The people half of the summary (top users, different people, people per role), worked out by the worker off the request path and
# read by key. agent "*" is all agents, role "*" all roles. A row exists for each view somebody has asked for in the last day.
agent_insight_people_cache = Table(
    "agent_insight_people_cache", Base.metadata,
    _uuid_col(),
    Column("agent_id", String(80), primary_key=True, nullable=False),
    Column("role", String(60), primary_key=True, nullable=False),
    Column("range", String(8), primary_key=True, nullable=False),
    Column("payload", JSON_COLUMN, nullable=True),            # null until first computed
    Column("computed_at", DateTime(timezone=True), nullable=True),
    Column("wanted_at", DateTime(timezone=True), nullable=False),
    Column("compute_ms", BigInteger, nullable=True),
    Index("ix_agent_insight_people_cache_wanted", "wanted_at"),
)

# One row per person per day (any agent): written insert-or-ignore, so whether a person is NEW for a day is known exactly. That is what
# keeps "how many different people each day" a counter instead of a count over every person-day.
agent_insight_user_days = Table(
    "agent_insight_user_days", Base.metadata,
    _uuid_col(),
    Column("day", Date, primary_key=True, nullable=False),
    Column("user_key", String(64), primary_key=True, nullable=False),
)

# Different people per day, kept as a counter: agent "*" is all agents, role "*" is all roles ("" is a person with no role).
agent_insight_active_daily = Table(
    "agent_insight_active_daily", Base.metadata,
    _uuid_col(),
    Column("day", Date, primary_key=True, nullable=False),
    Column("agent_id", String(80), primary_key=True, nullable=False),
    Column("role", String(60), primary_key=True, nullable=False),
    Column("users", BigInteger, nullable=False, server_default="0"),
)

agent_insight_problems = Table(
    "agent_insight_problems", Base.metadata,
    _uuid_col(),
    Column("turn_id", String(64), primary_key=True, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("agent_id", String(80), nullable=False),
    Column("conversation_id", String(64), nullable=False),
    Column("role", String(60), nullable=False, server_default=""),
    Column("reason", String(24), nullable=False),
    Column("message", String(300), nullable=True),
    Column("detail", String(300), nullable=True),
    # "turn": the app flagged the turn; "rating": made here from a thumbs-down (removed again if the rating changes)
    Column("source", String(8), nullable=False, server_default="turn"),
    Index("ix_agent_insight_problems_at", "project_id", "at"),
)

agent_insight_handoffs = Table(
    "agent_insight_handoffs", Base.metadata,
    _uuid_col(),
    Column("agent_id", String(80), primary_key=True, nullable=False),
    Column("conversation_id", String(64), primary_key=True, nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("status", String(12), nullable=False),
    Column("status_at", DateTime(timezone=True), nullable=False),
    Column("resolve_minutes", Float, nullable=True),
)

agent_insight_pending_ratings = Table(
    "agent_insight_pending_ratings", Base.metadata,
    _uuid_col(),
    Column("turn_id", String(64), primary_key=True, nullable=False),
    Column("rating", SmallInteger, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("note", String(300), nullable=True),
    Column("received_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_agent_insight_pending_received", "received_at"),
)

agent_insight_dropped = Table(
    "agent_insight_dropped", Base.metadata,
    _uuid_col(),
    Column("hour", DateTime(timezone=True), primary_key=True, nullable=False),
    Column("rejected", BigInteger, nullable=False, server_default="0"),
    Column("rate_limited", BigInteger, nullable=False, server_default="0"),
)
