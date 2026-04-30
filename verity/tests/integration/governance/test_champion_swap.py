"""Champion swap: promoting v2 to champion deprecates v1 and flips the
``agent.current_champion_version_id`` pointer.

The pointer is what ``Registry.get_agent_champion`` reads to resolve
"the current champion" — so a stale or unset pointer means the runtime
keeps using the old champion even after the new one is promoted.
"""

from __future__ import annotations

from verity.governance.lifecycle import Lifecycle
from verity.models.lifecycle import EntityType, LifecycleState, PromotionRequest

from tests.fixtures.builders import (
    make_agent,
    make_agent_version,
    promote,
)


def _fast_track_request() -> PromotionRequest:
    """Candidate → Champion fast-track (no full gate evidence required)."""
    return PromotionRequest(
        target_state=LifecycleState.CHAMPION,
        approver_name="tester",
        rationale="Champion swap test.",
    )


async def test_first_champion_promotion_sets_pointer(db):
    agent = await make_agent(db, name="risk_extractor")
    v1 = await make_agent_version(db, agent_id=agent.id)
    await promote(db, v1, to_state="candidate")
    lifecycle = Lifecycle(db)

    await lifecycle.promote(EntityType.AGENT, v1.id, _fast_track_request())

    row = await db.fetch_one_raw(
        "SELECT current_champion_version_id FROM agent WHERE id = %(id)s",
        {"id": str(agent.id)},
    )
    assert row is not None
    assert str(row["current_champion_version_id"]) == str(v1.id)


async def test_promoting_v2_deprecates_v1_and_flips_pointer(db):
    agent = await make_agent(db, name="risk_extractor")
    v1 = await make_agent_version(db, agent_id=agent.id)
    v2 = await make_agent_version(db, agent_id=agent.id, minor_version=1)
    lifecycle = Lifecycle(db)

    # v1 takes the throne first.
    await promote(db, v1, to_state="candidate")
    await lifecycle.promote(EntityType.AGENT, v1.id, _fast_track_request())

    # v2 promoted via fast-track too.
    await promote(db, v2, to_state="candidate")
    await lifecycle.promote(EntityType.AGENT, v2.id, _fast_track_request())

    # v2 is the current champion …
    agent_row = await db.fetch_one_raw(
        "SELECT current_champion_version_id FROM agent WHERE id = %(id)s",
        {"id": str(agent.id)},
    )
    assert str(agent_row["current_champion_version_id"]) == str(v2.id)

    # … and v1 has been deprecated automatically.
    v1_row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM agent_version WHERE id = %(id)s",
        {"id": str(v1.id)},
    )
    assert v1_row["lifecycle_state"] == "deprecated"

    # v2's state is champion.
    v2_row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM agent_version WHERE id = %(id)s",
        {"id": str(v2.id)},
    )
    assert v2_row["lifecycle_state"] == "champion"


async def test_re_promoting_same_version_does_not_deprecate_itself(db):
    """Edge case: if for any reason the same version is promoted twice
    (idempotent re-run), the version must NOT deprecate itself."""
    agent = await make_agent(db, name="self_promote")
    v1 = await make_agent_version(db, agent_id=agent.id)
    await promote(db, v1, to_state="candidate")
    lifecycle = Lifecycle(db)

    await lifecycle.promote(EntityType.AGENT, v1.id, _fast_track_request())

    # Second promote attempt: champion → champion isn't a valid transition,
    # so the lifecycle module rejects it. This test is here to confirm
    # that NO collateral damage happens to the existing champion when
    # the second call fails.
    import pytest
    with pytest.raises(ValueError):
        await lifecycle.promote(EntityType.AGENT, v1.id, _fast_track_request())

    row = await db.fetch_one_raw(
        "SELECT lifecycle_state FROM agent_version WHERE id = %(id)s",
        {"id": str(v1.id)},
    )
    # State must still be champion — the failed promote attempt mustn't
    # have deprecated the row before the gate check raised.
    assert row["lifecycle_state"] == "champion"
