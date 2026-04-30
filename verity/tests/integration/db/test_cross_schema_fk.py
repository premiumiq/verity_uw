"""Cross-schema FK behavior between runtime → governance.

PR 3 split the catch-all schema into governance + runtime. Several FKs
now cross that boundary — most importantly ``runtime.model_invocation_log``
references ``governance.model``. These tests verify the boundary is real
(violations rejected) and that referential actions (CASCADE, default
RESTRICT) behave the same way they would intra-schema.

Inserts are raw SQL because the named-query layer doesn't expose every
column we need to set; the test surface is the schema, not the query
helpers.
"""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from tests.fixtures.builders import make_agent, make_agent_version


async def _insert_decision_log(db, agent_version_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal runtime.agent_decision_log row, return its id."""
    row = await db.fetch_one_raw(
        """
        INSERT INTO runtime.agent_decision_log (
            entity_type, entity_version_id, inference_config_snapshot, channel
        ) VALUES (
            'agent', %(version_id)s, %(snapshot)s::jsonb, 'development'
        )
        RETURNING id
        """,
        {"version_id": str(agent_version_id), "snapshot": json.dumps({"model": "claude"})},
    )
    assert row is not None
    return row["id"]


async def _get_seed_model_id(db) -> uuid.UUID:
    row = await db.fetch_one_raw(
        "SELECT id FROM governance.model WHERE provider = 'anthropic' LIMIT 1"
    )
    assert row is not None
    return row["id"]


# ── Happy path: cross-schema FK resolves ───────────────────────────────────

async def test_model_invocation_log_inserts_with_valid_cross_schema_fk(db):
    av = await make_agent_version(db)
    decision_id = await _insert_decision_log(db, av.id)
    model_id = await _get_seed_model_id(db)

    await db.execute_raw(
        """
        INSERT INTO runtime.model_invocation_log (
            decision_log_id, model_id, provider, model_name,
            started_at, completed_at
        ) VALUES (
            %(decision_id)s, %(model_id)s, 'anthropic', 'claude-sonnet-4-20250514',
            NOW(), NOW()
        )
        """,
        {"decision_id": str(decision_id), "model_id": str(model_id)},
    )

    row = await db.fetch_one_raw(
        "SELECT count(*) AS n FROM runtime.model_invocation_log "
        "WHERE decision_log_id = %(id)s",
        {"id": str(decision_id)},
    )
    assert row["n"] == 1


# ── FK violations ───────────────────────────────────────────────────────────

async def test_model_invocation_log_rejects_unknown_model_id(db):
    """Cross-schema FK is enforced — a bogus model_id must fail.

    Without the FK enforcement the runtime could log invocations against
    deleted models and the cost view would silently show NULL prices.
    """
    av = await make_agent_version(db)
    decision_id = await _insert_decision_log(db, av.id)
    bogus_model_id = uuid.uuid4()

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await db.execute_raw(
            """
            INSERT INTO runtime.model_invocation_log (
                decision_log_id, model_id, provider, model_name,
                started_at, completed_at
            ) VALUES (
                %(decision_id)s, %(model_id)s, 'anthropic', 'fake',
                NOW(), NOW()
            )
            """,
            {"decision_id": str(decision_id), "model_id": str(bogus_model_id)},
        )


async def test_model_invocation_log_rejects_unknown_decision_log_id(db):
    """Same-schema FK to runtime.agent_decision_log also enforced."""
    model_id = await _get_seed_model_id(db)
    bogus_decision_id = uuid.uuid4()

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await db.execute_raw(
            """
            INSERT INTO runtime.model_invocation_log (
                decision_log_id, model_id, provider, model_name,
                started_at, completed_at
            ) VALUES (
                %(decision_id)s, %(model_id)s, 'anthropic', 'claude',
                NOW(), NOW()
            )
            """,
            {"decision_id": str(bogus_decision_id), "model_id": str(model_id)},
        )


# ── Referential actions ────────────────────────────────────────────────────

async def test_deleting_decision_log_cascades_to_model_invocation_log(db):
    """The decision_log_id FK is ON DELETE CASCADE — invocation rows are
    removed when their parent decision is deleted. This keeps the cost
    table in sync when audit-rerun deletes a decision."""
    av = await make_agent_version(db)
    decision_id = await _insert_decision_log(db, av.id)
    model_id = await _get_seed_model_id(db)

    await db.execute_raw(
        """
        INSERT INTO runtime.model_invocation_log (
            decision_log_id, model_id, provider, model_name,
            started_at, completed_at
        ) VALUES (
            %(decision_id)s, %(model_id)s, 'anthropic', 'claude',
            NOW(), NOW()
        )
        """,
        {"decision_id": str(decision_id), "model_id": str(model_id)},
    )

    await db.execute_raw(
        "DELETE FROM runtime.agent_decision_log WHERE id = %(id)s",
        {"id": str(decision_id)},
    )

    row = await db.fetch_one_raw(
        "SELECT count(*) AS n FROM runtime.model_invocation_log "
        "WHERE decision_log_id = %(id)s",
        {"id": str(decision_id)},
    )
    assert row["n"] == 0


async def test_cannot_delete_governance_model_referenced_by_runtime(db):
    """The model_id FK has no ON DELETE clause → defaults to NO ACTION
    (effectively RESTRICT). Deleting a model row that runtime invocation
    rows reference must fail — historical cost data would otherwise
    silently break."""
    av = await make_agent_version(db)
    decision_id = await _insert_decision_log(db, av.id)
    model_id = await _get_seed_model_id(db)

    await db.execute_raw(
        """
        INSERT INTO runtime.model_invocation_log (
            decision_log_id, model_id, provider, model_name,
            started_at, completed_at
        ) VALUES (
            %(decision_id)s, %(model_id)s, 'anthropic', 'claude',
            NOW(), NOW()
        )
        """,
        {"decision_id": str(decision_id), "model_id": str(model_id)},
    )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await db.execute_raw(
            "DELETE FROM governance.model WHERE id = %(id)s",
            {"id": str(model_id)},
        )


# ── Schema introspection: confirm the FK's target schema ───────────────────

async def test_fk_targets_are_in_correct_schemas(db):
    """The information_schema row for the model_id FK should name
    governance as the foreign schema. If a future refactor moves the
    model table back to public/runtime, this fails immediately."""
    row = await db.fetch_one_raw(
        """
        SELECT
            kcu.column_name,
            ccu.table_schema  AS foreign_schema,
            ccu.table_name    AS foreign_table
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.constraint_schema = tc.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.constraint_schema = tc.constraint_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'runtime'
          AND tc.table_name   = 'model_invocation_log'
          AND kcu.column_name = 'model_id'
        """
    )
    assert row is not None
    assert row["foreign_schema"] == "governance"
    assert row["foreign_table"] == "model"
