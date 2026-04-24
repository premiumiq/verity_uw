"""Translate legacy task-only wiring rows into the unified-wiring tables.

Old shape (still in schema for the migration window):
    task_version_source   — one row per task pre-prompt input fetch
    task_version_target   — one row per task post-output write

New shape (Phase A added these tables):
    source_binding        — one row per (owner_kind, owner_id, template_var)
                            with a `reference` string in the wiring DSL
    write_target          — one row per declared output write
    target_payload_field  — one row per key in the payload dict

This migration walks every legacy row and inserts the equivalent in the
new tables. It does NOT drop the legacy tables — the engine still reads
them until the runtime is refactored to read the unified tables.

Translation rules:
  task_version_source(input_field_name='document_ref',
                      connector_name='edms',
                      fetch_method='get_document_text',
                      maps_to_template_var='document_text',
                      required=True, execution_order=1)
   ──►
  source_binding(owner_kind='task_version', owner_id=<task_version_id>,
                 template_var='document_text',
                 reference='fetch:edms/get_document_text(input.document_ref)',
                 required=True, execution_order=1)

  task_version_target(output_field_name='extracted_fields',
                      connector_id=<edms_id>,
                      write_method='create_document',
                      target_container=NULL,
                      required=False, execution_order=1)
   ──►
  write_target(owner_kind='task_version', owner_id=<task_version_id>,
               name='extracted_fields',  -- reuse field name as logical target name
               connector_id=<edms_id>, write_method='create_document',
               container=NULL, required=False, execution_order=1)
  target_payload_field(write_target_id=<new>, payload_field='data',
                       reference='output.extracted_fields',
                       required=True, execution_order=1)

The single-key 'data' wrapping is a convention — the legacy runtime sent
the raw output value as the payload; the new runtime always sends a
dict. Provider implementations get a 'data' key to unwrap.

Idempotent: each insert checks for an existing row with the same unique
key (owner_kind+owner_id+template_var for source_binding;
owner_kind+owner_id+name for write_target) and skips if present.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row


async def _fetch(conn: psycopg.AsyncConnection, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params or {})
        return await cur.fetchall()


async def _exists(conn: psycopg.AsyncConnection, sql: str, params: dict[str, Any]) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()
        return row is not None


async def _migrate_sources(conn: psycopg.AsyncConnection) -> tuple[int, int]:
    """Migrate task_version_source rows into source_binding.

    Returns (total_legacy_rows, rows_inserted_this_run).
    """
    legacy = await _fetch(
        conn,
        """
        SELECT tvs.task_version_id,
               tvs.input_field_name,
               tvs.fetch_method,
               tvs.maps_to_template_var,
               tvs.required,
               tvs.execution_order,
               tvs.description,
               dc.name AS connector_name
        FROM task_version_source tvs
        JOIN data_connector dc ON dc.id = tvs.connector_id
        ORDER BY tvs.task_version_id, tvs.execution_order
        """,
    )
    inserted = 0
    for row in legacy:
        # Build the reference string in the wiring DSL.
        reference = (
            f"fetch:{row['connector_name']}/{row['fetch_method']}"
            f"(input.{row['input_field_name']})"
        )
        # Skip if a binding with this key already exists (idempotent).
        already = await _exists(
            conn,
            """
            SELECT 1 FROM source_binding
            WHERE owner_kind = %s AND owner_id = %s AND template_var = %s
            """,
            ("task_version", row["task_version_id"], row["maps_to_template_var"]),
        )
        if already:
            continue
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO source_binding (
                    owner_kind, owner_id, template_var, reference,
                    required, execution_order, description
                ) VALUES (
                    'task_version', %s, %s, %s,
                    %s, %s, %s
                )
                """,
                (
                    row["task_version_id"],
                    row["maps_to_template_var"],
                    reference,
                    row["required"],
                    row["execution_order"],
                    row["description"],
                ),
            )
        inserted += 1
    return len(legacy), inserted


async def _migrate_targets(conn: psycopg.AsyncConnection) -> tuple[int, int, int]:
    """Migrate task_version_target rows into write_target + target_payload_field.

    Returns (total_legacy_rows, write_targets_inserted, payload_fields_inserted).
    """
    legacy = await _fetch(
        conn,
        """
        SELECT tvt.task_version_id,
               tvt.output_field_name,
               tvt.connector_id,
               tvt.write_method,
               tvt.target_container,
               tvt.required,
               tvt.execution_order,
               tvt.description
        FROM task_version_target tvt
        ORDER BY tvt.task_version_id, tvt.execution_order
        """,
    )
    targets_inserted = 0
    fields_inserted = 0
    for row in legacy:
        # Skip if a write_target with this (owner, name) already exists.
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id FROM write_target
                WHERE owner_kind = 'task_version'
                  AND owner_id = %s
                  AND name = %s
                """,
                (row["task_version_id"], row["output_field_name"]),
            )
            existing = await cur.fetchone()
        if existing:
            write_target_id = existing["id"]
        else:
            # Insert new write_target. Returning the id so we can attach
            # the payload field row.
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO write_target (
                        owner_kind, owner_id, name,
                        connector_id, write_method, container,
                        required, execution_order, description
                    ) VALUES (
                        'task_version', %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        row["task_version_id"],
                        row["output_field_name"],
                        row["connector_id"],
                        row["write_method"],
                        row["target_container"],
                        row["required"],
                        row["execution_order"],
                        row["description"],
                    ),
                )
                new_row = await cur.fetchone()
            write_target_id = new_row["id"]
            targets_inserted += 1

        # Skip the payload_field insert if already present.
        already_field = await _exists(
            conn,
            """
            SELECT 1 FROM target_payload_field
            WHERE write_target_id = %s AND payload_field = %s
            """,
            (write_target_id, "data"),
        )
        if already_field:
            continue
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO target_payload_field (
                    write_target_id, payload_field, reference,
                    required, execution_order
                ) VALUES (
                    %s, 'data', %s,
                    TRUE, 1
                )
                """,
                (write_target_id, f"output.{row['output_field_name']}"),
            )
        fields_inserted += 1
    return len(legacy), targets_inserted, fields_inserted


async def _print_sample(conn: psycopg.AsyncConnection) -> None:
    """Print a few before/after rows so the operator can eyeball them."""
    print("\n--- Sample translations ---")
    legacy_sources = await _fetch(
        conn,
        """
        SELECT tvs.task_version_id, tvs.input_field_name,
               tvs.maps_to_template_var, tvs.fetch_method,
               dc.name AS connector_name
        FROM task_version_source tvs
        JOIN data_connector dc ON dc.id = tvs.connector_id
        LIMIT 3
        """,
    )
    for row in legacy_sources:
        sb_match = await _fetch(
            conn,
            """
            SELECT template_var, reference
            FROM source_binding
            WHERE owner_kind = 'task_version'
              AND owner_id = %(tv)s
              AND template_var = %(tv_name)s
            """,
            {"tv": row["task_version_id"], "tv_name": row["maps_to_template_var"]},
        )
        if sb_match:
            print(
                f"  source: tv={row['task_version_id']} "
                f"{row['input_field_name']}->{row['maps_to_template_var']} "
                f"=> {sb_match[0]['reference']}"
            )

    legacy_targets = await _fetch(
        conn,
        """
        SELECT task_version_id, output_field_name, write_method
        FROM task_version_target
        LIMIT 3
        """,
    )
    for row in legacy_targets:
        wt_match = await _fetch(
            conn,
            """
            SELECT wt.id, wt.name, wt.write_method,
                   tpf.payload_field, tpf.reference
            FROM write_target wt
            LEFT JOIN target_payload_field tpf
                ON tpf.write_target_id = wt.id
            WHERE wt.owner_kind = 'task_version'
              AND wt.owner_id = %(tv)s
              AND wt.name = %(name)s
            """,
            {"tv": row["task_version_id"], "name": row["output_field_name"]},
        )
        if wt_match:
            entry = wt_match[0]
            print(
                f"  target: tv={row['task_version_id']} "
                f"{row['output_field_name']}/{row['write_method']} "
                f"=> write_target.name={entry['name']}, "
                f"payload[{entry['payload_field']}]={entry['reference']}"
            )


async def migrate(database_url: str) -> None:
    """Run the migration against the given database. Idempotent."""
    print(f"Connecting to {database_url.split('@')[-1]} ...")
    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=False
    ) as conn:
        # Fail fast if either set of new tables is missing — this script
        # only makes sense after the Phase A schema is applied.
        for required_table in (
            "source_binding",
            "write_target",
            "target_payload_field",
        ):
            ok = await _exists(
                conn,
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=%s",
                (required_table,),
            )
            if not ok:
                print(f"ERROR: required table '{required_table}' is missing. "
                      "Apply the Phase A schema before running this migration.")
                sys.exit(2)

        print("\n=== Migrating task_version_source -> source_binding ===")
        legacy_sources, sb_inserted = await _migrate_sources(conn)
        print(f"  legacy rows: {legacy_sources}")
        print(f"  inserted   : {sb_inserted}")

        print("\n=== Migrating task_version_target -> write_target + target_payload_field ===")
        legacy_targets, wt_inserted, tpf_inserted = await _migrate_targets(conn)
        print(f"  legacy rows         : {legacy_targets}")
        print(f"  write_targets added : {wt_inserted}")
        print(f"  payload_fields added: {tpf_inserted}")

        # Final counts for verification.
        print("\n--- Final counts (post-migration) ---")
        async with conn.cursor() as cur:
            for table in (
                "task_version_source",
                "source_binding",
                "task_version_target",
                "write_target",
                "target_payload_field",
            ):
                await cur.execute(f"SELECT COUNT(*) FROM {table}")
                row = await cur.fetchone()
                print(f"  {table:30s} {row[0]}")

        await _print_sample(conn)
        await conn.commit()
        print("\nMigration committed. Old tables retained — drop in a "
              "follow-up commit after the runtime is refactored to read "
              "the unified-wiring tables.")


def main() -> None:
    db_url = os.environ.get("VERITY_DB_URL")
    if not db_url:
        print("ERROR: VERITY_DB_URL not set in environment.")
        sys.exit(2)
    asyncio.run(migrate(db_url))


if __name__ == "__main__":
    main()
