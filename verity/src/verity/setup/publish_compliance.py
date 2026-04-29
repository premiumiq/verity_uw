"""`verity compliance publish` — push the L2 mart + L3/L4/L5 metadata to MinIO
in a Guidewire-CDA-style folder hierarchy.

Bucket layout (S3-compatible):

    verity-data-hub/                                      (bucket)
    └── compliance/                                       (top-level dir)
        ├── _deployment.json                              (pointer to current deployment_id)
        └── <deployment_id>/                              (e.g. 2026-04-29T07-00-00Z)
            ├── manifest.json                             (cumulative; updated each publish)
            ├── ddl/
            │   ├── schema_compliance.sql
            │   └── schema_compliance_views.sql
            ├── metadata/
            │   ├── metamodel.yaml
            │   ├── reports.yaml
            │   └── feeds.yaml
            └── data/
                └── <view_name>/                          (one folder per table, e.g. v_decision)
                    └── <schema_fingerprint>/             (sha1 of column_name+type tuples;
                        │                                  schema evolution → new fingerprint)
                        └── <batch_timestamp>/            (epoch ms, one folder per publish run)
                            ├── page-0000.parquet
                            └── page-0001.parquet

Modeled on Guidewire CDA's S3 layout. Customer-side ingest:
  1. List `compliance/<deployment_id>/data/<view>/<fingerprint>/` to enumerate
     batch timestamps newer than what was already loaded.
  2. For each new batch, COPY INTO the warehouse target table from the parquet
     pages. Snowflake/BigQuery/Redshift/Iceberg all read parquet natively.
  3. The manifest.json at the deployment root is the authoritative inventory.

Architecture: docs/architecture/compliance-stack.md (Incremental Feed Rung 1).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg

# Heavy deps imported lazily inside main() so `--help` stays fast.


PAGE_SIZE = 1000

# MinIO + bucket defaults (env-overridable).
DEFAULT_ENDPOINT     = os.getenv("MINIO_ENDPOINT",     "localhost:9000")
DEFAULT_ACCESS_KEY   = os.getenv("MINIO_ACCESS_KEY",   "minioadmin")
DEFAULT_SECRET_KEY   = os.getenv("MINIO_SECRET_KEY",   "minioadmin123")
DEFAULT_SECURE       = os.getenv("MINIO_SECURE",       "false").lower() == "true"
DEFAULT_BUCKET       = os.getenv("VERITY_DATA_HUB_BUCKET", "verity-data-hub")

DEPLOYMENT_POINTER_KEY = "compliance/_deployment.json"


# =============================================================================
# YAML / JSON serialisation helpers (rich types from psycopg)
# =============================================================================

def _json_default(obj: Any) -> Any:
    """JSON encoder that handles UUID / datetime / Decimal."""
    if isinstance(obj, (UUID,)):
        return str(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"{type(obj).__name__} is not JSON-serializable")


def _yaml_dumper():
    """Lazy import; configures yaml SafeDumper to handle the rich types."""
    import yaml
    def _scalar(dumper, value):
        return dumper.represent_scalar("tag:yaml.org,2002:str", str(value))
    yaml.SafeDumper.add_representer(UUID, _scalar)
    yaml.SafeDumper.add_representer(datetime, _scalar)
    yaml.SafeDumper.add_representer(date, _scalar)
    yaml.SafeDumper.add_representer(Decimal, _scalar)
    return yaml


# =============================================================================
# MinIO helpers — small wrapper over the minio package
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
    """Upload an in-memory blob to MinIO."""
    client.put_object(
        bucket,
        key,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )


def _get_bytes(client, bucket: str, key: str) -> bytes | None:
    """Read an object; return None if it doesn't exist."""
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
# Deployment id — persisted at compliance/_deployment.json
# =============================================================================

def _resolve_deployment_id(client, bucket: str, force_new: bool) -> str:
    """Return the deployment_id to use. If `force_new` (or pointer absent),
    mint a new one and persist it."""
    if not force_new:
        existing = _get_bytes(client, bucket, DEPLOYMENT_POINTER_KEY)
        if existing:
            try:
                return json.loads(existing)["deployment_id"]
            except Exception:
                pass  # fall through and rewrite

    new_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    payload = json.dumps(
        {"deployment_id": new_id, "rotated_at": datetime.now(timezone.utc).isoformat()},
        indent=2,
    ).encode("utf-8")
    _put_bytes(client, bucket, DEPLOYMENT_POINTER_KEY, payload, "application/json")
    return new_id


# =============================================================================
# Schema fingerprint — sha1 over (column_name, column_type) tuples
# =============================================================================

def _schema_fingerprint(columns: list[tuple[str, str]]) -> str:
    """Stable hex fingerprint of a column list. Same schema → same hash;
    schema evolution → new hash → new folder, customer warehouse can detect
    the change without ambiguity."""
    s = ";".join(f"{name}:{ctype}" for name, ctype in columns)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


# =============================================================================
# Per-view publish — drains the view in pages, writes parquet to MinIO
# =============================================================================

async def _publish_view(
    conn,
    *,
    client,
    bucket: str,
    deployment_id: str,
    view_name: str,
    since_ts: datetime,
    until_ts: datetime,
    batch_ts: int,
) -> dict[str, Any]:
    """Drain one view in [since, until). Returns per-view summary for the
    manifest:
        {
          "view": "v_decision",
          "fingerprint": "8a3f2b1c4d5e6f70",
          "schema": [...],
          "batch_timestamp": "1714374000000",
          "row_count": 46,
          "page_count": 1,
          "key_prefix": "compliance/<deployment_id>/data/v_decision/<fp>/<batch_ts>/"
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

            # Compute fingerprint on the FIRST page; pyarrow infers schema.
            if schema is None:
                # Use Python type names from cur.description-like info; fall
                # back to value type. Postgres pg_type oids are stable but
                # we don't expose them here, so use sample-row Python types.
                first = rows[0]
                schema = [
                    (cols[i], type(first[i]).__name__ if first[i] is not None else "NoneType")
                    for i in range(len(cols))
                ]
                fp = _schema_fingerprint(schema)
                prefix = (
                    f"compliance/{deployment_id}/data/{view_name}/"
                    f"{fp}/{batch_ts}/"
                )

            # Build a pyarrow Table directly from row tuples + column names.
            # Convert UUID/datetime/Decimal to strings/ISO so parquet
            # serialisation works without bespoke pyarrow type registration.
            normalized = []
            for r in rows:
                normalized.append(tuple(_normalize_for_parquet(v) for v in r))
            arrays = list(zip(*normalized)) if normalized else [[] for _ in cols]
            table = pa.table({cols[i]: list(arrays[i]) for i in range(len(cols))})

            # Serialise to parquet in memory.
            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            payload = buf.getvalue()

            page_key = f"{prefix}page-{page_idx:04d}.parquet"
            _put_bytes(
                client, bucket, page_key, payload,
                content_type="application/x-parquet",
            )

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
        "batch_timestamp": str(batch_ts),
        "row_count":       total,
        "page_count":      page_idx,
        "key_prefix":      prefix or f"compliance/{deployment_id}/data/{view_name}/",
    }


def _normalize_for_parquet(v: Any) -> Any:
    """Convert types pyarrow can't auto-infer cleanly to strings."""
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
# Manifest — read existing, merge new batch, write back
# =============================================================================

def _manifest_key(deployment_id: str) -> str:
    return f"compliance/{deployment_id}/manifest.json"


def _load_manifest(client, bucket: str, deployment_id: str) -> dict[str, Any]:
    raw = _get_bytes(client, bucket, _manifest_key(deployment_id))
    if not raw:
        return {
            "deployment_id": deployment_id,
            "created_at":    datetime.now(timezone.utc).isoformat(),
            "batches":       [],
            "tables":        {},
        }
    return json.loads(raw)


def _save_manifest(client, bucket: str, manifest: dict[str, Any]) -> None:
    payload = json.dumps(manifest, indent=2, default=_json_default).encode("utf-8")
    _put_bytes(
        client, bucket,
        _manifest_key(manifest["deployment_id"]),
        payload,
        "application/json",
    )


# =============================================================================
# Side artefacts — DDL files + metamodel/reports/feeds YAML at the deployment
# root. Not part of the Guidewire pattern but useful for customer self-service.
# =============================================================================

def _publish_static_artifacts(client, bucket: str, deployment_id: str) -> None:
    pkg_root = Path(__file__).resolve().parent.parent

    # DDL files
    for fname in ("schema_compliance.sql", "schema_compliance_views.sql"):
        src = pkg_root / "db" / fname
        if src.exists():
            _put_bytes(
                client, bucket,
                f"compliance/{deployment_id}/ddl/{fname}",
                src.read_bytes(),
                "text/plain",
            )


async def _publish_metadata_yaml(conn, client, bucket: str, deployment_id: str) -> None:
    """Dump metamodel + reports + feeds to YAML in the bundle's metadata/ subdir."""
    yaml = _yaml_dumper()

    metamodel = await _dump_tables(conn, [
        ("frameworks",                "verity_compliance.regulatory_framework"),
        ("provisions",                "verity_compliance.regulatory_provision"),
        ("themes",                    "verity_compliance.canonical_requirement_theme"),
        ("canonical_requirements",    "verity_compliance.canonical_requirement"),
        ("provision_requirement_map", "verity_compliance.provision_requirement_map"),
        ("feature_planes",            "verity_compliance.feature_plane"),
        ("feature_capabilities",      "verity_compliance.feature_capability"),
        ("features",                  "verity_compliance.feature"),
        ("requirement_feature_link",  "verity_compliance.requirement_feature_link"),
        ("requirement_coverage",      "verity_compliance.requirement_coverage"),
    ])
    reports = await _dump_tables(conn, [
        ("mart_fields",                "verity_analytics.mart_field"),
        ("requirement_evidence_field", "verity_compliance.requirement_evidence_field"),
        ("report_definitions",         "verity_compliance.report_definition"),
        ("report_requirements",        "verity_compliance.report_requirement"),
    ])
    feeds = await _dump_tables(conn, [
        ("feed_views", "verity_analytics.feed_view"),
    ])

    for name, body in (("metamodel", metamodel), ("reports", reports), ("feeds", feeds)):
        body["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload = yaml.safe_dump(body, sort_keys=False, allow_unicode=True).encode("utf-8")
        _put_bytes(
            client, bucket,
            f"compliance/{deployment_id}/metadata/{name}.yaml",
            payload, "text/yaml",
        )


async def _dump_tables(conn, mappings: list[tuple[str, str]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, qualname in mappings:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT * FROM {qualname}")
            cols = [d.name for d in cur.description] if cur.description else []
            out[key] = [
                {cols[i]: v for i, v in enumerate(row)} for row in await cur.fetchall()
            ]
    return out


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
    new_deployment: bool = False,
) -> dict[str, Any]:
    # Lazy ISO parsing using the same helpers as the API.
    from verity.web.api.feed import _parse_iso

    since_ts = _parse_iso(since) if since else _parse_iso("1970-01-01T00:00:00Z")
    until_ts = _parse_iso(until) if until else datetime.now(timezone.utc).replace(tzinfo=None)
    if until_ts <= since_ts:
        raise ValueError(f"until ({until_ts}) must be > since ({since_ts})")

    client = _minio_client(endpoint, access_key, secret_key, secure)
    _ensure_bucket(client, bucket)

    deployment_id = _resolve_deployment_id(client, bucket, force_new=new_deployment)
    batch_ts = int(time.time() * 1000)
    print(f"  bucket:        {bucket}")
    print(f"  deployment_id: {deployment_id}")
    print(f"  batch_ts:      {batch_ts}")
    print(f"  window:        {since_ts.isoformat()} → {until_ts.isoformat()}")
    print()

    async with await psycopg.AsyncConnection.connect(database_url, autocommit=True) as conn:
        # Side artefacts (DDL + metadata) — re-published on every run because
        # they're cheap and they're the consumer's bootstrap material.
        _publish_static_artifacts(client, bucket, deployment_id)
        await _publish_metadata_yaml(conn, client, bucket, deployment_id)

        # Discover feedable views from the registry.
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT view_name FROM verity_analytics.feed_view
                WHERE is_active = true
                ORDER BY sort_seq, view_name
                """
            )
            view_names = [r[0] for r in await cur.fetchall()]

        # Per-view publish.
        per_view: list[dict[str, Any]] = []
        for view_name in view_names:
            print(f"  publishing {view_name} ...", flush=True)
            summary = await _publish_view(
                conn,
                client=client, bucket=bucket,
                deployment_id=deployment_id,
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

    # Update manifest cumulatively.
    manifest = _load_manifest(client, bucket, deployment_id)
    batch_record = {
        "batch_timestamp": str(batch_ts),
        "since":           since_ts.isoformat(),
        "until":           until_ts.isoformat(),
        "row_total":       sum(v["row_count"] for v in per_view),
        "views":           per_view,
    }
    manifest["batches"].append(batch_record)
    # Track the latest fingerprint per view, so customers can spot evolution
    # by comparing against the prior manifest.
    for v in per_view:
        manifest["tables"].setdefault(v["view"], {"fingerprints": {}})
        fp = v["fingerprint"]
        manifest["tables"][v["view"]]["fingerprints"].setdefault(fp, {
            "schema": v["schema"],
            "batches": [],
        })
        manifest["tables"][v["view"]]["fingerprints"][fp]["batches"].append({
            "batch_timestamp": v["batch_timestamp"],
            "row_count":       v["row_count"],
            "page_count":      v["page_count"],
            "key_prefix":      v["key_prefix"],
        })
    manifest["last_updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_manifest(client, bucket, manifest)

    return {
        "deployment_id": deployment_id,
        "batch_ts":      str(batch_ts),
        "bucket":        bucket,
        "manifest_key":  _manifest_key(deployment_id),
        "views":         per_view,
    }


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m verity.setup.publish_compliance <database_url> "
            "[--bucket NAME] [--since ISO] [--until ISO] [--new-deployment]"
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
        elif args[i] == "--new-deployment":
            kwargs["new_deployment"] = True; i += 1
        else:
            print(f"Unknown arg: {args[i]!r}"); sys.exit(2)

    result = asyncio.run(publish_bundle(db_url, **kwargs))
    print()
    print(f"Done. deployment_id={result['deployment_id']}  batch_ts={result['batch_ts']}")
    print(f"Manifest: s3://{result['bucket']}/{result['manifest_key']}")


if __name__ == "__main__":
    main()
