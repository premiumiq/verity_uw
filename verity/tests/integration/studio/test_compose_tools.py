"""Compose-mode tool browse + edit pages.

Tools are unversioned global assets — same shape as the config
editor but with extra field types: booleans (checkboxes with
hidden-pair pattern), JSON schemas, list-typed tags, and an enum
data_classification_max.

Tests cover:

  * Read-only browse and 404.
  * Edit form pre-populates with current values.
  * Save happy path — text, JSON, booleans, tags all round-trip.
  * Stale-stamp conflict.
  * JSON parse error on input/output_schema and mock_responses.
  * Boolean unchecking — saving with the hidden=0 pair must record
    False (otherwise users could never untick a flag).
  * Promoted-consumer warning rendered when champion exists.
"""

from __future__ import annotations

import re

from tests.fixtures.builders import (
    authorize_tool,
    make_complete_agent,
    make_tool,
)


# ── browse ─────────────────────────────────────────────────────────────────


async def test_tools_list_renders_existing_tools(studio_client, db):
    await make_tool(db, name="studio_browse_tool")
    r = await studio_client.get("/studio/compose/tools")
    assert r.status_code == 200
    body = r.text
    assert "studio_browse_tool" in body
    assert "/studio/compose/tools/studio_browse_tool" in body


async def test_tool_detail_404_for_missing(studio_client, db):
    r = await studio_client.get("/studio/compose/tools/no_such_tool")
    assert r.status_code == 404


# ── edit page ──────────────────────────────────────────────────────────────


async def test_tool_detail_renders_form_with_current_values(
    studio_client, db,
):
    await make_tool(
        db,
        name="form_render_tool",
        display_name="Form Render Tool",
        description="Lookup tool used by form-render test.",
        transport="python_inprocess",
        implementation_path="some.module.lookup_fn",
    )

    r = await studio_client.get("/studio/compose/tools/form_render_tool")
    assert r.status_code == 200
    body = r.text
    # Form posts to the save handler via HTMX.
    assert "hx-post=" in body
    assert "/studio/compose/tools/form_render_tool/save" in body
    # Hidden stamp is present.
    assert 'name="expected_updated_at"' in body
    # Current values are visible.
    assert "Form Render Tool" in body
    assert "Lookup tool used by form-render test." in body
    assert "some.module.lookup_fn" in body
    # Transport dropdown selected the right option.
    assert 'value="python_inprocess" selected' in body


# ── save handler — happy path ──────────────────────────────────────────────


async def test_save_handler_returns_ok_partial_when_stamp_matches(
    studio_client, db,
):
    """Save with the matching stamp succeeds and the DB row reflects
    the new values across text, schema, and tag fields."""
    await make_tool(
        db,
        name="save_happy_tool",
        display_name="Original Display",
    )

    edit_resp = await studio_client.get(
        "/studio/compose/tools/save_happy_tool",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    save_resp = await studio_client.post(
        "/studio/compose/tools/save_happy_tool/save",
        data={
            "display_name": "Updated Display",
            "description": "Updated description.",
            "transport": "python_inprocess",
            "implementation_path": "x.y.updated",
            "input_schema": '{"type": "object", "properties": {"q": {"type": "string"}}}',
            "output_schema": '{"type": "object"}',
            "data_classification_max": "tier2_internal",
            "tags": "production\nlookup\n  query  ",
            "expected_updated_at": stamp,
        },
    )
    assert save_resp.status_code == 200, save_resp.text
    assert "Saved" in save_resp.text

    row = await db.fetch_one_raw(
        """
        SELECT display_name, description, implementation_path,
               input_schema, output_schema,
               data_classification_max, tags
        FROM governance.tool
        WHERE name = %(name)s
        """,
        {"name": "save_happy_tool"},
    )
    assert row["display_name"] == "Updated Display"
    assert row["implementation_path"] == "x.y.updated"
    assert row["input_schema"] == {
        "type": "object",
        "properties": {"q": {"type": "string"}},
    }
    assert str(row["data_classification_max"]) == "tier2_internal"
    assert row["tags"] == ["production", "lookup", "query"]


# ── save handler — stale stamp ─────────────────────────────────────────────


async def test_save_handler_returns_conflict_partial_on_stale_stamp(
    studio_client, db,
):
    await make_tool(db, name="save_conflict_tool", display_name="Initial")

    edit_resp = await studio_client.get(
        "/studio/compose/tools/save_conflict_tool",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    first = await studio_client.post(
        "/studio/compose/tools/save_conflict_tool/save",
        data={"display_name": "Client B", "expected_updated_at": stamp},
    )
    assert first.status_code == 200
    assert "Saved" in first.text

    second = await studio_client.post(
        "/studio/compose/tools/save_conflict_tool/save",
        data={"display_name": "Client A stale", "expected_updated_at": stamp},
    )
    assert second.status_code == 200
    assert "Stale save" in second.text

    row = await db.fetch_one_raw(
        "SELECT display_name FROM governance.tool WHERE name = %(name)s",
        {"name": "save_conflict_tool"},
    )
    assert row["display_name"] == "Client B"


# ── save handler — boolean unchecking ──────────────────────────────────────


async def test_save_handler_records_false_when_checkbox_unchecked(
    studio_client, db,
):
    """The hidden=0 / checkbox=1 pair must let an unchecked checkbox
    actually save False. Otherwise users could never untick a flag."""
    # Start with mock_mode_enabled=True so we can verify it flips off.
    await make_tool(
        db, name="checkbox_test_tool", mock_mode_enabled=True,
    )

    r = await studio_client.post(
        "/studio/compose/tools/checkbox_test_tool/save",
        # The form template emits the hidden=0 pair for each checkbox.
        # When the user unchecks the box, only the hidden=0 is sent.
        # We simulate that here by including only the hidden value.
        data={"mock_mode_enabled": "0"},
    )
    assert r.status_code == 200
    assert "Saved" in r.text

    row = await db.fetch_one_raw(
        "SELECT mock_mode_enabled FROM governance.tool WHERE name = %(name)s",
        {"name": "checkbox_test_tool"},
    )
    assert row["mock_mode_enabled"] is False


async def test_save_handler_records_true_when_checkbox_checked(
    studio_client, db,
):
    """When the checkbox is checked, the form submits both the hidden=0
    AND the checkbox=1 — last value wins."""
    await make_tool(
        db, name="checkbox_check_tool", mock_mode_enabled=False,
    )

    r = await studio_client.post(
        "/studio/compose/tools/checkbox_check_tool/save",
        # When the checkbox is checked, the form submits BOTH the
        # hidden=0 and the checkbox=1. Pass them as a list so httpx
        # encodes the repeated key correctly.
        data={"mock_mode_enabled": ["0", "1"]},
    )
    assert r.status_code == 200
    assert "Saved" in r.text

    row = await db.fetch_one_raw(
        "SELECT mock_mode_enabled FROM governance.tool WHERE name = %(name)s",
        {"name": "checkbox_check_tool"},
    )
    assert row["mock_mode_enabled"] is True


# ── save handler — JSON parse errors ───────────────────────────────────────


async def test_save_handler_rejects_invalid_input_schema_json(
    studio_client, db,
):
    await make_tool(db, name="bad_input_schema_tool")

    r = await studio_client.post(
        "/studio/compose/tools/bad_input_schema_tool/save",
        data={"input_schema": "{this is not valid"},
    )
    assert r.status_code == 200
    body = r.text
    assert "Could not save" in body
    assert "input_schema" in body


async def test_save_handler_rejects_invalid_mock_responses_json(
    studio_client, db,
):
    await make_tool(db, name="bad_mock_resp_tool")

    r = await studio_client.post(
        "/studio/compose/tools/bad_mock_resp_tool/save",
        data={"mock_responses": "[unclosed"},
    )
    assert r.status_code == 200
    body = r.text
    assert "Could not save" in body
    assert "mock_responses" in body


# ── promoted-consumer warning ──────────────────────────────────────────────


async def test_detail_page_shows_warning_when_consumer_is_champion(
    studio_client, db,
):
    """When a champion agent_version authorises the tool, the edit
    page must surface the 'Promoted consumer' banner."""
    tool = await make_tool(db, name="warned_tool")
    bundle = await make_complete_agent(
        db, name="tool_warning_consumer", promote_to_champion=True,
        tools=[tool],
    )

    r = await studio_client.get("/studio/compose/tools/warned_tool")
    assert r.status_code == 200
    body = r.text
    assert "Promoted consumer" in body
    assert "tool_warning_consumer" in body
    assert "champion" in body.lower()


async def test_detail_page_omits_warning_when_no_promoted_consumer(
    studio_client, db,
):
    await make_tool(db, name="unused_tool")

    r = await studio_client.get("/studio/compose/tools/unused_tool")
    assert r.status_code == 200
    assert "Promoted consumer" not in r.text
