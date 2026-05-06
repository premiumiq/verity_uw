"""Compose-mode inference-config browse + edit pages.

Configs are unversioned, so the test surface is simpler than prompts:
list, edit page (which is the same URL as the detail page), save
handler. Tests cover:

  * Read-only browse: list shows every active config.
  * Edit form: every editable field is rendered with the current
    value and the optimistic-concurrency stamp.
  * Save handler: happy-path stamp match, stale-stamp conflict, JSON
    parse errors on extended_params, numeric parse errors.
  * Promoted-consumer warning: rendered when at least one consumer
    is in champion or challenger.
"""

from __future__ import annotations

import re

from tests.fixtures.builders import (
    make_agent_version,
    make_complete_agent,
    make_inference_config,
)


# ── browse ─────────────────────────────────────────────────────────────────


async def test_configs_list_renders_existing_configs(studio_client, db):
    """The browse page surfaces the seeded configs plus any added
    during the test."""
    cfg = await make_inference_config(db, name="studio_browse_config")

    r = await studio_client.get("/studio/compose/configs")
    assert r.status_code == 200
    body = r.text
    assert "studio_browse_config" in body
    # The clickable row navigates to the edit page.
    assert "/studio/compose/configs/studio_browse_config" in body


async def test_config_detail_404_for_missing(studio_client, db):
    r = await studio_client.get("/studio/compose/configs/no_such_config")
    assert r.status_code == 404


# ── edit page ──────────────────────────────────────────────────────────────


async def test_config_detail_renders_form_with_current_values(
    studio_client, db,
):
    """All editable fields appear in the form pre-populated with the
    current row values."""
    await make_inference_config(
        db,
        name="form_render_config",
        display_name="Form Render Config",
        model_name="claude-sonnet-4-20250514",
        temperature=0.5,
        max_tokens=2048,
    )

    r = await studio_client.get("/studio/compose/configs/form_render_config")
    assert r.status_code == 200
    body = r.text
    # Form posts to the save handler via HTMX.
    assert "hx-post=" in body
    assert "/studio/compose/configs/form_render_config/save" in body
    # Hidden stamp is present.
    assert 'name="expected_updated_at"' in body
    # Current values are visible in the rendered form.
    assert "Form Render Config" in body
    assert "claude-sonnet-4-20250514" in body
    # Temperature comes back as Decimal('0.5'); accept either form.
    assert ("0.5" in body) or ("0.500" in body)


# ── save handler — happy path ──────────────────────────────────────────────


async def test_save_handler_returns_ok_partial_when_stamp_matches(
    studio_client, db,
):
    """Save with the matching stamp succeeds, returns the 'Saved.'
    partial, and the DB row reflects the new values."""
    cfg = await make_inference_config(
        db,
        name="save_happy_config",
        display_name="Original Display",
        temperature=0.0,
    )

    edit_resp = await studio_client.get(
        "/studio/compose/configs/save_happy_config",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    save_resp = await studio_client.post(
        "/studio/compose/configs/save_happy_config/save",
        data={
            "display_name": "Updated Display",
            "model_name": "claude-sonnet-4-20250514",
            "description": "Updated description.",
            "intended_use": "",
            "temperature": "0.7",
            "max_tokens": "8192",
            "top_p": "",
            "top_k": "",
            "stop_sequences": "",
            "extended_params": "",
            "expected_updated_at": stamp,
        },
    )
    assert save_resp.status_code == 200, save_resp.text
    assert "Saved" in save_resp.text

    # DB reflects the change.
    row = await db.fetch_one_raw(
        """
        SELECT display_name, model_name, temperature, max_tokens
        FROM governance.inference_config
        WHERE name = %(name)s
        """,
        {"name": "save_happy_config"},
    )
    assert row["display_name"] == "Updated Display"
    assert row["model_name"] == "claude-sonnet-4-20250514"
    # Numeric column comes back as Decimal — coerce for comparison.
    assert float(row["temperature"]) == 0.7
    assert row["max_tokens"] == 8192


# ── save handler — stale-stamp conflict ────────────────────────────────────


async def test_save_handler_returns_conflict_partial_on_stale_stamp(
    studio_client, db,
):
    """Saving with a stamp that's been advanced returns the conflict
    partial and the DB row keeps the winning save's content."""
    await make_inference_config(
        db, name="save_conflict_config",
        display_name="Initial",
    )

    edit_resp = await studio_client.get(
        "/studio/compose/configs/save_conflict_config",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    # Client B saves first.
    first = await studio_client.post(
        "/studio/compose/configs/save_conflict_config/save",
        data={
            "display_name": "Client B's display",
            "model_name": "claude-sonnet-4-20250514",
            "expected_updated_at": stamp,
        },
    )
    assert first.status_code == 200
    assert "Saved" in first.text

    # Client A tries to save with the now-stale stamp.
    second = await studio_client.post(
        "/studio/compose/configs/save_conflict_config/save",
        data={
            "display_name": "Client A's display",
            "model_name": "claude-sonnet-4-20250514",
            "expected_updated_at": stamp,
        },
    )
    assert second.status_code == 200
    body = second.text
    assert "Stale save" in body, (
        f"Expected the stale-save partial, got: {body[:300]}"
    )

    # DB has client B's content.
    row = await db.fetch_one_raw(
        "SELECT display_name FROM governance.inference_config WHERE name = %(name)s",
        {"name": "save_conflict_config"},
    )
    assert row["display_name"] == "Client B's display"


# ── save handler — parse errors ────────────────────────────────────────────


async def test_save_handler_rejects_non_numeric_temperature(
    studio_client, db,
):
    """Non-numeric temperature returns the error partial with a
    helpful message — the user shouldn't see a 500 or a stack trace."""
    await make_inference_config(db, name="parse_error_config")

    r = await studio_client.post(
        "/studio/compose/configs/parse_error_config/save",
        data={"temperature": "very hot"},
    )
    assert r.status_code == 200
    body = r.text
    assert "Could not save" in body
    assert "temperature" in body.lower()


async def test_save_handler_rejects_invalid_extended_params_json(
    studio_client, db,
):
    """extended_params must be valid JSON; a parse failure surfaces
    via the error partial."""
    await make_inference_config(db, name="bad_json_config")

    r = await studio_client.post(
        "/studio/compose/configs/bad_json_config/save",
        data={"extended_params": "{this is not :: json"},
    )
    assert r.status_code == 200
    body = r.text
    assert "Could not save" in body
    assert "json" in body.lower()


# ── save handler — list-shaped fields ──────────────────────────────────────


async def test_save_handler_parses_stop_sequences_from_textarea(
    studio_client, db,
):
    """The textarea sends one stop sequence per line; the handler
    must turn that into a TEXT[] column update."""
    await make_inference_config(db, name="stop_seq_config")

    r = await studio_client.post(
        "/studio/compose/configs/stop_seq_config/save",
        data={
            "stop_sequences": "STOP\n<|end|>\n  END  ",
        },
    )
    assert r.status_code == 200
    assert "Saved" in r.text

    row = await db.fetch_one_raw(
        "SELECT stop_sequences FROM governance.inference_config WHERE name = %(name)s",
        {"name": "stop_seq_config"},
    )
    # Whitespace-only lines and outer whitespace stripped.
    assert row["stop_sequences"] == ["STOP", "<|end|>", "END"]


# ── promoted-consumer warning ──────────────────────────────────────────────


async def test_detail_page_shows_warning_when_consumer_is_champion(
    studio_client, db,
):
    """When a champion agent_version references the config, the
    edit page must surface a clear warning that saving has a
    production-blast-radius. (Saving is still allowed — configs
    don't have a clone-to-draft alternative.)"""
    bundle = await make_complete_agent(
        db, name="config_warning_consumer", promote_to_champion=True,
    )
    # The make_complete_agent default uses the seeded test config.
    # Look up its name so we know what URL to hit.
    cfg_row = await db.fetch_one_raw(
        """
        SELECT ic.name
        FROM governance.inference_config ic
        JOIN governance.agent_version av ON av.inference_config_id = ic.id
        WHERE av.id = %(id)s::uuid
        """,
        {"id": str(bundle.version.id)},
    )
    assert cfg_row is not None
    cfg_name = cfg_row["name"]

    r = await studio_client.get(f"/studio/compose/configs/{cfg_name}")
    assert r.status_code == 200
    body = r.text
    # Warning about promoted consumer.
    assert "Promoted consumer" in body
    # Where-used panel surfaces the consumer name + lifecycle state.
    assert "config_warning_consumer" in body
    assert "champion" in body.lower()


async def test_detail_page_omits_warning_when_no_promoted_consumer(
    studio_client, db,
):
    """An unused config (no consumers) shows no warning — the form
    is editable cleanly."""
    cfg = await make_inference_config(db, name="unused_config")

    r = await studio_client.get(f"/studio/compose/configs/unused_config")
    assert r.status_code == 200
    body = r.text
    assert "Promoted consumer" not in body
