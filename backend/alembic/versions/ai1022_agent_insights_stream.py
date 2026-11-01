"""agent insights, push and rollup: keys, raw turn events, minute/hour/day rollups, users, problems, handoffs

A generated app now ships its assistant turns to the platform (POST /api/insights/ingest), and the Insights page reads counters
the platform keeps, instead of the platform reading the newest rows out of the app's own table. See models/agent_insights.py for
what each table is for and services/agent_insights_store.py for how they are written.

On Postgres ``agent_turn_events`` is PARTITIONED BY RANGE (at), one partition per UTC day, so dropping a month-old day is instant
and never a long DELETE. The worker keeps tomorrow's partitions ahead of time (``ensure_partitions`` in the store); this migration
makes the ones for the last 30 days and the next 7, plus a DEFAULT partition that catches anything else (an event older than a
month that is still inside the 90 days the platform accepts). Other databases (SQLite in tests) get one plain table.

Revision ID: ai1022_agent_insights_stream
Revises: tp1016_test_and_production
Create Date: 2026-10-22
"""
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai1022_agent_insights_stream"
down_revision = "tp1016_test_and_production"
branch_labels = None
depends_on = None

# Written out here, not imported from the model: a migration describes the database as it was made, whatever the model says later.
LATENCY_BUCKETS = 26
COUNTERS = ("turns", "errors", "blocked", "handed_off", "conversations", "input_tokens", "output_tokens", "tool_calls",
            "tool_errors", "ms_sum", "up", "down", "handoff_total", "handoff_open", "handoff_claimed", "handoff_resolved",
            "handoff_resolve_n") + tuple(f"lat_{i}" for i in range(LATENCY_BUCKETS))
GRAINS = ("minute", "hour", "day")


def _project() -> sa.Column:
    return sa.Column("project_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)


def _bigint(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger, nullable=False, server_default="0")


def _create_events_table() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        op.create_table(
            "agent_turn_events", _project(),
            sa.Column("event_id", sa.String(64), primary_key=True, nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), primary_key=True, nullable=False),
            *_event_columns(sa.JSON()),
        )
        op.create_index("ix_agent_turn_events_project_at", "agent_turn_events", ["project_id", "at"])
        return
    op.execute("""
        CREATE TABLE agent_turn_events (
            project_id uuid NOT NULL,
            event_id varchar(64) NOT NULL,
            at timestamptz NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            agent_id varchar(80) NOT NULL,
            conversation_id varchar(64) NOT NULL,
            user_key varchar(64) NOT NULL,
            role varchar(60) NOT NULL DEFAULT '',
            env varchar(16) NOT NULL DEFAULT 'production',
            model varchar(100) NOT NULL DEFAULT '',
            input_tokens bigint NOT NULL DEFAULT 0,
            output_tokens bigint NOT NULL DEFAULT 0,
            ms bigint NOT NULL DEFAULT 0,
            status varchar(16) NOT NULL,
            tool_calls integer NOT NULL DEFAULT 0,
            tool_errors integer NOT NULL DEFAULT 0,
            tools jsonb,
            handed_off boolean NOT NULL DEFAULT false,
            turn_number integer NOT NULL DEFAULT 1,
            rating smallint,
            rating_at timestamptz,
            rating_note varchar(300),
            problem jsonb,
            PRIMARY KEY (project_id, event_id, at)
        ) PARTITION BY RANGE (at)
    """)
    op.execute("CREATE TABLE agent_turn_events_default PARTITION OF agent_turn_events DEFAULT")
    op.execute("CREATE INDEX ix_agent_turn_events_project_at ON agent_turn_events (project_id, at)")
    today = datetime.now(timezone.utc).date()
    for offset in range(-30, 8):
        day = today + timedelta(days=offset)
        nxt = day + timedelta(days=1)
        op.execute(f"CREATE TABLE IF NOT EXISTS agent_turn_events_p{day:%Y%m%d} PARTITION OF agent_turn_events "
                   f"FOR VALUES FROM ('{day} 00:00:00+00') TO ('{nxt} 00:00:00+00')")


def _event_columns(json_type) -> list[sa.Column]:
    return [
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("agent_id", sa.String(80), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("user_key", sa.String(64), nullable=False),
        sa.Column("role", sa.String(60), nullable=False, server_default=""),
        sa.Column("env", sa.String(16), nullable=False, server_default="production"),
        sa.Column("model", sa.String(100), nullable=False, server_default=""),
        _bigint("input_tokens"), _bigint("output_tokens"), _bigint("ms"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("tool_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tool_errors", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tools", json_type, nullable=True),
        sa.Column("handed_off", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("turn_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("rating", sa.SmallInteger, nullable=True),
        sa.Column("rating_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating_note", sa.String(300), nullable=True),
        sa.Column("problem", json_type, nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_insight_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_insight_keys_project", "agent_insight_keys", ["project_id"])
    op.create_index("uq_agent_insight_keys_active", "agent_insight_keys", ["project_id"], unique=True,
                    postgresql_where=sa.text("revoked_at IS NULL"), sqlite_where=sa.text("revoked_at IS NULL"))

    _create_events_table()

    for grain in GRAINS:
        key = [_project(), sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True, nullable=False),
               sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
               sa.Column("role", sa.String(60), primary_key=True, nullable=False, server_default="")]
        op.create_table(f"agent_insight_rollup_{grain}", *key, *[_bigint(c) for c in COUNTERS],
                        sa.Column("handoff_resolve_min_sum", sa.Float, nullable=False, server_default="0"))
        op.create_index(f"ix_agent_insight_rollup_{grain}_bucket", f"agent_insight_rollup_{grain}", ["bucket"])

        op.create_table(
            f"agent_insight_models_{grain}", _project(),
            sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
            sa.Column("role", sa.String(60), primary_key=True, nullable=False, server_default=""),
            sa.Column("model", sa.String(100), primary_key=True, nullable=False, server_default=""),
            _bigint("turns"), _bigint("input_tokens"), _bigint("output_tokens"),
        )
        op.create_index(f"ix_agent_insight_models_{grain}_bucket", f"agent_insight_models_{grain}", ["bucket"])

        op.create_table(
            f"agent_insight_tools_{grain}", _project(),
            sa.Column("bucket", sa.DateTime(timezone=True), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
            sa.Column("role", sa.String(60), primary_key=True, nullable=False, server_default=""),
            sa.Column("tool", sa.String(80), primary_key=True, nullable=False),
            _bigint("calls"), _bigint("errors"), _bigint("ms_sum"),
        )
        op.create_index(f"ix_agent_insight_tools_{grain}_bucket", f"agent_insight_tools_{grain}", ["bucket"])

    op.create_table(
        "agent_insight_users", _project(),
        sa.Column("user_key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("role", sa.String(60), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_insight_users_last", "agent_insight_users", ["project_id", "last_seen_at"])
    op.create_index("ix_agent_insight_users_first", "agent_insight_users", ["project_id", "first_seen_at"])

    op.create_table(
        "agent_insight_users_daily", _project(),
        sa.Column("day", sa.Date, primary_key=True, nullable=False),
        sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
        sa.Column("user_key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("role", sa.String(60), nullable=False, server_default=""),
        _bigint("turns"), _bigint("input_tokens"), _bigint("output_tokens"), _bigint("errors"), _bigint("up"), _bigint("down"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agent_insight_users_weekly", _project(),
        sa.Column("week", sa.Date, primary_key=True, nullable=False),
        sa.Column("user_key", sa.String(64), primary_key=True, nullable=False),
        sa.Column("role", sa.String(60), nullable=False, server_default=""),
        _bigint("turns"), _bigint("input_tokens"), _bigint("output_tokens"), _bigint("errors"), _bigint("up"), _bigint("down"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_insight_people_cache", _project(),
        sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
        sa.Column("role", sa.String(60), primary_key=True, nullable=False),
        sa.Column("range", sa.String(8), primary_key=True, nullable=False),
        sa.Column("payload", postgresql.JSONB(none_as_null=True).with_variant(sa.JSON(none_as_null=True), "sqlite"), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wanted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("compute_ms", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_agent_insight_people_cache_wanted", "agent_insight_people_cache", ["wanted_at"])

    op.create_table(
        "agent_insight_user_days", _project(),
        sa.Column("day", sa.Date, primary_key=True, nullable=False),
        sa.Column("user_key", sa.String(64), primary_key=True, nullable=False),
    )
    op.create_table(
        "agent_insight_active_daily", _project(),
        sa.Column("day", sa.Date, primary_key=True, nullable=False),
        sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
        sa.Column("role", sa.String(60), primary_key=True, nullable=False),
        _bigint("users"),
    )

    op.create_table(
        "agent_insight_problems", _project(),
        sa.Column("turn_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(80), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(60), nullable=False, server_default=""),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("message", sa.String(300), nullable=True),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("source", sa.String(8), nullable=False, server_default="turn"),
    )
    op.create_index("ix_agent_insight_problems_at", "agent_insight_problems", ["project_id", "at"])

    op.create_table(
        "agent_insight_handoffs", _project(),
        sa.Column("agent_id", sa.String(80), primary_key=True, nullable=False),
        sa.Column("conversation_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolve_minutes", sa.Float, nullable=True),
    )

    op.create_table(
        "agent_insight_pending_ratings", _project(),
        sa.Column("turn_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(300), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_insight_pending_received", "agent_insight_pending_ratings", ["received_at"])

    op.create_table(
        "agent_insight_dropped", _project(),
        sa.Column("hour", sa.DateTime(timezone=True), primary_key=True, nullable=False),
        _bigint("rejected"), _bigint("rate_limited"),
    )


def downgrade() -> None:
    for name in ("agent_insight_people_cache", "agent_insight_users_weekly", "agent_insight_active_daily", "agent_insight_user_days", "agent_insight_dropped", "agent_insight_pending_ratings", "agent_insight_handoffs", "agent_insight_problems",
                 "agent_insight_users_daily", "agent_insight_users"):
        op.drop_table(name)
    for grain in GRAINS:
        op.drop_table(f"agent_insight_tools_{grain}")
        op.drop_table(f"agent_insight_models_{grain}")
        op.drop_table(f"agent_insight_rollup_{grain}")
    # dropping the parent drops its partitions with it
    op.drop_table("agent_turn_events")
    op.drop_table("agent_insight_keys")
