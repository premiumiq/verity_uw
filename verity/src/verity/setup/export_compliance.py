"""`verity export-compliance` — bundle the L2 mart + L3 metamodel + L4/L5
artifacts for customer-warehouse ingest.

Produces a directory of:
    ddl/verity_analytics.sql       — recreate the views in the customer DB
    ddl/verity_compliance.sql      — the metamodel + reports tables
    metamodel.yaml                 — frameworks, provisions, canonicals,
                                     bridges, coverage, features
    reports.yaml                   — mart_field, evidence fields, report
                                     definitions, report requirements
    feeds.yaml                     — feed_view registry
    data/{view}/page-NNNN.jsonl    — one or more JSONL pages per view in
                                     [since, until). Same shape and order
                                     as /api/v1/feed returns.
    manifest.json                  — what's inside, with row counts + window

Customer-side: reapply DDL, load metamodel.yaml + reports.yaml + feeds.yaml,
COPY INTO each fact view from the JSONL pages. The same shape can be lifted
to Iceberg or Parquet later (Phase 5+) without breaking customer ingest.

Architecture: docs/architecture/compliance-stack.md (Incremental Feed Rung 1).
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import yaml


# YAML can't natively serialise UUID/datetime/Decimal — add representers
# so dumps don't crash on the rich types we get from psycopg.
def _yaml_str(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(value))


yaml.SafeDumper.add_representer(UUID,     _yaml_str)
yaml.SafeDumper.add_representer(datetime, _yaml_str)
yaml.SafeDumper.add_representer(date,     _yaml_str)
try:
    from decimal import Decimal
    yaml.SafeDumper.add_representer(Decimal, _yaml_str)
except ImportError:
    pass


# Reuse the encode/decode + parse helpers from the API to keep the cursor
# format identical between the HTTP endpoint and this CLI.
from verity.web.api.feed import (  # noqa: E402
    encode_cursor,  # not used here directly but kept for symmetry
    _parse_iso,
)

DEFAULT_SINCE = "1970-01-01T00:00:00Z"
PAGE_SIZE = 1000


# =============================================================================
# Top-level driver
# =============================================================================

async def export_bundle(
    database_url: str,
    out_dir: Path,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Write a complete bundle to `out_dir` and return a manifest dict."""
    out_dir = Path(out_dir)
    (out_dir / "ddl").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    since_ts = _parse_iso(since or DEFAULT_SINCE)
    until_ts = _parse_iso(until) if until else datetime.now(timezone.utc).replace(tzinfo=None)
    if until_ts <= since_ts:
        raise ValueError(f"until ({until_ts}) must be > since ({since_ts})")

    # Locate the schema files inside the verity package.
    pkg_root = Path(__file__).resolve().parent.parent
    (out_dir / "ddl" / "schema_compliance.sql").write_bytes(
        (pkg_root / "db" / "schema_compliance.sql").read_bytes()
    )
    (out_dir / "ddl" / "schema_compliance_views.sql").write_bytes(
        (pkg_root / "db" / "schema_compliance_views.sql").read_bytes()
    )

    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
        # ---- L3 + L4/L5 metamodel (YAML, easy to diff/re-ingest) ----
        metamodel = await _dump_metamodel(conn)
        (out_dir / "metamodel.yaml").write_text(
            yaml.safe_dump(metamodel, sort_keys=False, allow_unicode=True)
        )

        reports = await _dump_reports_metadata(conn)
        (out_dir / "reports.yaml").write_text(
            yaml.safe_dump(reports, sort_keys=False, allow_unicode=True)
        )

        feeds = await _dump_feed_registry(conn)
        (out_dir / "feeds.yaml").write_text(
            yaml.safe_dump(feeds, sort_keys=False, allow_unicode=True)
        )

        # ---- Data pages, one view at a time ----
        view_summaries: list[dict[str, Any]] = []
        for fv in feeds["feed_views"]:
            view = fv["view"]
            print(f"  exporting {view} ...", flush=True)
            view_dir = out_dir / "data" / view
            view_dir.mkdir(parents=True, exist_ok=True)
            row_total, page_total = await _export_view_pages(
                conn, view, since_ts, until_ts, view_dir
            )
            view_summaries.append({
                "view":       view,
                "row_count":  row_total,
                "page_count": page_total,
            })
            print(f"     {row_total} row(s) in {page_total} page(s)", flush=True)

    manifest = {
        "tool":        "verity export-compliance",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "since":       since_ts.isoformat(),
        "until":       until_ts.isoformat(),
        "page_size":   PAGE_SIZE,
        "views":       view_summaries,
        "files": {
            "ddl":       ["ddl/schema_compliance.sql", "ddl/schema_compliance_views.sql"],
            "metamodel": "metamodel.yaml",
            "reports":   "reports.yaml",
            "feeds":     "feeds.yaml",
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    return manifest


# =============================================================================
# View → JSONL pages (mirror of the /api/v1/feed/{view} contract)
# =============================================================================

async def _export_view_pages(
    conn,
    view_name: str,
    since_ts: datetime,
    until_ts: datetime,
    out_dir: Path,
) -> tuple[int, int]:
    """Drain one view in [since, until) into JSONL pages."""
    keyset_ts = since_ts
    keyset_pk = ""
    page_idx  = 0
    total     = 0

    while True:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT * FROM verity_analytics.{view_name}
                WHERE (ingest_ts, COALESCE(source_pk, '')) > (%(ts)s, %(pk)s)
                  AND ingest_ts < %(until)s
                ORDER BY ingest_ts ASC, source_pk ASC
                LIMIT {PAGE_SIZE}
                """,
                {"ts": keyset_ts, "pk": keyset_pk, "until": until_ts},
            )
            cols = [d.name for d in cur.description] if cur.description else []
            rows = await cur.fetchall()
            if not rows:
                return total, page_idx

            page_path = out_dir / f"page-{page_idx:04d}.jsonl"
            with page_path.open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(
                        json.dumps(dict(zip(cols, r)), default=str)
                    )
                    fh.write("\n")
            total += len(rows)
            page_idx += 1

            if len(rows) < PAGE_SIZE:
                return total, page_idx

            # Advance keyset cursor.
            last = dict(zip(cols, rows[-1]))
            keyset_ts = last["ingest_ts"]
            keyset_pk = last.get("source_pk") or ""


# =============================================================================
# YAML dumps of the metamodel
# =============================================================================

async def _fetch_dicts(conn, sql: str, params: dict | None = None) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(sql, params or {})
        cols = [d.name for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in await cur.fetchall()]


async def _dump_metamodel(conn) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "frameworks": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.regulatory_framework ORDER BY sort_seq, code",
        ),
        "provisions": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.regulatory_provision ORDER BY framework_id, sort_seq",
        ),
        "themes": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.canonical_requirement_theme ORDER BY sort_seq, code",
        ),
        "canonical_requirements": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.canonical_requirement ORDER BY sort_seq, code",
        ),
        "provision_requirement_map": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.provision_requirement_map",
        ),
        "feature_planes": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.feature_plane ORDER BY sort_seq, code",
        ),
        "feature_capabilities": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.feature_capability ORDER BY sort_seq, code",
        ),
        "features": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.feature ORDER BY capability_id, sort_seq, code",
        ),
        "requirement_feature_link": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.requirement_feature_link",
        ),
        "requirement_coverage": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.requirement_coverage",
        ),
    }


async def _dump_reports_metadata(conn) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mart_fields": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_analytics.mart_field ORDER BY table_name, sort_seq",
        ),
        "requirement_evidence_field": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.requirement_evidence_field",
        ),
        "report_definitions": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.report_definition ORDER BY sort_seq, code",
        ),
        "report_requirements": await _fetch_dicts(
            conn,
            "SELECT * FROM verity_compliance.report_requirement",
        ),
    }


async def _dump_feed_registry(conn) -> dict[str, Any]:
    rows = await _fetch_dicts(
        conn,
        """
        SELECT view_name AS view, description, sort_seq, is_active
        FROM verity_analytics.feed_view
        WHERE is_active = true
        ORDER BY sort_seq, view_name
        """,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "feed_views":   rows,
    }


# =============================================================================
# CLI dispatcher (callable as `python -m verity.setup.export_compliance ...`)
# =============================================================================

def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m verity.setup.export_compliance <database_url> <out_dir> [--since ISO] [--until ISO]")
        sys.exit(2)
    db_url  = sys.argv[1]
    out_dir = Path(sys.argv[2])

    since: str | None = None
    until: str | None = None
    args = sys.argv[3:]
    i = 0
    while i < len(args):
        if args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]; i += 2
        elif args[i] == "--until" and i + 1 < len(args):
            until = args[i + 1]; i += 2
        else:
            print(f"Unknown arg: {args[i]!r}")
            sys.exit(2)

    print(f"Exporting compliance bundle to {out_dir}")
    print(f"  since = {since or DEFAULT_SINCE}")
    print(f"  until = {until or '(now)'}")
    manifest = asyncio.run(export_bundle(db_url, out_dir, since=since, until=until))
    total = sum(v["row_count"] for v in manifest["views"])
    print()
    print(f"Done. {total} total row(s) across {len(manifest['views'])} view(s).")
    print(f"Manifest: {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
