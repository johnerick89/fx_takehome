"""add_transactions_and_idempotency

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-11 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "transactions",
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("from_currency", sa.String(length=3), nullable=False),
        sa.Column("to_currency", sa.String(length=3), nullable=False),
        sa.Column("debited_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("credited_amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("exchange_rate", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("quote_id"),
    )
    op.create_table(
        "idempotency_log",
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("quote_id", sa.String(length=36), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        op.f("ix_idempotency_log_idempotency_key"),
        "idempotency_log",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_idempotency_log_idempotency_key"), table_name="idempotency_log")
    op.drop_table("idempotency_log")
    op.drop_table("transactions")
