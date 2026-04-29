"""Seed the L3 compliance metamodel from a YAML manifest.

Phase 1.2: static seeds (frameworks, themes, feature hierarchy).
Phase 1.3 will add a separate seeder for provisions / canonical
requirements / bridges / coverage from compliance_seed_data.yaml.

Idempotent — UPSERTs by natural code, so editing the YAML and
re-running this seeder is safe.

Architecture: docs/architecture/compliance-stack.md
Build plan:   docs/plans/compliance-build-plan.md
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import psycopg
import yaml


STATIC_SEED_FILE = Path(__file__).parent / "compliance_seed_static.yaml"
DATA_SEED_FILE = Path(__file__).parent / "compliance_seed_data.yaml"
REPORTS_SEED_FILE = Path(__file__).parent / "compliance_seed_reports.yaml"


# =============================================================================
# Seed entry points
# =============================================================================


async def seed_static(database_url: str) -> dict[str, int]:
    """Seed frameworks, themes, planes, capabilities, features, and the
    embedding_config row. Idempotent.

    Returns a counts dict so the CLI can print a summary.
    """
    data = yaml.safe_load(STATIC_SEED_FILE.read_text())

    counts = {
        "embedding_config": 0,
        "frameworks": 0,
        "themes": 0,
        "feature_planes": 0,
        "feature_capabilities": 0,
        "features": 0,
    }

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=False
    ) as conn:
        async with conn.cursor() as cur:
            counts["embedding_config"] = await _seed_embedding_config(
                cur, data["embedding_config"]
            )
            counts["frameworks"] = await _seed_frameworks(cur, data["frameworks"])
            counts["themes"] = await _seed_themes(cur, data["themes"])
            (
                counts["feature_planes"],
                counts["feature_capabilities"],
                counts["features"],
            ) = await _seed_feature_hierarchy(cur, data["feature_planes"])
        await conn.commit()

    return counts


# =============================================================================
# Seeders, one per top-level node
# =============================================================================


async def _seed_embedding_config(cur: psycopg.AsyncCursor, cfg: dict[str, Any]) -> int:
    """Idempotent: only insert if no current config row exists for this model+version."""
    await cur.execute(
        """
        SELECT id FROM verity_compliance.embedding_config
        WHERE model_name = %s AND model_version = %s AND is_current = true
        """,
        (cfg["model_name"], cfg["model_version"]),
    )
    row = await cur.fetchone()
    if row:
        return 0

    # Demote any other current row before inserting.
    await cur.execute(
        "UPDATE verity_compliance.embedding_config SET is_current = false "
        "WHERE is_current = true"
    )
    await cur.execute(
        """
        INSERT INTO verity_compliance.embedding_config
            (model_name, model_version, dim, runtime, is_current)
        VALUES (%s, %s, %s, %s, true)
        """,
        (
            cfg["model_name"],
            cfg["model_version"],
            cfg["dim"],
            cfg.get("runtime", "fastembed"),
        ),
    )
    return 1


async def _seed_frameworks(cur: psycopg.AsyncCursor, frameworks: list[dict[str, Any]]) -> int:
    """UPSERT by code. Updates name/description/etc. if they changed."""
    written = 0
    for fw in frameworks:
        await cur.execute(
            """
            INSERT INTO verity_compliance.regulatory_framework
                (code, name, jurisdiction, version, effective_date,
                 source_url, description, sort_seq)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name           = EXCLUDED.name,
                jurisdiction   = EXCLUDED.jurisdiction,
                version        = EXCLUDED.version,
                effective_date = EXCLUDED.effective_date,
                source_url     = EXCLUDED.source_url,
                description    = EXCLUDED.description,
                sort_seq       = EXCLUDED.sort_seq,
                updated_at     = now()
            """,
            (
                fw["code"],
                fw["name"],
                fw["jurisdiction"],
                fw.get("version"),
                fw.get("effective_date"),
                fw.get("source_url"),
                fw.get("description"),
                fw.get("sort_seq", 0),
            ),
        )
        written += 1
    return written


async def _seed_themes(cur: psycopg.AsyncCursor, themes: list[dict[str, Any]]) -> int:
    """UPSERT by code."""
    written = 0
    for theme in themes:
        await cur.execute(
            """
            INSERT INTO verity_compliance.canonical_requirement_theme
                (code, name, description, sort_seq)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name        = EXCLUDED.name,
                description = EXCLUDED.description,
                sort_seq    = EXCLUDED.sort_seq
            """,
            (
                theme["code"],
                theme["name"],
                theme.get("description"),
                theme.get("sort_seq", 0),
            ),
        )
        written += 1
    return written


async def _seed_feature_hierarchy(
    cur: psycopg.AsyncCursor, planes: list[dict[str, Any]]
) -> tuple[int, int, int]:
    """Walk plane → capability → feature.
    UPSERT planes by code, capabilities by (plane_id, code), features by (capability_id, code).
    """
    n_planes = n_caps = n_features = 0

    for plane in planes:
        await cur.execute(
            """
            INSERT INTO verity_compliance.feature_plane
                (code, name, description, sort_seq)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET
                name        = EXCLUDED.name,
                description = EXCLUDED.description,
                sort_seq    = EXCLUDED.sort_seq
            RETURNING id
            """,
            (
                plane["code"],
                plane["name"],
                plane.get("description"),
                plane.get("sort_seq", 0),
            ),
        )
        plane_row = await cur.fetchone()
        plane_id = plane_row[0]
        n_planes += 1

        for cap in plane.get("capabilities", []):
            await cur.execute(
                """
                INSERT INTO verity_compliance.feature_capability
                    (plane_id, code, name, description, sort_seq)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (plane_id, code) DO UPDATE SET
                    name        = EXCLUDED.name,
                    description = EXCLUDED.description,
                    sort_seq    = EXCLUDED.sort_seq
                RETURNING id
                """,
                (
                    plane_id,
                    cap["code"],
                    cap["name"],
                    cap.get("description"),
                    cap.get("sort_seq", 0),
                ),
            )
            cap_row = await cur.fetchone()
            cap_id = cap_row[0]
            n_caps += 1

            for feat in cap.get("features", []):
                await cur.execute(
                    """
                    INSERT INTO verity_compliance.feature
                        (capability_id, code, name, description, status, sort_seq)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (capability_id, code) DO UPDATE SET
                        name        = EXCLUDED.name,
                        description = EXCLUDED.description,
                        status      = EXCLUDED.status,
                        sort_seq    = EXCLUDED.sort_seq,
                        updated_at  = now()
                    """,
                    (
                        cap_id,
                        feat["code"],
                        feat["name"],
                        feat.get("description"),
                        feat.get("status", "shipped"),
                        feat.get("sort_seq", 0),
                    ),
                )
                n_features += 1

    return n_planes, n_caps, n_features


# =============================================================================
# Phase 1.3 — canonical requirements + provisions + bridges + coverage
# =============================================================================


async def seed_data(database_url: str) -> dict[str, int]:
    """Seed canonical requirements, provisions, bridges, coverage from YAML.

    Pre-requisite: seed_static() must have been run first (frameworks, themes,
    feature hierarchy must exist; this seeder looks them up by code).

    Idempotent — UPSERTs by natural key. Bridge rows for canonical-feature and
    provision-canonical relationships are recomputed: existing rows are deleted
    for each canonical / provision and re-inserted from YAML on every run, so
    removing a row from YAML actually removes it from DB.

    Returns a counts dict.
    """
    data = yaml.safe_load(DATA_SEED_FILE.read_text())

    counts = {
        "canonical_requirements": 0,
        "requirement_coverage": 0,
        "requirement_feature_links": 0,
        "provisions": 0,
        "provision_requirement_maps": 0,
    }

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=False
    ) as conn:
        async with conn.cursor() as cur:
            # Pre-fetch lookup tables.
            theme_lookup = await _lookup(cur, "verity_compliance.canonical_requirement_theme")
            framework_lookup = await _lookup(cur, "verity_compliance.regulatory_framework")
            feature_lookup = await _lookup(cur, "verity_compliance.feature")

            # ---- canonical requirements + coverage + feature links -------
            canonical_lookup: dict[str, str] = {}
            for cr in data["canonical_requirements"]:
                cr_id = await _upsert_canonical_requirement(
                    cur, cr, theme_lookup
                )
                canonical_lookup[cr["code"]] = cr_id
                counts["canonical_requirements"] += 1

                if "coverage" in cr:
                    await _upsert_coverage(cur, cr_id, cr["coverage"])
                    counts["requirement_coverage"] += 1

                if "feature_links" in cr:
                    n = await _refresh_feature_links(
                        cur, cr_id, cr["feature_links"], feature_lookup, cr["code"]
                    )
                    counts["requirement_feature_links"] += n

            # ---- provisions + bridge to canonical requirements ----------
            for prov in data["provisions"]:
                prov_id = await _upsert_provision(cur, prov, framework_lookup)
                counts["provisions"] += 1

                links = prov.get("canonical_links", [])
                n = await _refresh_provision_canonical_links(
                    cur, prov_id, links, canonical_lookup, prov["citation"]
                )
                counts["provision_requirement_maps"] += n

        await conn.commit()

    return counts


async def _lookup(cur: psycopg.AsyncCursor, table: str) -> dict[str, str]:
    """Build a {code: id} lookup for a table that has both."""
    await cur.execute(f"SELECT code, id FROM {table}")
    return {row[0]: row[1] for row in await cur.fetchall()}


async def _upsert_canonical_requirement(
    cur: psycopg.AsyncCursor,
    cr: dict[str, Any],
    theme_lookup: dict[str, str],
) -> str:
    theme_code = cr["theme"]
    if theme_code not in theme_lookup:
        raise ValueError(
            f"canonical_requirement {cr['code']!r} references unknown "
            f"theme {theme_code!r}. Run seed_static first or fix the YAML."
        )

    await cur.execute(
        """
        INSERT INTO verity_compliance.canonical_requirement
            (theme_id, code, title, description, sort_seq)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET
            theme_id    = EXCLUDED.theme_id,
            title       = EXCLUDED.title,
            description = EXCLUDED.description,
            sort_seq    = EXCLUDED.sort_seq,
            updated_at  = now()
        RETURNING id
        """,
        (
            theme_lookup[theme_code],
            cr["code"],
            cr["title"],
            cr.get("description"),
            cr.get("sort_seq", 0),
        ),
    )
    row = await cur.fetchone()
    return row[0]


async def _upsert_coverage(
    cur: psycopg.AsyncCursor,
    canonical_requirement_id: str,
    coverage: dict[str, Any],
) -> None:
    await cur.execute(
        """
        INSERT INTO verity_compliance.requirement_coverage
            (canonical_requirement_id, coverage_level, rationale, customer_actions)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (canonical_requirement_id) DO UPDATE SET
            coverage_level   = EXCLUDED.coverage_level,
            rationale        = EXCLUDED.rationale,
            customer_actions = EXCLUDED.customer_actions,
            last_reviewed_at = now(),
            updated_at       = now()
        """,
        (
            canonical_requirement_id,
            coverage["level"],
            coverage.get("rationale"),
            coverage.get("customer_actions"),
        ),
    )


async def _refresh_feature_links(
    cur: psycopg.AsyncCursor,
    canonical_requirement_id: str,
    links: list[dict[str, Any]],
    feature_lookup: dict[str, str],
    cr_code: str,
) -> int:
    # Delete-and-replace so removing a link from YAML actually removes it.
    await cur.execute(
        "DELETE FROM verity_compliance.requirement_feature_link "
        "WHERE canonical_requirement_id = %s",
        (canonical_requirement_id,),
    )
    n = 0
    for link in links:
        feat_code = link["code"]
        if feat_code not in feature_lookup:
            raise ValueError(
                f"canonical_requirement {cr_code!r} references unknown "
                f"feature {feat_code!r}. Run seed_static first or fix the YAML."
            )
        await cur.execute(
            """
            INSERT INTO verity_compliance.requirement_feature_link
                (canonical_requirement_id, feature_id, role, notes)
            VALUES (%s, %s, %s, %s)
            """,
            (
                canonical_requirement_id,
                feature_lookup[feat_code],
                link.get("role", "primary"),
                link.get("notes"),
            ),
        )
        n += 1
    return n


async def _upsert_provision(
    cur: psycopg.AsyncCursor,
    prov: dict[str, Any],
    framework_lookup: dict[str, str],
) -> str:
    fw_code = prov["framework"]
    if fw_code not in framework_lookup:
        raise ValueError(
            f"provision {prov['citation']!r} references unknown "
            f"framework {fw_code!r}. Run seed_static first or fix the YAML."
        )

    await cur.execute(
        """
        INSERT INTO verity_compliance.regulatory_provision
            (framework_id, citation, title, text, sort_seq)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (framework_id, citation) DO UPDATE SET
            title       = EXCLUDED.title,
            text        = EXCLUDED.text,
            sort_seq    = EXCLUDED.sort_seq,
            updated_at  = now()
        RETURNING id
        """,
        (
            framework_lookup[fw_code],
            prov["citation"],
            prov["title"],
            prov.get("text"),
            prov.get("sort_seq", 0),
        ),
    )
    row = await cur.fetchone()
    return row[0]


async def _refresh_provision_canonical_links(
    cur: psycopg.AsyncCursor,
    provision_id: str,
    links: list[dict[str, Any]],
    canonical_lookup: dict[str, str],
    prov_citation: str,
) -> int:
    await cur.execute(
        "DELETE FROM verity_compliance.provision_requirement_map "
        "WHERE provision_id = %s",
        (provision_id,),
    )
    n = 0
    for link in links:
        cr_code = link["canonical"]
        if cr_code not in canonical_lookup:
            raise ValueError(
                f"provision {prov_citation!r} references unknown "
                f"canonical_requirement {cr_code!r}."
            )
        await cur.execute(
            """
            INSERT INTO verity_compliance.provision_requirement_map
                (provision_id, canonical_requirement_id,
                 match_strength, confidence, mapping_source, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                provision_id,
                canonical_lookup[cr_code],
                link.get("match_strength", 1.00),
                link.get("confidence", 1.00),
                link.get("mapping_source", "manual"),
                link.get("notes"),
            ),
        )
        n += 1
    return n


# =============================================================================
# Phase 2.2 — Reports seeder (mart_field, requirement_evidence_field,
#             report_definition, report_requirement)
# =============================================================================


async def seed_reports(database_url: str) -> dict[str, int]:
    """Seed mart_field rows + requirement_evidence_field bridges + report
    definitions + their canonical-requirement bridges from
    compliance_seed_reports.yaml.

    Pre-requisite: seed_static + seed_data must have run first (canonical
    requirements must exist; this seeder looks them up by code).

    Idempotent — UPSERTs by natural keys. Bridge rows
    (requirement_evidence_field, report_requirement) are recomputed:
    delete-and-replace per parent on every run, so removing a row from
    YAML actually removes it from DB.
    """
    data = yaml.safe_load(REPORTS_SEED_FILE.read_text())

    counts = {
        "mart_fields":               0,
        "requirement_evidence_fields": 0,
        "report_definitions":        0,
        "report_requirements":       0,
    }

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=False
    ) as conn:
        async with conn.cursor() as cur:
            # ---- feed_view registry UPSERT ---------------------------
            for fv in data.get("feed_views", []):
                await cur.execute(
                    """
                    INSERT INTO verity_analytics.feed_view
                        (view_name, description, is_active, sort_seq)
                    VALUES (%s, %s, true, %s)
                    ON CONFLICT (view_name) DO UPDATE SET
                        description = EXCLUDED.description,
                        is_active   = EXCLUDED.is_active,
                        sort_seq    = EXCLUDED.sort_seq
                    """,
                    (
                        fv["view"],
                        fv.get("description"),
                        int(fv.get("sort", 0)),
                    ),
                )
            counts.setdefault("feed_views", 0)
            counts["feed_views"] = len(data.get("feed_views", []))

            # ---- mart_field UPSERT ------------------------------------
            for mf in data.get("mart_fields", []):
                await cur.execute(
                    """
                    INSERT INTO verity_analytics.mart_field
                        (table_name, column_name, semantic_type, description,
                         is_pii, sort_seq)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (table_name, column_name) DO UPDATE SET
                        semantic_type = EXCLUDED.semantic_type,
                        description   = EXCLUDED.description,
                        is_pii        = EXCLUDED.is_pii,
                        sort_seq      = EXCLUDED.sort_seq,
                        updated_at    = now()
                    """,
                    (
                        mf["table"],
                        mf["column"],
                        mf["type"],
                        mf.get("description"),
                        bool(mf.get("is_pii", False)),
                        int(mf.get("sort", 0)),
                    ),
                )
                counts["mart_fields"] += 1

            # Build (table, column) -> mart_field_id lookup.
            await cur.execute(
                "SELECT table_name, column_name, id FROM verity_analytics.mart_field"
            )
            mart_lookup: dict[tuple[str, str], str] = {
                (row[0], row[1]): row[2] for row in await cur.fetchall()
            }

            # Build canonical_code -> id lookup.
            await cur.execute(
                "SELECT code, id FROM verity_compliance.canonical_requirement"
            )
            canonical_lookup: dict[str, str] = {
                row[0]: row[1] for row in await cur.fetchall()
            }

            # ---- requirement_evidence_field bridges (delete + replace) ---
            for cr in data.get("requirement_evidence_fields", []):
                cr_code = cr["canonical"]
                if cr_code not in canonical_lookup:
                    raise ValueError(
                        f"requirement_evidence_field references unknown "
                        f"canonical {cr_code!r}"
                    )
                cr_id = canonical_lookup[cr_code]

                await cur.execute(
                    "DELETE FROM verity_compliance.requirement_evidence_field "
                    "WHERE canonical_requirement_id = %s",
                    (cr_id,),
                )
                for f in cr.get("fields", []):
                    key = (f["table"], f["column"])
                    if key not in mart_lookup:
                        raise ValueError(
                            f"requirement_evidence_field {cr_code!r} "
                            f"references unregistered mart_field {key!r}"
                        )
                    await cur.execute(
                        """
                        INSERT INTO verity_compliance.requirement_evidence_field
                            (canonical_requirement_id, mart_field_id,
                             role, aggregation, sort_seq, notes)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            cr_id,
                            mart_lookup[key],
                            f.get("role", "dimension"),
                            f.get("aggregation"),
                            int(f.get("sort", 0)),
                            f.get("notes"),
                        ),
                    )
                    counts["requirement_evidence_fields"] += 1

            # ---- report_definition UPSERT + report_requirement (replace) ---
            for rep in data.get("reports", []):
                await cur.execute(
                    """
                    INSERT INTO verity_compliance.report_definition
                        (code, name, description, report_kind, docx_template,
                         output_formats, scope_params, sort_seq, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, true)
                    ON CONFLICT (code) DO UPDATE SET
                        name           = EXCLUDED.name,
                        description    = EXCLUDED.description,
                        report_kind    = EXCLUDED.report_kind,
                        docx_template  = EXCLUDED.docx_template,
                        output_formats = EXCLUDED.output_formats,
                        scope_params   = EXCLUDED.scope_params,
                        sort_seq       = EXCLUDED.sort_seq,
                        updated_at     = now()
                    RETURNING id
                    """,
                    (
                        rep["code"],
                        rep["name"],
                        rep.get("description"),
                        rep.get("report_kind", "metadata_driven"),
                        rep.get("docx_template"),
                        rep.get("output_formats", ["html", "docx", "pdf"]),
                        json.dumps(rep.get("scope_params", {})),
                        int(rep.get("sort_seq", 0)),
                    ),
                )
                report_id = (await cur.fetchone())[0]
                counts["report_definitions"] += 1

                await cur.execute(
                    "DELETE FROM verity_compliance.report_requirement "
                    "WHERE report_id = %s",
                    (report_id,),
                )
                for rr in rep.get("canonical_requirements", []):
                    cr_code = rr["code"]
                    if cr_code not in canonical_lookup:
                        raise ValueError(
                            f"report {rep['code']!r} references unknown "
                            f"canonical {cr_code!r}"
                        )
                    await cur.execute(
                        """
                        INSERT INTO verity_compliance.report_requirement
                            (report_id, canonical_requirement_id, section, sort_seq, notes)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            report_id,
                            canonical_lookup[cr_code],
                            rr.get("section"),
                            int(rr.get("sort", 0)),
                            rr.get("notes"),
                        ),
                    )
                    counts["report_requirements"] += 1

        await conn.commit()

    return counts


# =============================================================================
# Phase 1.5 — Embedding pipeline (fastembed + staleness-aware reembed)
# =============================================================================
# Embedded columns (per docs/architecture/compliance-stack.md):
#   regulatory_provision.embedding   ← title + " " + text
#   canonical_requirement.embedding  ← title + " " + description
#   feature.embedding                ← name  + " " + description
# Each embedded row carries embedding_model_id pointing at embedding_config so
# the reembed CLI can detect stale rows when the model is upgraded and only
# re-embed those (instead of all rows). See AD-CS-007.

# Tables to embed: (table_qualname, [text_columns_in_priority_order])
_EMBEDDABLE_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("verity_compliance.regulatory_provision",  ("title", "text")),
    ("verity_compliance.canonical_requirement", ("title", "description")),
    ("verity_compliance.feature",               ("name",  "description")),
)


def _vector_literal(emb) -> str:
    """Format a 1-D numeric iterable as a pgvector literal: '[v1,v2,...]'."""
    return "[" + ",".join(f"{float(v):.6f}" for v in emb) + "]"


def _row_text(row, n_cols: int) -> str:
    """Combine the row's text columns (positions 1..n) into a single embedding
    input string. None / empty cells are skipped. Returns '(empty)' as a
    last-resort fallback so the embedder never sees a blank string.
    """
    parts: list[str] = []
    for i in range(1, n_cols + 1):
        val = row[i]
        if val:
            parts.append(str(val).strip())
    combined = " ".join(parts)
    return combined or "(empty)"


async def reembed(database_url: str, force: bool = False) -> dict[str, int]:
    """Generate vector embeddings for compliance rows.

    Walks the three embedded tables and produces vectors for any row that
    is stale — i.e. either has no embedding yet, or has an
    embedding_model_id different from the current `embedding_config` row.
    With `force=True`, every row is re-embedded regardless.

    Returns a dict of {table_name: rows_embedded}.
    """
    # Lazy import — fastembed download (~30 MB ONNX model) only triggers
    # when this CLI command is actually run.
    from fastembed import TextEmbedding  # type: ignore

    counts: dict[str, int] = {table: 0 for table, _ in _EMBEDDABLE_TABLES}

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=False
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, model_name, dim
                FROM verity_compliance.embedding_config
                WHERE is_current = true
                """
            )
            cfg = await cur.fetchone()
            if not cfg:
                raise RuntimeError(
                    "No current embedding_config row. "
                    "Run `verity compliance seed-static` first."
                )
            current_id, model_name, dim = cfg

            print(f"Loading embedding model {model_name} (dim={dim})…")
            model = TextEmbedding(model_name)

            for table, text_columns in _EMBEDDABLE_TABLES:
                col_list = ", ".join(text_columns)

                if force:
                    await cur.execute(
                        f"SELECT id, {col_list} FROM {table} ORDER BY id"
                    )
                else:
                    await cur.execute(
                        f"""
                        SELECT id, {col_list} FROM {table}
                        WHERE embedding IS NULL
                           OR embedding_model_id IS NULL
                           OR embedding_model_id != %s
                        ORDER BY id
                        """,
                        (current_id,),
                    )
                rows = await cur.fetchall()
                if not rows:
                    print(f"  {table:<46} — already current")
                    continue

                texts = [_row_text(r, len(text_columns)) for r in rows]
                print(f"  {table:<46} — embedding {len(rows)} row(s)…")
                embeddings = list(model.embed(texts))

                for r, emb in zip(rows, embeddings):
                    if len(emb) != dim:
                        raise RuntimeError(
                            f"Model produced dim={len(emb)} but "
                            f"embedding_config says dim={dim} for {model_name}."
                        )
                    await cur.execute(
                        f"""
                        UPDATE {table}
                        SET embedding = %s::vector,
                            embedding_model_id = %s,
                            updated_at = now()
                        WHERE id = %s
                        """,
                        (_vector_literal(emb), current_id, r[0]),
                    )
                counts[table] = len(rows)

        await conn.commit()

    return counts


async def similarity_search(
    database_url: str,
    query_text: str,
    top_k: int = 5,
    table: str = "canonical_requirement",
) -> list[dict]:
    """Embed `query_text` and return the top-k closest rows by cosine
    similarity from one of the three embedded tables.

    `table` ∈ {'canonical_requirement', 'regulatory_provision', 'feature'}.
    Returns a list of result dicts (also prints them to stdout).
    """
    from fastembed import TextEmbedding  # type: ignore

    table_qualnames = {
        "canonical_requirement": "verity_compliance.canonical_requirement",
        "regulatory_provision":  "verity_compliance.regulatory_provision",
        "feature":               "verity_compliance.feature",
    }
    if table not in table_qualnames:
        raise ValueError(
            f"Unknown table {table!r}. Choose: {list(table_qualnames)}"
        )

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT model_name FROM verity_compliance.embedding_config "
                "WHERE is_current = true"
            )
            r = await cur.fetchone()
            if not r:
                raise RuntimeError("No current embedding_config row.")
            model_name = r[0]

            model = TextEmbedding(model_name)
            query_emb = next(iter(model.embed([query_text])))
            qlit = _vector_literal(query_emb)

            if table == "canonical_requirement":
                sql = f"""
                    SELECT cr.code, cr.title, t.code AS theme_code,
                           1 - (cr.embedding <=> %s::vector) AS cosine_similarity
                    FROM   {table_qualnames[table]} cr
                    JOIN   verity_compliance.canonical_requirement_theme t
                           ON t.id = cr.theme_id
                    WHERE  cr.embedding IS NOT NULL
                    ORDER BY cr.embedding <=> %s::vector
                    LIMIT  %s
                """
            elif table == "regulatory_provision":
                sql = f"""
                    SELECT p.citation, p.title, f.code AS framework_code,
                           1 - (p.embedding <=> %s::vector) AS cosine_similarity
                    FROM   {table_qualnames[table]} p
                    JOIN   verity_compliance.regulatory_framework f
                           ON f.id = p.framework_id
                    WHERE  p.embedding IS NOT NULL
                    ORDER BY p.embedding <=> %s::vector
                    LIMIT  %s
                """
            else:  # feature
                sql = f"""
                    SELECT feat.code, feat.name, p.code AS plane_code,
                           1 - (feat.embedding <=> %s::vector) AS cosine_similarity
                    FROM   {table_qualnames[table]} feat
                    JOIN   verity_compliance.feature_capability c ON c.id = feat.capability_id
                    JOIN   verity_compliance.feature_plane     p ON p.id = c.plane_id
                    WHERE  feat.embedding IS NOT NULL
                    ORDER BY feat.embedding <=> %s::vector
                    LIMIT  %s
                """

            await cur.execute(sql, (qlit, qlit, top_k))
            rows = await cur.fetchall()

    print(f"\nQuery:  {query_text!r}")
    print(f"Table:  {table}")
    print(f"Top {top_k} matches by cosine similarity:\n")
    results: list[dict] = []
    for row in rows:
        c1, c2, c3, sim = row
        print(f"  {sim:.3f}  [{c1}]  {c2}  ({c3})")
        results.append({"code_or_citation": c1, "title": c2, "context": c3, "similarity": float(sim)})
    if not results:
        print("  (no rows — did you run `verity compliance reembed`?)")
    print()
    return results


# =============================================================================
# Inspection — print what's in the DB as a tree (review affordance)
# =============================================================================


async def show(database_url: str) -> None:
    """Print frameworks, themes, and feature hierarchy as a tree.

    Easy way to review what was seeded without firing up the UI.
    """
    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            print("\n=== EMBEDDING MODEL ===")
            await cur.execute(
                """
                SELECT model_name, model_version, dim, runtime, is_current
                FROM verity_compliance.embedding_config
                ORDER BY is_current DESC, created_at DESC
                """
            )
            rows = await cur.fetchall()
            if not rows:
                print("  (none)")
            for name, ver, dim, runtime, is_current in rows:
                marker = "* current" if is_current else "  history"
                print(f"  {marker}  {name} {ver}  dim={dim}  runtime={runtime}")

            print("\n=== REGULATORY FRAMEWORKS ===")
            await cur.execute(
                """
                SELECT code, name, jurisdiction, version, effective_date,
                       valid_from, valid_to
                FROM verity_compliance.regulatory_framework
                ORDER BY sort_seq, code
                """
            )
            rows = await cur.fetchall()
            if not rows:
                print("  (none)")
            for code, name, juris, ver, eff, vf, vt in rows:
                print(f"  [{code}]  {name}")
                print(
                    f"    jurisdiction={juris}  version={ver or '—'}  "
                    f"effective={eff or '—'}  valid={vf}..{vt}"
                )

            print("\n=== CANONICAL REQUIREMENT THEMES ===")
            await cur.execute(
                """
                SELECT code, name, description
                FROM verity_compliance.canonical_requirement_theme
                ORDER BY sort_seq, code
                """
            )
            rows = await cur.fetchall()
            if not rows:
                print("  (none)")
            for code, name, desc in rows:
                first_line = (desc or "").strip().split("\n")[0][:80]
                print(f"  [{code:<32}]  {name}")
                if first_line:
                    print(f"      {first_line}")

            print("\n=== FEATURE HIERARCHY ===")
            await cur.execute(
                """
                SELECT p.code, p.name, p.sort_seq,
                       c.code, c.name, c.sort_seq,
                       f.code, f.name, f.status, f.sort_seq
                FROM verity_compliance.feature_plane p
                JOIN verity_compliance.feature_capability c ON c.plane_id = p.id
                JOIN verity_compliance.feature             f ON f.capability_id = c.id
                ORDER BY p.sort_seq, c.sort_seq, f.sort_seq
                """
            )
            rows = await cur.fetchall()
            if not rows:
                print("  (none)")
                return

            cur_plane = cur_cap = None
            plane_count = cap_count = feat_count = 0
            for (
                p_code, p_name, _p_seq,
                c_code, c_name, _c_seq,
                f_code, f_name, f_status, _f_seq,
            ) in rows:
                if p_code != cur_plane:
                    print(f"\n  ▸ {p_name}  [{p_code}]")
                    cur_plane = p_code
                    cur_cap = None
                    plane_count += 1
                if c_code != cur_cap:
                    print(f"      └─ {c_name}  [{c_code}]")
                    cur_cap = c_code
                    cap_count += 1
                status_tag = "" if f_status == "shipped" else f"  ({f_status})"
                print(f"            • {f_name}  [{f_code}]{status_tag}")
                feat_count += 1

            print(
                f"\n  TOTAL: {plane_count} planes, {cap_count} capabilities, "
                f"{feat_count} features"
            )

            # ---- canonical requirements + coverage --------------------
            print("\n=== CANONICAL REQUIREMENTS (with coverage) ===")
            await cur.execute(
                """
                SELECT cr.code, cr.title, t.code AS theme_code,
                       cov.coverage_level, cov.customer_actions
                FROM verity_compliance.canonical_requirement cr
                JOIN verity_compliance.canonical_requirement_theme t ON t.id = cr.theme_id
                LEFT JOIN verity_compliance.requirement_coverage cov
                       ON cov.canonical_requirement_id = cr.id
                ORDER BY t.sort_seq, cr.sort_seq, cr.code
                """
            )
            rows = await cur.fetchall()
            if not rows:
                print("  (none — run `verity compliance seed-data` first)")
                return

            cur_theme = None
            cov_counts: dict[str, int] = {}
            cr_count = 0
            for cr_code, cr_title, theme_code, level, actions in rows:
                if theme_code != cur_theme:
                    print(f"\n  ▸ THEME: {theme_code}")
                    cur_theme = theme_code
                marker = {
                    "full": "✓ FULL       ",
                    "substantial": "◐ SUBSTANT.  ",
                    "partial": "◑ PARTIAL    ",
                    "gap": "✗ GAP        ",
                }.get(level or "", "  (no cov)   ")
                print(f"      {marker} {cr_title}  [{cr_code}]")
                if actions:
                    first_line = actions.strip().split("\n")[0][:88]
                    print(f"                    customer: {first_line}")
                if level:
                    cov_counts[level] = cov_counts.get(level, 0) + 1
                cr_count += 1

            print("\n  Coverage rollup:")
            for level in ("full", "substantial", "partial", "gap"):
                print(f"    {level:<13} {cov_counts.get(level, 0)}")
            print(f"    total         {cr_count}")

            # ---- provisions per framework ----------------------------
            print("\n=== PROVISIONS BY FRAMEWORK ===")
            await cur.execute(
                """
                SELECT f.code, f.name, p.citation, p.title,
                       count(prm.id) AS link_count
                FROM verity_compliance.regulatory_framework f
                LEFT JOIN verity_compliance.regulatory_provision p ON p.framework_id = f.id
                LEFT JOIN verity_compliance.provision_requirement_map prm
                       ON prm.provision_id = p.id
                GROUP BY f.code, f.name, p.id, p.citation, p.title, f.sort_seq, p.sort_seq
                ORDER BY f.sort_seq, p.sort_seq NULLS FIRST
                """
            )
            rows = await cur.fetchall()
            cur_fw = None
            prov_total = 0
            for fw_code, fw_name, citation, title, link_count in rows:
                if fw_code != cur_fw:
                    print(f"\n  ▸ {fw_name}  [{fw_code}]")
                    cur_fw = fw_code
                if citation is None:
                    print("      (no provisions seeded)")
                    continue
                bridge_marker = f"→{link_count} canonical" if link_count else "→0 canonical"
                print(f"      • {citation}  {bridge_marker}")
                prov_total += 1

            print(f"\n  TOTAL provisions: {prov_total}")


# =============================================================================
# Convenience: standalone runner
# =============================================================================


def main() -> None:
    """Allow `python -m verity.setup.seed_compliance <database_url>` for quick runs."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m verity.setup.seed_compliance <database_url> [seed|show]")
        sys.exit(1)

    db_url = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "seed"

    if action == "seed":
        counts = asyncio.run(seed_static(db_url))
        print("Static compliance seed complete:")
        for k, v in counts.items():
            print(f"  {k:<22} {v}")
    elif action == "seed-data":
        counts = asyncio.run(seed_data(db_url))
        print("Compliance data seed complete:")
        for k, v in counts.items():
            print(f"  {k:<28} {v}")
    elif action == "show":
        asyncio.run(show(db_url))
    else:
        print(f"Unknown action: {action!r}. Use 'seed', 'seed-data', or 'show'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
