"""Rollback: deprecate a champion and write the rollback approval record.

``Lifecycle.rollback`` only operates on champion versions — calling it
on a non-champion raises. The rollback creates an approval row with
gate_type='rollback' for the audit trail.

Restoring the prior champion is left to the caller in the current
implementation; the rollback method itself only deprecates the present
champion. Tests reflect that contract.
"""

from __future__ import annotations

import pytest

from verity.governance.lifecycle import Lifecycle
from verity.models.lifecycle import EntityType, LifecycleState, PromotionRequest

from tests.fixtures.builders import make_agent_version, promote


def _fast_track() -> PromotionRequest:
    return PromotionRequest(
        target_state=LifecycleState.CHAMPION,
        approver_name="tester",
        rationale="Promote to champion for rollback test.",
    )


async def test_rollback_deprecates_champion(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    lifecycle = Lifecycle(db)
    await lifecycle.promote(EntityType.AGENT, av.id, _fast_track())

    result = await lifecycle.rollback(
        EntityType.AGENT, av.id,
        approver_name="rollback_owner",
        rationale="Production incident — see ticket #42.",
    )
    assert result["entity_type"] == "agent"
    assert str(result["rolled_back_version"]) == str(av.id)

    row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM agent_version WHERE id = %(id)s",
        {"id": str(av.id)},
    )
    assert row["lifecycle_state"] == "deprecated"


async def test_rollback_creates_approval_record(db):
    av = await make_agent_version(db)
    await promote(db, av, to_state="candidate")
    lifecycle = Lifecycle(db)
    await lifecycle.promote(EntityType.AGENT, av.id, _fast_track())

    result = await lifecycle.rollback(
        EntityType.AGENT, av.id,
        approver_name="rollback_owner",
        rationale="Bad metrics observed.",
    )

    row = await db.fetch_one_raw(
        "SELECT gate_type, from_state, to_state, approver_name, rationale "
        "FROM approval_record WHERE id = %(id)s",
        {"id": str(result["approval_id"])},
    )
    assert row is not None
    assert row["gate_type"] == "rollback"
    assert row["from_state"] == "champion"
    assert row["to_state"] == "deprecated"
    assert row["approver_name"] == "rollback_owner"


async def test_rollback_rejects_non_champion(db):
    """Rollback is champion-only — rolling back a draft/candidate/etc.
    is meaningless and should fail loudly."""
    av = await make_agent_version(db)
    # Stays in draft.
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="Can only rollback a champion"):
        await lifecycle.rollback(
            EntityType.AGENT, av.id,
            approver_name="owner", rationale="Mistake.",
        )


async def test_rollback_rejects_unknown_version(db):
    import uuid
    bogus = uuid.uuid4()
    lifecycle = Lifecycle(db)

    with pytest.raises(ValueError, match="not found"):
        await lifecycle.rollback(
            EntityType.AGENT, bogus,
            approver_name="owner", rationale="404.",
        )
