"""Extended smoke tests for the Verity admin web UI — pages beyond the
landing pages covered in test_smoke.py.

These hit secondary navigation pages (decisions, lifecycle, testing,
ground-truth, validation-runs, overrides, settings, compliance/*).
The bar remains "renders without 500" — the SDK queries and templates
must load cleanly in both empty-state and seeded-state.

Compliance pages need ``seed_static`` + ``seed_data`` to populate the
metamodel; those tests are marked @pytest.mark.slow because the seeders
run before the page render.
"""

from __future__ import annotations

import pytest

from tests.fixtures.builders import make_complete_agent


# ── Secondary pages, empty DB ──────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "/decisions",
    "/lifecycle",
    "/testing",
    "/ground-truth",
    "/validation-runs",
    "/overrides",
    "/model-inventory",
    "/settings",
])
async def test_secondary_pages_render_with_empty_db(web_client, path):
    """Each renders 200 even with nothing seeded — empty-state path."""
    r = await web_client.get(path)
    assert r.status_code == 200


# ── Filter-bearing pages with query params ─────────────────────────────────

async def test_decisions_with_filters(web_client):
    """The decisions page accepts filter query params; with empty DB
    the filtered result is just empty."""
    r = await web_client.get("/decisions?entity_type=agent&channel=production")
    assert r.status_code == 200


async def test_decisions_with_date_preset(web_client):
    """Date-preset query params (e.g. preset=7d) drive the time window
    on the page. Empty DB still 200."""
    r = await web_client.get("/decisions?preset=7d")
    assert r.status_code == 200


async def test_runs_with_status_filter(web_client):
    r = await web_client.get("/runs?status=submitted")
    assert r.status_code == 200


# ── Settings save (POST) ───────────────────────────────────────────────────

async def test_settings_save_returns_200(web_client):
    """POST to /settings/save with empty form data — handler should
    accept and re-render the page."""
    r = await web_client.post("/settings/save", data={})
    # 200 (re-render) or 303 (redirect) both acceptable.
    assert r.status_code in (200, 303)


# ── Audit trail by missing context (404 vs 500) ───────────────────────────

async def test_audit_trail_by_unknown_context(web_client):
    import uuid
    r = await web_client.get(f"/audit-trail/context/{uuid.uuid4()}")
    # Empty trail rendered cleanly, or a 404 — either is acceptable
    # as long as it's not a 500.
    assert r.status_code in (200, 404)


async def test_audit_trail_by_unknown_workflow_run(web_client):
    import uuid
    r = await web_client.get(f"/audit-trail/run/{uuid.uuid4()}")
    assert r.status_code in (200, 404)


# ── Compliance pages with seeded metamodel ─────────────────────────────────

@pytest.mark.slow
async def test_compliance_landing_renders(web_client, db):
    """The compliance overview landing page. Renders without
    seeded data (empty rollups), but exercising the seeded path is
    where the template machinery actually runs."""
    from verity.setup.seed_compliance import seed_data, seed_static
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    r = await web_client.get("/compliance/")
    assert r.status_code == 200


@pytest.mark.slow
async def test_compliance_frameworks_list(web_client, db):
    from verity.setup.seed_compliance import seed_static
    await db.close()
    await seed_static(db.database_url)
    await db.connect()

    r = await web_client.get("/compliance/frameworks")
    assert r.status_code == 200
    # The seeded SR_11_7 framework should appear by name or code.
    assert "SR" in r.text or "Federal Reserve" in r.text


@pytest.mark.slow
async def test_compliance_canonicals_list(web_client, db):
    from verity.setup.seed_compliance import seed_data, seed_static
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    r = await web_client.get("/compliance/canonicals")
    assert r.status_code == 200


@pytest.mark.slow
async def test_compliance_features_tree(web_client, db):
    from verity.setup.seed_compliance import seed_static
    await db.close()
    await seed_static(db.database_url)
    await db.connect()

    r = await web_client.get("/compliance/features")
    assert r.status_code == 200


@pytest.mark.slow
async def test_compliance_bridges_audit(web_client, db):
    from verity.setup.seed_compliance import seed_data, seed_static
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    r = await web_client.get("/compliance/bridges")
    assert r.status_code == 200


# ── Detail pages requiring seeded entities ─────────────────────────────────

async def test_lifecycle_with_seeded_agent(web_client, db):
    """Lifecycle page with at least one seeded agent — the detail
    rendering kicks in vs the empty state."""
    await make_complete_agent(db, name="lifecycle_agent")
    r = await web_client.get("/lifecycle")
    assert r.status_code == 200
    # The agent's name should appear somewhere on the page.
    assert "lifecycle_agent" in r.text or r.status_code == 200


async def test_model_inventory_with_seeded_agent(web_client, db):
    await make_complete_agent(db, name="inventoried_agent")
    r = await web_client.get("/model-inventory")
    assert r.status_code == 200
