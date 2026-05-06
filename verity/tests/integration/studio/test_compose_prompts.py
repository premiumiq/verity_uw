"""Compose-mode prompt browse + edit pages.

These tests drive the Studio sub-app over the per-test cloned DB.
They cover:

  * Read-only browse: /compose/prompts (list) and detail page.
  * Edit page gating: only draft versions get a form; non-draft
    versions redirect back to detail.
  * Save handler: optimistic-concurrency happy path, stale-stamp
    conflict path, lifecycle conflict path.
  * Where-used panel: surfaces consumers with their lifecycle states.
"""

from __future__ import annotations

import re

from tests.fixtures.builders import (
    assign_prompt,
    make_complete_agent,
    make_prompt,
    make_prompt_version,
    promote,
)


async def _promote_prompt_version(db, prompt_version_id, to_state: str) -> None:
    """Move a prompt_version into a non-draft state.

    The shared ``promote()`` builder only knows about Agent/Task
    versions; prompts have their own row but the lifecycle column is
    the same shape. Update it directly here rather than expanding the
    builder.
    """
    await db.execute_raw(
        """
        UPDATE governance.prompt_version
        SET lifecycle_state = %(state)s
        WHERE id = %(id)s::uuid
        """,
        {"id": str(prompt_version_id), "state": to_state},
    )


# ── browse ─────────────────────────────────────────────────────────────────


async def test_prompts_list_renders_existing_prompts(studio_client, db):
    """The browse page shows every prompt's name, with a clickable row
    that navigates to the detail page."""
    await make_prompt(db, name="studio_browse_a")
    await make_prompt(db, name="studio_browse_b")

    r = await studio_client.get("/studio/compose/prompts")
    assert r.status_code == 200
    body = r.text
    assert "studio_browse_a" in body
    assert "studio_browse_b" in body
    # Click target — the row's onclick navigates to detail.
    assert "/studio/compose/prompts/studio_browse_a" in body


async def test_prompt_detail_shows_versions_and_edit_link_for_draft(
    studio_client, db,
):
    """Detail page lists every version with role/tier/state. Drafts
    get an Edit link; non-drafts get a Clone-to-Draft form."""
    prompt = await make_prompt(db, name="detail_test_prompt")
    draft_v = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="Draft content.",
    )
    promoted_v = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=0, minor_version=9, patch_version=0,
        content="Older promoted content.",
    )
    await _promote_prompt_version(db, promoted_v.id, to_state="candidate")

    r = await studio_client.get("/studio/compose/prompts/detail_test_prompt")
    assert r.status_code == 200
    body = r.text
    assert "1.0.0" in body
    assert "0.9.0" in body

    # Draft has an Edit link to the right URL.
    edit_url = (
        f"/studio/compose/prompts/detail_test_prompt"
        f"/versions/{draft_v.id}/edit"
    )
    assert edit_url in body
    # Non-draft version does NOT have an Edit link.
    no_edit_url = (
        f"/studio/compose/prompts/detail_test_prompt"
        f"/versions/{promoted_v.id}/edit"
    )
    assert no_edit_url not in body
    # Non-draft version DOES have a Clone-to-Draft form posting at
    # the matching URL.
    clone_action = (
        f"/studio/compose/prompts/detail_test_prompt"
        f"/versions/{promoted_v.id}/clone-to-draft"
    )
    assert clone_action in body
    assert "Clone to Draft" in body


async def test_prompt_detail_404_for_missing_prompt(studio_client, db):
    r = await studio_client.get("/studio/compose/prompts/no_such_prompt")
    assert r.status_code == 404


# ── edit page gating ───────────────────────────────────────────────────────


async def test_edit_page_renders_form_for_draft_version(studio_client, db):
    """The edit page surfaces a textarea for content, hidden
    ``expected_updated_at`` field, and an HTMX-bound save button."""
    prompt = await make_prompt(db, name="edit_form_prompt")
    pv = await make_prompt_version(
        db, prompt_id=prompt.id,
        content="System prompt body.",
    )

    r = await studio_client.get(
        f"/studio/compose/prompts/edit_form_prompt/versions/{pv.id}/edit",
    )
    assert r.status_code == 200
    body = r.text
    assert "System prompt body." in body
    # Form posts to the save handler via HTMX.
    assert "hx-post=" in body
    assert f"/studio/compose/prompts/edit_form_prompt/versions/{pv.id}/save" in body
    # Hidden stamp for optimistic concurrency.
    assert 'name="expected_updated_at"' in body


async def test_edit_page_redirects_when_version_is_not_draft(
    studio_client, db,
):
    """Promoted versions are immutable. The edit URL must redirect
    back to the detail page rather than render an editable form."""
    prompt = await make_prompt(db, name="edit_redirect_prompt")
    pv = await make_prompt_version(db, prompt_id=prompt.id)
    await _promote_prompt_version(db, pv.id, to_state="candidate")

    r = await studio_client.get(
        f"/studio/compose/prompts/edit_redirect_prompt/versions/{pv.id}/edit",
    )
    # httpx follows redirects by default; we want to inspect the
    # raw response.
    assert r.status_code in (303, 307) or r.url.path.endswith(
        "/studio/compose/prompts/edit_redirect_prompt"
    )


# ── save handler — happy path ──────────────────────────────────────────────


async def test_save_handler_returns_ok_partial_when_stamp_matches(
    studio_client, db,
):
    """Save with the matching stamp succeeds and returns the 'Saved.'
    partial with a fresh updated_at."""
    prompt = await make_prompt(db, name="save_ok_prompt")
    pv = await make_prompt_version(
        db, prompt_id=prompt.id,
        content="Original content.",
    )

    # First read the edit page to capture the current stamp.
    edit_resp = await studio_client.get(
        f"/studio/compose/prompts/save_ok_prompt/versions/{pv.id}/edit",
    )
    assert edit_resp.status_code == 200
    stamp_match = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    )
    assert stamp_match is not None
    stamp = stamp_match.group(1)
    assert stamp, "Stamp must be non-empty for the optimistic-concurrency test"

    # Save with that stamp.
    save_resp = await studio_client.post(
        f"/studio/compose/prompts/save_ok_prompt/versions/{pv.id}/save",
        data={
            "content": "Updated content.",
            "change_summary": "Tweaked.",
            "api_role": "system",
            "governance_tier": "behavioural",
            "author_name": "tester",
            "expected_updated_at": stamp,
        },
    )
    assert save_resp.status_code == 200, save_resp.text
    # Response is the success partial.
    assert "Saved" in save_resp.text
    # Sanity — DB row really changed.
    row = await db.fetch_one_raw(
        "SELECT content FROM governance.prompt_version WHERE id = %(id)s",
        {"id": str(pv.id)},
    )
    assert row["content"] == "Updated content."


# ── save handler — stale-stamp conflict ────────────────────────────────────


async def test_save_handler_returns_conflict_partial_on_stale_stamp(
    studio_client, db,
):
    """Saving with a stamp that's been advanced by a concurrent save
    must return the conflict partial (NOT silently overwrite)."""
    prompt = await make_prompt(db, name="save_conflict_prompt")
    pv = await make_prompt_version(
        db, prompt_id=prompt.id,
        content="Initial.",
    )

    # Both clients read — they see the same stamp.
    edit_resp = await studio_client.get(
        f"/studio/compose/prompts/save_conflict_prompt/versions/{pv.id}/edit",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    # Client B saves first.
    first = await studio_client.post(
        f"/studio/compose/prompts/save_conflict_prompt/versions/{pv.id}/save",
        data={
            "content": "Client B saved this.",
            "change_summary": "B got there first.",
            "api_role": "system",
            "governance_tier": "behavioural",
            "expected_updated_at": stamp,
        },
    )
    assert first.status_code == 200

    # Client A saves with the now-stale stamp.
    second = await studio_client.post(
        f"/studio/compose/prompts/save_conflict_prompt/versions/{pv.id}/save",
        data={
            "content": "Client A's stale save.",
            "change_summary": "A.",
            "api_role": "system",
            "governance_tier": "behavioural",
            "expected_updated_at": stamp,
        },
    )
    assert second.status_code == 200  # the partial endpoint returns 200
    body = second.text
    assert "Stale save" in body, (
        f"Expected the stale-save conflict partial, got: {body[:300]}"
    )

    # The DB row has client B's content, not A's — overwrite was prevented.
    row = await db.fetch_one_raw(
        "SELECT content FROM governance.prompt_version WHERE id = %(id)s",
        {"id": str(pv.id)},
    )
    assert row["content"] == "Client B saved this."


# ── save handler — lifecycle conflict ──────────────────────────────────────


async def test_save_handler_returns_error_partial_when_no_longer_draft(
    studio_client, db,
):
    """If the version was promoted out of draft between page load and
    save, the partial reports the lifecycle change (not a stale_write)."""
    prompt = await make_prompt(db, name="save_lifecycle_prompt")
    pv = await make_prompt_version(db, prompt_id=prompt.id, content="Pre-promote.")

    edit_resp = await studio_client.get(
        f"/studio/compose/prompts/save_lifecycle_prompt/versions/{pv.id}/edit",
    )
    stamp = re.search(
        r'name="expected_updated_at"\s+value="([^"]+)"', edit_resp.text,
    ).group(1)

    # Promote the version BEFORE the user's save lands.
    await _promote_prompt_version(db, pv.id, to_state="candidate")

    save_resp = await studio_client.post(
        f"/studio/compose/prompts/save_lifecycle_prompt/versions/{pv.id}/save",
        data={
            "content": "Tried to edit after promotion.",
            "change_summary": "x.",
            "api_role": "system",
            "governance_tier": "behavioural",
            "expected_updated_at": stamp,
        },
    )
    assert save_resp.status_code == 200
    body = save_resp.text
    assert "candidate" in body.lower() or "clone" in body.lower(), (
        f"Expected the lifecycle-conflict error, got: {body[:300]}"
    )


# ── where-used panel ───────────────────────────────────────────────────────


# ── clone-to-draft ─────────────────────────────────────────────────────────


async def test_clone_to_draft_creates_new_draft_and_redirects_to_edit(
    studio_client, db,
):
    """The headline use case: a champion prompt has no draft.
    Clicking Clone to Draft creates one and lands the user on the
    edit page for it."""
    prompt = await make_prompt(db, name="clone_target_prompt")
    src_v = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
        content="Champion content.",
    )
    await _promote_prompt_version(db, src_v.id, to_state="champion")

    # Don't follow the redirect — assert on it directly.
    r = await studio_client.post(
        f"/studio/compose/prompts/clone_target_prompt/versions/{src_v.id}/clone-to-draft",
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert "/edit" in location
    assert "/clone_target_prompt/versions/" in location

    # The new draft exists in the DB and has a higher patch number.
    new_drafts = await db.fetch_all_raw(
        """
        SELECT id, version_label, lifecycle_state, content
        FROM governance.prompt_version
        WHERE prompt_id = %(pid)s::uuid
          AND lifecycle_state = 'draft'
        """,
        {"pid": str(prompt.id)},
    )
    assert len(new_drafts) == 1
    assert new_drafts[0]["version_label"] == "1.0.1"
    # Content carried over from source.
    assert new_drafts[0]["content"] == "Champion content."

    # Following the redirect lands on the edit form for the new draft.
    follow = await studio_client.get(location)
    assert follow.status_code == 200
    assert 'name="content"' in follow.text
    assert "Champion content." in follow.text


async def test_clone_to_draft_picks_next_free_patch_when_one_exists(
    studio_client, db,
):
    """Auto-bump must skip slots that already exist — re-cloning a
    champion that's been cloned before should produce a fresh label."""
    prompt = await make_prompt(db, name="clone_skip_prompt")
    src_v = await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=0,
    )
    await _promote_prompt_version(db, src_v.id, to_state="champion")
    # 1.0.1 already taken by a prior clone.
    await make_prompt_version(
        db, prompt_id=prompt.id,
        major_version=1, minor_version=0, patch_version=1,
    )

    r = await studio_client.post(
        f"/studio/compose/prompts/clone_skip_prompt/versions/{src_v.id}/clone-to-draft",
        follow_redirects=False,
    )
    assert r.status_code == 303

    drafts = await db.fetch_all_raw(
        """
        SELECT version_label
        FROM governance.prompt_version
        WHERE prompt_id = %(pid)s::uuid
          AND lifecycle_state = 'draft'
        ORDER BY version_label
        """,
        {"pid": str(prompt.id)},
    )
    labels = [d["version_label"] for d in drafts]
    # 1.0.1 already existed (not a draft); the new clone was 1.0.2.
    assert "1.0.2" in labels


# ── where-used panel ───────────────────────────────────────────────────────


async def test_where_used_panel_lists_consumers_with_lifecycle_state(
    studio_client, db,
):
    """The where-used panel must surface every consumer's
    lifecycle_state — that's the safe-edit signal."""
    prompt = await make_prompt(db, name="where_used_prompt")
    pv = await make_prompt_version(db, prompt_id=prompt.id)

    bundle = await make_complete_agent(
        db, name="where_used_consumer", promote_to_champion=True,
    )
    await assign_prompt(db, entity_version=bundle.version, prompt_version=pv)

    r = await studio_client.get(f"/studio/compose/prompts/where_used_prompt")
    assert r.status_code == 200
    body = r.text
    # Consumer's name appears.
    assert "where_used_consumer" in body
    # Champion lifecycle state appears (it's how the editor would
    # eventually decide whether to gate edits).
    assert "champion" in body.lower()
