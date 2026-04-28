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
from pathlib import Path
from typing import Any

import psycopg
import yaml


STATIC_SEED_FILE = Path(__file__).parent / "compliance_seed_static.yaml"


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
    elif action == "show":
        asyncio.run(show(db_url))
    else:
        print(f"Unknown action: {action!r}. Use 'seed' or 'show'.")
        sys.exit(1)


if __name__ == "__main__":
    main()
