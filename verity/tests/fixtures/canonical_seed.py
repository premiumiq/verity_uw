"""Minimal seed data loaded into the test template DB once per session.

Philosophy: keep this tiny. The more tests depend on hidden seed state, the
harder they are to read and the more brittle the suite becomes. Tests that
need agents/prompts/tools should create them inline so the test reads
top-to-bottom.

What's seeded here:
  - One ``inference_config`` row that downstream FKs (agent_version,
    task_version) can point to.
  - One ``model`` row in the LLM model catalog so model-related FKs
    (e.g. model_invocation_log → model) have a target.

What's NOT seeded:
  - Agents, tasks, prompts, tools — vary per test.
  - The compliance metamodel — load via the dedicated seeder when a test
    actually needs it. Most integration tests in this PR don't.
  - The 3 governance applications (``ai_ops``, ``model_validation``,
    ``compliance_audit``) are seeded by ``apply_schema()`` directly — see
    ``verity/src/verity/db/migrate.py``.
"""

from __future__ import annotations

from verity.db.connection import Database


# Stable identifiers tests can reference by name without hardcoding UUIDs.
TEST_INFERENCE_CONFIG_NAME = "test_default_config"
TEST_MODEL_PROVIDER = "anthropic"
TEST_MODEL_ID = "claude-sonnet-4-20250514"


async def load_canonical_seed(db: Database) -> None:
    """Insert the minimal seed rows. Idempotent — safe to call twice."""
    # ``model`` row — uq_model is on (provider, model_id), so ON CONFLICT
    # is the cleanest idempotent path.
    await db.execute_raw(
        """
        INSERT INTO model (provider, model_id, display_name, modality,
                           context_window, status, description)
        VALUES (%(provider)s, %(model_id)s, %(display_name)s, 'chat',
                200000, 'active',
                'Seed model used by Verity tests; not a real catalog entry.')
        ON CONFLICT (provider, model_id) DO NOTHING
        """,
        {
            "provider": TEST_MODEL_PROVIDER,
            "model_id": TEST_MODEL_ID,
            "display_name": "Test Claude Sonnet (seed)",
        },
    )

    # ``inference_config`` row — uniqueness is on ``name``.
    await db.execute_raw(
        """
        INSERT INTO inference_config (name, display_name, description,
                                      intended_use, model_name, temperature,
                                      max_tokens)
        VALUES (%(name)s, %(display_name)s, %(description)s,
                %(intended_use)s, %(model_name)s, 0.0, 4096)
        ON CONFLICT (name) DO NOTHING
        """,
        {
            "name": TEST_INFERENCE_CONFIG_NAME,
            "display_name": "Test Default Config",
            "description": "Seed inference config used by Verity tests.",
            "intended_use": "Used as the inference_config_id FK target in "
                            "agent_version / task_version test inserts.",
            "model_name": TEST_MODEL_ID,
        },
    )
