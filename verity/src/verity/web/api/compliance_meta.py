"""Verity Compliance — bootstrap-material endpoints.

The data bucket carries only Parquet + manifest. The DDL files and
metamodel/reports/feeds YAMLs that customer warehouses need to BOOTSTRAP
their stack are served here, on demand, from the running Verity API.

Endpoints:
    GET /api/v1/compliance/manifest                 — proxy to bucket manifest.json
    GET /api/v1/compliance/metamodel.yaml           — frameworks, provisions,
                                                       canonicals, bridges,
                                                       coverage, features
    GET /api/v1/compliance/reports.yaml             — mart_field, evidence
                                                       fields, report defs
    GET /api/v1/compliance/feeds.yaml               — feed_view registry
    GET /api/v1/compliance/ddl/{filename}           — DDL .sql files
                                                       (allowlist of names only)
"""

from __future__ import annotations

import io
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, Response


# Allowlist of DDL files that may be served (path-traversal safety).
DDL_ALLOWLIST = {
    "schema_compliance.sql",
    "schema_compliance_views.sql",
}


def _yaml_dumper():
    """Configure yaml.SafeDumper for our rich types."""
    import yaml
    def _scalar(d, v):
        return d.represent_scalar("tag:yaml.org,2002:str", str(v))
    yaml.SafeDumper.add_representer(UUID, _scalar)
    yaml.SafeDumper.add_representer(datetime, _scalar)
    yaml.SafeDumper.add_representer(date, _scalar)
    yaml.SafeDumper.add_representer(Decimal, _scalar)
    return yaml


# =============================================================================
# Router
# =============================================================================

def build_compliance_meta_router(verity) -> APIRouter:
    router = APIRouter(prefix="/compliance", tags=["compliance-meta"])

    # ── bucket manifest passthrough ─────────────────────────────
    @router.get("/manifest")
    async def get_manifest():
        """Return the cumulative bucket manifest as JSON."""
        from minio import Minio
        from minio.error import S3Error

        endpoint   = os.getenv("MINIO_ENDPOINT",   "minio:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
        secure     = os.getenv("MINIO_SECURE", "false").lower() == "true"
        bucket     = os.getenv("VERITY_DATA_HUB_BUCKET", "verity-data-hub")

        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        try:
            resp = client.get_object(bucket, "compliance/manifest.json")
            try:
                payload = resp.read()
            finally:
                resp.close()
                resp.release_conn()
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "No manifest.json yet. Run `verity compliance publish` "
                        "to populate the bucket."
                    ),
                )
            raise

        return Response(content=payload, media_type="application/json")

    # ── on-demand metamodel YAML ────────────────────────────────
    @router.get("/metamodel.yaml")
    async def get_metamodel_yaml():
        await verity.ensure_connected()
        body = await _dump_metamodel(verity)
        return _yaml_response(body)

    @router.get("/reports.yaml")
    async def get_reports_yaml():
        await verity.ensure_connected()
        body = await _dump_reports(verity)
        return _yaml_response(body)

    @router.get("/feeds.yaml")
    async def get_feeds_yaml():
        await verity.ensure_connected()
        body = await _dump_feeds(verity)
        return _yaml_response(body)

    # ── DDL files ───────────────────────────────────────────────
    @router.get("/ddl/{filename}")
    async def get_ddl(filename: str):
        if filename not in DDL_ALLOWLIST:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Unknown DDL file {filename!r}. "
                    f"Available: {sorted(DDL_ALLOWLIST)}"
                ),
            )
        # Resolved relative to the verity package: db/<filename>
        pkg_root = Path(__file__).resolve().parents[2]
        path = pkg_root / "db" / filename
        if not path.is_file():
            raise HTTPException(
                status_code=500,
                detail=f"Server misconfiguration: {path} not found.",
            )
        return PlainTextResponse(
            content=path.read_text(encoding="utf-8"),
            media_type="text/x-sql",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    return router


# =============================================================================
# YAML response helpers
# =============================================================================

def _yaml_response(body: dict[str, Any]) -> Response:
    yaml = _yaml_dumper()
    body["generated_at"] = datetime.utcnow().isoformat() + "Z"
    payload = yaml.safe_dump(body, sort_keys=False, allow_unicode=True)
    return Response(
        content=payload,
        media_type="application/x-yaml",
    )


async def _fetch_dicts(verity, sql: str) -> list[dict]:
    return await verity.db.fetch_all_raw(sql, {})


async def _dump_metamodel(verity) -> dict[str, Any]:
    return {
        "frameworks":                 await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.regulatory_framework ORDER BY sort_seq, code"),
        "provisions":                 await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.regulatory_provision ORDER BY framework_id, sort_seq"),
        "themes":                     await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.canonical_requirement_theme ORDER BY sort_seq, code"),
        "canonical_requirements":     await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.canonical_requirement ORDER BY sort_seq, code"),
        "provision_requirement_map":  await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.provision_requirement_map"),
        "feature_planes":             await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.feature_plane ORDER BY sort_seq, code"),
        "feature_capabilities":       await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.feature_capability ORDER BY sort_seq, code"),
        "features":                   await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.feature ORDER BY capability_id, sort_seq, code"),
        "requirement_feature_link":   await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.requirement_feature_link"),
        "requirement_coverage":       await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.requirement_coverage"),
    }


async def _dump_reports(verity) -> dict[str, Any]:
    return {
        "mart_fields":                  await _fetch_dicts(verity,
            "SELECT * FROM verity_analytics.mart_field ORDER BY table_name, sort_seq"),
        "requirement_evidence_field":   await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.requirement_evidence_field"),
        "report_definitions":           await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.report_definition ORDER BY sort_seq, code"),
        "report_requirements":          await _fetch_dicts(verity,
            "SELECT * FROM verity_compliance.report_requirement"),
    }


async def _dump_feeds(verity) -> dict[str, Any]:
    return {
        "feed_views": await _fetch_dicts(verity,
            "SELECT view_name AS view, description, sort_seq, is_active "
            "FROM verity_analytics.feed_view "
            "WHERE is_active = true "
            "ORDER BY sort_seq, view_name"),
    }
