"""`verity compliance publish` — push the L2 mart to MinIO in an
Iceberg-style continuous layout (no deployment wrapper).

Bucket layout (S3-compatible):

    verity-data-hub/
    └── compliance/
        ├── manifest.json                                 (top-level; cumulative)
        └── <view_name>/                                  (one folder per table; lives forever)
            └── <schema_fingerprint>/                     (sha1 of column_name+type tuples;
                │                                          schema evolution → new fingerprint)
                └── <batch_timestamp>/                    (epoch ms, one per publish run)
                    ├── page-0000.parquet
                    └── page-0001.parquet

Customer-side ingest:
  - Snowflake / Iceberg / BigQuery point an external table or stage at
    s3://verity-data-hub/compliance/<view_name>/ and treat fingerprint +
    batch_timestamp as partition columns.
  - The table prefix never changes — wire it once.
  - Each publish drops new <batch_timestamp> folders; customer warehouse
    incrementally loads anything newer than what they've already ingested.
  - A new fingerprint subfolder appears only when the schema changes.

DDL + metamodel YAMLs are served via /api/v1/compliance/* endpoints, NOT
in the data bucket — the bucket stays pure data + manifest.

Architecture: docs/architecture/compliance-stack.md (Incremental Feed Rung 1).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg


PAGE_SIZE = 1000


def _batch_timestamp() -> str:
    """ISO-8601 UTC timestamp, S3-path-safe.

    Colons aren't valid in some S3 client tooling and create surprises in
    Hive-style partition parsing; we replace colons and the millisecond dot
    with hyphens. Keeps lexicographic sort order, stays human-readable,
    and Iceberg / Delta / Snowflake external tables all read this fine.

    Examples:
      2026-04-29T07-59-15-720Z   (millisecond resolution)
    """
    now = datetime.now(timezone.utc)
    iso = now.isoformat(timespec="milliseconds")  # 2026-04-29T07:59:15.720+00:00
    return (
        iso.replace("+00:00", "Z")
           .replace(":", "-")
           .replace(".", "-")
    )

# MinIO + bucket defaults (env-overridable).
DEFAULT_ENDPOINT     = os.getenv("MINIO_ENDPOINT",     "localhost:9000")
DEFAULT_ACCESS_KEY   = os.getenv("MINIO_ACCESS_KEY",   "minioadmin")
DEFAULT_SECRET_KEY   = os.getenv("MINIO_SECRET_KEY",   "minioadmin123")
DEFAULT_SECURE       = os.getenv("MINIO_SECURE",       "false").lower() == "true"
DEFAULT_BUCKET       = os.getenv("VERITY_DATA_HUB_BUCKET", "verity-data-hub")

MANIFEST_KEY = "compliance/manifest.json"


# =============================================================================
# JSON serialisation helpers
# =============================================================================

def _json_default(obj: Any) -> Any:
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON-serializable")


# =============================================================================
# MinIO helpers
# =============================================================================

def _minio_client(
    endpoint: str = DEFAULT_ENDPOINT,
    access_key: str = DEFAULT_ACCESS_KEY,
    secret_key: str = DEFAULT_SECRET_KEY,
    secure: bool = DEFAULT_SECURE,
):
    from minio import Minio
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def _ensure_bucket(client, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def _put_bytes(client, bucket: str, key: str, payload: bytes, content_type: str) -> None:
    client.put_object(
        bucket, key,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )


def _get_bytes(client, bucket: str, key: str) -> bytes | None:
    from minio.error import S3Error
    try:
        resp = client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchObject"):
            return None
        raise


# =============================================================================
# Schema fingerprint
# =============================================================================

def _schema_fingerprint(columns: list[tuple[str, str]]) -> str:
    """Stable hex fingerprint of a column list. Same schema → same hash;
    schema evolution → new hash → new folder under the table."""
    s = ";".join(f"{name}:{ctype}" for name, ctype in columns)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


# =============================================================================
# Per-view publish
# =============================================================================

async def _publish_view(
    conn,
    *,
    client,
    bucket: str,
    view_name: str,
    since_ts: datetime,
    until_ts: datetime,
    batch_ts: str,
) -> dict[str, Any]:
    """Drain one view in [since, until) into Parquet pages on MinIO.

    Returns a per-view summary suitable for the manifest:
        {
          "view":            "v_decision",
          "fingerprint":     "8a3f2b1c4d5e6f70",
          "schema":          [{"name": ..., "py_type": ...}, ...],
          "batch_timestamp": "2026-04-29T07-59-15-720Z",
          "row_count":       46,
          "page_count":      1,
          "key_prefix":      "compliance/v_decision/<fp>/<batch_ts>/"
        }
    """
    import pyarrow as pa  # type: ignore
    import pyarrow.parquet as pq  # type: ignore

    keyset_ts = since_ts
    keyset_pk = ""
    page_idx  = 0
    total     = 0
    schema:  list[tuple[str, str]] | None = None
    fp:      str | None = None
    prefix:  str | None = None

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
            cols_meta = cur.description or []
            cols      = [d.name for d in cols_meta]
            rows      = await cur.fetchall()
            if not rows:
                break

            # Compute fingerprint on the first page; pyarrow infers schema.
            if schema is None:
                first = rows[0]
                schema = [
                    (cols[i], type(first[i]).__name__ if first[i] is not None else "NoneType")
                    for i in range(len(cols))
                ]
                fp = _schema_fingerprint(schema)
                # Iceberg-style continuous layout — table folder lives at
                # compliance/<view_name>/, no deployment wrapper.
                prefix = f"compliance/{view_name}/{fp}/{batch_ts}/"

            # Normalise rich types and build a pyarrow Table.
            normalized = [
                tuple(_normalize_for_parquet(v) for v in r) for r in rows
            ]
            arrays = list(zip(*normalized))
            table = pa.table({cols[i]: list(arrays[i]) for i in range(len(cols))})

            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            payload = buf.getvalue()

            page_key = f"{prefix}page-{page_idx:04d}.parquet"
            _put_bytes(client, bucket, page_key, payload, "application/x-parquet")

            total += len(rows)
            page_idx += 1
            if len(rows) < PAGE_SIZE:
                break

            last = rows[-1]
            keyset_ts = last[cols.index("ingest_ts")]
            sp = last[cols.index("source_pk")] if "source_pk" in cols else None
            keyset_pk = sp if sp is not None else ""

    return {
        "view":            view_name,
        "fingerprint":     fp or "—",
        "schema":          [{"name": n, "py_type": t} for n, t in (schema or [])],
        "batch_timestamp": batch_ts,
        "row_count":       total,
        "page_count":      page_idx,
        "key_prefix":      prefix or f"compliance/{view_name}/",
    }


def _normalize_for_parquet(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=_json_default)
    return v


# =============================================================================
# Manifest — cumulative top-level inventory
# =============================================================================

def _load_manifest(client, bucket: str) -> dict[str, Any]:
    raw = _get_bytes(client, bucket, MANIFEST_KEY)
    if not raw:
        return {
            "schema_version": 1,
            "created_at":     datetime.now(timezone.utc).isoformat(),
            "last_updated_at": None,
            "batches":        [],
            "tables":         {},
        }
    return json.loads(raw)


def _save_manifest(client, bucket: str, manifest: dict[str, Any]) -> None:
    payload = json.dumps(manifest, indent=2, default=_json_default).encode("utf-8")
    _put_bytes(client, bucket, MANIFEST_KEY, payload, "application/json")


# =============================================================================
# Top-level driver
# =============================================================================

async def publish_bundle(
    database_url: str,
    *,
    bucket: str = DEFAULT_BUCKET,
    endpoint: str = DEFAULT_ENDPOINT,
    access_key: str = DEFAULT_ACCESS_KEY,
    secret_key: str = DEFAULT_SECRET_KEY,
    secure: bool = DEFAULT_SECURE,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    from verity.web.api.feed import _parse_iso

    since_ts = _parse_iso(since) if since else _parse_iso("1970-01-01T00:00:00Z")
    until_ts = _parse_iso(until) if until else datetime.now(timezone.utc).replace(tzinfo=None)
    if until_ts <= since_ts:
        raise ValueError(f"until ({until_ts}) must be > since ({since_ts})")

    client = _minio_client(endpoint, access_key, secret_key, secure)
    _ensure_bucket(client, bucket)

    batch_ts = _batch_timestamp()
    print(f"  bucket:    {bucket}")
    print(f"  batch_ts:  {batch_ts}")
    print(f"  window:    {since_ts.isoformat()} → {until_ts.isoformat()}")
    print()

    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT view_name FROM verity_analytics.feed_view
                WHERE is_active = true
                ORDER BY sort_seq, view_name
                """
            )
            view_names = [r[0] for r in await cur.fetchall()]

        per_view: list[dict[str, Any]] = []
        for view_name in view_names:
            print(f"  publishing {view_name} ...", flush=True)
            summary = await _publish_view(
                conn,
                client=client, bucket=bucket,
                view_name=view_name,
                since_ts=since_ts, until_ts=until_ts,
                batch_ts=batch_ts,
            )
            per_view.append(summary)
            print(
                f"     {summary['row_count']} row(s) in "
                f"{summary['page_count']} page(s)  fp={summary['fingerprint']}",
                flush=True,
            )

    # Cumulative manifest update.
    manifest = _load_manifest(client, bucket)
    manifest["batches"].append({
        "batch_timestamp": batch_ts,
        "since":           since_ts.isoformat(),
        "until":           until_ts.isoformat(),
        "row_total":       sum(v["row_count"] for v in per_view),
        "views":           per_view,
    })
    for v in per_view:
        manifest["tables"].setdefault(v["view"], {"fingerprints": {}})
        fp = v["fingerprint"]
        bucket_view = manifest["tables"][v["view"]]
        if fp not in bucket_view["fingerprints"]:
            bucket_view["fingerprints"][fp] = {
                "schema":         v["schema"],
                "first_seen_at":  datetime.now(timezone.utc).isoformat(),
                "batches":        [],
            }
        bucket_view["fingerprints"][fp]["batches"].append({
            "batch_timestamp": v["batch_timestamp"],
            "row_count":       v["row_count"],
            "page_count":      v["page_count"],
            "key_prefix":      v["key_prefix"],
        })
    manifest["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_manifest(client, bucket, manifest)

    return {
        "batch_ts":     str(batch_ts),
        "bucket":       bucket,
        "manifest_key": MANIFEST_KEY,
        "views":        per_view,
    }


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m verity.setup.publish_compliance <database_url> "
            "[--bucket NAME] [--since ISO] [--until ISO]"
        )
        sys.exit(2)
    db_url = sys.argv[1]
    args = sys.argv[2:]

    kwargs: dict[str, Any] = {}
    i = 0
    while i < len(args):
        if args[i] == "--bucket" and i + 1 < len(args):
            kwargs["bucket"] = args[i + 1]; i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            kwargs["since"] = args[i + 1]; i += 2
        elif args[i] == "--until" and i + 1 < len(args):
            kwargs["until"] = args[i + 1]; i += 2
        else:
            print(f"Unknown arg: {args[i]!r}"); sys.exit(2)

    result = asyncio.run(publish_bundle(db_url, **kwargs))
    print()
    print(f"Done. batch_ts={result['batch_ts']}")
    print(f"Manifest: s3://{result['bucket']}/{result['manifest_key']}")


if __name__ == "__main__":
    main()
