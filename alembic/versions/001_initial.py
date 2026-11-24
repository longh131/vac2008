"""initial tables"""

from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _sql(value: str):
    return sa.text("'" + value.replace("'", "''") + "'")


def upgrade():
    # A failed first run leaves tables behind. MySQL commits each CREATE immediately.
    if op.get_bind().dialect.name == "mysql":
        op.execute(sa.text("SET FOREIGN_KEY_CHECKS=0"))
    for name in (
        "settings",
        "email_logs",
        "favorites",
        "crawl_runs",
        "opportunities",
        "subscriptions",
        "login_tokens",
        "users",
    ):
        op.execute(sa.text(f"DROP TABLE IF EXISTS {name}"))
    if op.get_bind().dialect.name == "mysql":
        op.execute(sa.text("SET FOREIGN_KEY_CHECKS=1"))

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("digest_opt_out", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "login_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime),
    )
    op.create_index("ix_login_tokens_hash", "login_tokens", ["token_hash"], unique=True)
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False, server_default=_sql("lemonsqueezy")),
        sa.Column("provider_subscription_id", sa.String(80), nullable=False, server_default=_sql("")),
        sa.Column("status", sa.String(20), nullable=False, server_default=_sql("expired")),
        sa.Column("current_period_end", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_index("ix_subscriptions_user", "subscriptions", ["user_id"], unique=True)
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_key", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False, server_default=_sql("")),
        sa.Column("state", sa.String(8), nullable=False),
        sa.Column("city_or_agency", sa.String(255), nullable=False, server_default=_sql("")),
        sa.Column("category", sa.String(80), nullable=False, server_default=_sql("Other")),
        sa.Column("title_raw", sa.String(500), nullable=False, server_default=_sql("")),
        sa.Column("title_clean", sa.String(500), nullable=False, server_default=_sql("")),
        sa.Column("estimated_budget", sa.String(120), nullable=False, server_default=_sql("Not Disclosed")),
        sa.Column("deadline_at", sa.DateTime),
        sa.Column("deadline_text", sa.String(120), nullable=False, server_default=_sql("")),
        sa.Column("summary_plain", sa.Text, nullable=False),
        sa.Column("fit_score", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fit_reason", sa.String(300), nullable=False, server_default=_sql("")),
        sa.Column("contact_name", sa.String(200), nullable=False, server_default=_sql("")),
        sa.Column("contact_email", sa.String(200), nullable=False, server_default=_sql("")),
        sa.Column("contact_phone", sa.String(80), nullable=False, server_default=_sql("")),
        sa.Column("bid_email_draft", sa.Text, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("raw_hash", sa.String(64), nullable=False, server_default=_sql("")),
        sa.Column("status", sa.String(20), nullable=False, server_default=_sql("active")),
        sa.Column("ai_status", sa.String(20), nullable=False, server_default=_sql("pending")),
        sa.Column("published_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
        sa.UniqueConstraint("source_key", "external_id", name="uq_source_external"),
    )
    op.create_index("ix_opportunities_state", "opportunities", ["state"])
    op.create_index("ix_opportunities_category", "opportunities", ["category"])
    op.create_index("ix_opportunities_status", "opportunities", ["status"])
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("found", sa.Integer, nullable=False, server_default="0"),
        sa.Column("inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_ok", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_failed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=False),
    )
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("opportunity_id", sa.Integer, sa.ForeignKey("opportunities.id"), nullable=False),
        sa.Column("created_at", sa.DateTime),
        sa.UniqueConstraint("user_id", "opportunity_id", name="uq_favorite"),
    )
    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("sent_on", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=_sql("sent")),
        sa.Column("detail", sa.Text, nullable=False),
        sa.UniqueConstraint("user_id", "kind", "sent_on", name="uq_email_once"),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )


def downgrade():
    for name in ("settings", "email_logs", "favorites", "crawl_runs", "opportunities", "subscriptions", "login_tokens", "users"):
        op.drop_table(name)
