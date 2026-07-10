"""Track last-recalled recency on memory_units and documents.

Adds a nullable ``last_recalled_at TIMESTAMPTZ`` column to ``memory_units`` and
``documents``, plus a partial btree index on each that only carries rows where
the column is not null. Consumers can stamp the column from any recall path
(e.g. via ``OperationValidatorExtension.on_recall_complete``) to power generic
lifecycle use cases: LRU / eviction ordering, analytics on the dormant-memory
tail, cache warmup, and time-based cleanup policies. Downstream retention
readers should ``COALESCE(last_recalled_at, created_at)`` when they want a
"never-recalled-since-ingest" fallback, so a document ingested but not yet
recalled falls back to its ingestion time.

Column defaults to NULL; existing rows are unaffected. The partial index keeps
lookups cheap on tenants where most rows never get stamped — a full btree over
a mostly-null column would be wasted disk without the ``WHERE`` clause.

PG-only migration: the recall path this signal is meant for is PG-only today
(mirrors the intentional Oracle-slot absence in
``s4n5o6p7q8r9_add_consolidated_at_to_memory_units``). Adding the columns on
Oracle without a writer to stamp them would just be dead schema.

Revision ID: a8b9c0d1e2f3
Revises: f4d1c2b3a5e6
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import context, op

from hindsight_api.alembic._dialect import run_for_dialect

revision: str = "a8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "f4d1c2b3a5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _pg_schema_prefix() -> str:
    """Schema-qualifier for raw SQL on PG (multi-tenant search_path)."""
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def _pg_upgrade() -> None:
    schema = _pg_schema_prefix()

    op.execute(
        f"""
        ALTER TABLE {schema}memory_units
        ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMPTZ DEFAULT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE {schema}documents
        ADD COLUMN IF NOT EXISTS last_recalled_at TIMESTAMPTZ DEFAULT NULL
        """
    )

    # Partial indexes: the common tenant shape is "most rows never stamped",
    # so a full btree would be wasted. The WHERE clause keeps the index tight
    # while still accelerating "top-N by last_recalled_at" and
    # "COALESCE(last_recalled_at, created_at) < now() - interval N days"
    # patterns that a lifecycle sweeper is likely to run.
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_memory_units_last_recalled_at
        ON {schema}memory_units (last_recalled_at)
        WHERE last_recalled_at IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_documents_last_recalled_at
        ON {schema}documents (last_recalled_at)
        WHERE last_recalled_at IS NOT NULL
        """
    )


def _pg_downgrade() -> None:
    schema = _pg_schema_prefix()

    op.execute(f"DROP INDEX IF EXISTS {schema}idx_documents_last_recalled_at")
    op.execute(f"DROP INDEX IF EXISTS {schema}idx_memory_units_last_recalled_at")
    op.execute(f"ALTER TABLE {schema}documents DROP COLUMN IF EXISTS last_recalled_at")
    op.execute(f"ALTER TABLE {schema}memory_units DROP COLUMN IF EXISTS last_recalled_at")


def upgrade() -> None:
    run_for_dialect(pg=_pg_upgrade)


def downgrade() -> None:
    run_for_dialect(pg=_pg_downgrade)
