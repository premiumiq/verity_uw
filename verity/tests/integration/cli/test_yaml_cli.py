"""Verity CLI — ``export``, ``import``, ``diff`` subcommands.

These tests call the async handler functions directly with a
hand-built ``argparse.Namespace`` rather than invoking the full
``main()`` argparse machinery. The handlers are the interesting
unit; ``main()`` is just argparse plumbing.

Output capture uses pytest's ``capsys`` fixture. The handlers write
status messages to stderr and the bundle YAML / diff body to stdout,
so callers can pipe stdout to a file in shell scripts.
"""

from __future__ import annotations

import argparse
import io
import textwrap
from pathlib import Path

import pytest
import yaml

from tests.fixtures.builders import make_complete_agent
from verity.cli import _run_yaml_diff, _run_yaml_export, _run_yaml_import


# ── verity export ───────────────────────────────────────────────────────────


async def test_export_writes_yaml_to_stdout_when_no_output_flag(
    capsys, db,
):
    """``verity export agent foo`` with no -o writes YAML to stdout."""
    bundle_setup = await make_complete_agent(
        db, name="cli_export_agent", promote_to_champion=False,
    )
    args = argparse.Namespace(
        kind="agent",
        name="cli_export_agent",
        version=None,
        database_url=db.database_url,
        output=None,
    )

    rc = await _run_yaml_export(args)
    assert rc == 0

    captured = capsys.readouterr()
    parsed = yaml.safe_load(captured.out)
    assert parsed["apiVersion"] == "studio.verity.ai/v1"
    kinds = [e["kind"] for e in parsed["entities"]]
    assert "Agent" in kinds


async def test_export_writes_yaml_to_file_when_output_flag_given(
    capsys, db, tmp_path,
):
    """``verity export -o foo.yaml`` writes to a file and prints a
    short status line to stderr."""
    await make_complete_agent(
        db, name="cli_export_to_file", promote_to_champion=False,
    )
    out_path = tmp_path / "bundle.yaml"
    args = argparse.Namespace(
        kind="agent",
        name="cli_export_to_file",
        version=None,
        database_url=db.database_url,
        output=str(out_path),
    )

    rc = await _run_yaml_export(args)
    assert rc == 0
    assert out_path.exists()
    contents = out_path.read_text()
    assert "kind: Agent" in contents

    captured = capsys.readouterr()
    # Stdout is empty (we wrote to file); status goes to stderr.
    assert captured.out == ""
    assert "Wrote" in captured.err


async def test_export_returns_nonzero_for_missing_entity(capsys, db):
    """A name that doesn't exist in the DB returns exit code 1, not 0,
    so CI scripts can detect typos."""
    args = argparse.Namespace(
        kind="agent",
        name="does_not_exist",
        version=None,
        database_url=db.database_url,
        output=None,
    )
    rc = await _run_yaml_export(args)
    assert rc == 1
    captured = capsys.readouterr()
    assert "No agent found" in captured.err


async def test_export_rejects_version_flag_for_unversioned_kind(capsys, db):
    """``--version`` only makes sense for agent/task/prompt; passing
    it with kind=tool is a usage error (exit 2)."""
    args = argparse.Namespace(
        kind="tool",
        name="some_tool",
        version="1.0.0",
        database_url=db.database_url,
        output=None,
    )
    rc = await _run_yaml_export(args)
    assert rc == 2
    captured = capsys.readouterr()
    assert "version" in captured.err.lower()


# ── verity import ───────────────────────────────────────────────────────────


_MINIMAL_TOOL_YAML = textwrap.dedent("""\
    apiVersion: studio.verity.ai/v1
    kind: Bundle
    entities:
    - kind: Tool
      name: cli_imported_tool
      display_name: CLI Imported Tool
      description: Inserted via the CLI import handler.
      transport: python_inprocess
      implementation_path: x.y.cli_imported
      input_schema:
        type: object
      output_schema:
        type: object
""")


async def test_import_from_file_inserts_entities(capsys, db, tmp_path):
    """Reading from a file path persists the bundle and prints a
    summary."""
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(_MINIMAL_TOOL_YAML)

    args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )

    rc = await _run_yaml_import(args)
    assert rc == 0

    captured = capsys.readouterr()
    assert "Imported" in captured.out
    assert "cli_imported_tool" in captured.out

    # The row actually exists in the DB.
    row = await db.fetch_one_raw(
        "SELECT name FROM governance.tool WHERE name = %(name)s",
        {"name": "cli_imported_tool"},
    )
    assert row is not None


async def test_import_from_stdin_inserts_entities(capsys, db, monkeypatch):
    """Reading from stdin (no file argument) works the same as from a
    file — supports the ``cat foo.yaml | verity import`` pipeline."""
    monkeypatch.setattr("sys.stdin", io.StringIO(_MINIMAL_TOOL_YAML))

    args = argparse.Namespace(
        file=None,
        database_url=db.database_url,
    )

    rc = await _run_yaml_import(args)
    assert rc == 0
    captured = capsys.readouterr()
    assert "cli_imported_tool" in captured.out


async def test_import_reports_validation_errors_and_exits_one(
    capsys, db, tmp_path,
):
    """Dangling references → exit 1 with structured errors on stderr.
    Use exit 1 so a CI script can distinguish 'bundle wrong' from
    'usage wrong' (exit 2)."""
    bad_yaml = textwrap.dedent("""\
        apiVersion: studio.verity.ai/v1
        kind: Bundle
        entities:
        - kind: Agent
          name: cli_dangling_agent
          display_name: Dangling
          description: References a missing config.
          versions:
          - version_label: 1.0.0
            change_summary: Initial.
            inference_config: not_a_real_config
    """)
    bundle_path = tmp_path / "bad.yaml"
    bundle_path.write_text(bad_yaml)

    args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )
    rc = await _run_yaml_import(args)
    assert rc == 1

    captured = capsys.readouterr()
    assert "Validation failed" in captured.err
    assert "dangling_reference" in captured.err
    assert "not_a_real_config" in captured.err


async def test_import_returns_two_for_unparseable_yaml(capsys, db, tmp_path):
    """Yaml parse errors are usage-class problems (the file is wrong)
    so they exit 2, distinct from validation failures (exit 1)."""
    bad = tmp_path / "broken.yaml"
    bad.write_text("[unclosed\n")

    args = argparse.Namespace(
        file=str(bad),
        database_url=db.database_url,
    )
    rc = await _run_yaml_import(args)
    assert rc == 2

    captured = capsys.readouterr()
    assert "parse" in captured.err.lower()


# ── verity diff ─────────────────────────────────────────────────────────────


async def test_diff_reports_create_actions_for_missing_entities(
    capsys, db, tmp_path,
):
    """``verity diff`` lists what an import would create against the
    current DB. With nothing pre-existing for our bundle's tool name,
    the diff says CREATE."""
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(_MINIMAL_TOOL_YAML)

    args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )
    rc = await _run_yaml_diff(args)
    assert rc == 0

    captured = capsys.readouterr()
    assert "Would CREATE" in captured.out
    assert "cli_imported_tool" in captured.out


async def test_diff_reports_skip_for_existing_entities(
    capsys, db, tmp_path,
):
    """After importing once, a second diff run should report SKIP for
    every entity instead of CREATE."""
    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text(_MINIMAL_TOOL_YAML)

    # Import first.
    import_args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )
    rc = await _run_yaml_import(import_args)
    assert rc == 0
    capsys.readouterr()  # discard

    # Now diff — everything should be SKIP.
    diff_args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )
    rc = await _run_yaml_diff(diff_args)
    assert rc == 0

    captured = capsys.readouterr()
    assert "Would SKIP" in captured.out
    assert "Would CREATE" not in captured.out


async def test_diff_with_validation_error_exits_one(capsys, db, tmp_path):
    """A dangling-reference bundle can't be diffed meaningfully —
    surface the validation errors and exit 1."""
    bad_yaml = textwrap.dedent("""\
        apiVersion: studio.verity.ai/v1
        kind: Bundle
        entities:
        - kind: Agent
          name: diff_dangling
          display_name: Dangling
          description: d
          versions:
          - version_label: 1.0.0
            change_summary: Initial.
            inference_config: not_a_real_config
    """)
    bundle_path = tmp_path / "bad.yaml"
    bundle_path.write_text(bad_yaml)

    args = argparse.Namespace(
        file=str(bundle_path),
        database_url=db.database_url,
    )
    rc = await _run_yaml_diff(args)
    assert rc == 1

    captured = capsys.readouterr()
    assert "validation error" in captured.err.lower()
