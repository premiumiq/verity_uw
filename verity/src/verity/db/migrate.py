"""Simple schema migration: apply schema.sql to database.

No Alembic, no migration framework. Just the DDL.
For a production system, add version tracking and incremental migrations.
"""

import asyncio
from pathlib import Path

import psycopg


SCHEMA_FILE = Path(__file__).parent / "schema.sql"
COMPLIANCE_SCHEMA_FILE = Path(__file__).parent / "schema_compliance.sql"
COMPLIANCE_VIEWS_FILE = Path(__file__).parent / "schema_compliance_views.sql"
# Governance intake (use cases / requirements / approvals / artifact plan).
# Applied AFTER schema_compliance.sql because intake_requirement.embedding_model_id
# FKs compliance.embedding_config. See docs/architecture/governance-intake.md.
INTAKE_SCHEMA_FILE = Path(__file__).parent / "schema_intake.sql"


async def apply_schema(database_url: str, drop_existing: bool = False) -> None:
    """Apply the Verity schema to the target database.

    Applies schema.sql first (operational trust DB), then
    schema_compliance.sql (L3 compliance metamodel + L2 analytics
    schema placeholder), then schema_intake.sql (governance intake
    layer — use cases, requirements, approvals, artifact plan), then
    schema_compliance_views.sql (logical mart). See
    docs/architecture/compliance-stack.md and
    docs/architecture/governance-intake.md.

    Args:
        database_url: PostgreSQL connection URL.
        drop_existing: If True, drop all tables first (destructive!).
    """
    schema_sql = SCHEMA_FILE.read_text()
    compliance_schema_sql = COMPLIANCE_SCHEMA_FILE.read_text()
    intake_schema_sql = INTAKE_SCHEMA_FILE.read_text()
    compliance_views_sql = COMPLIANCE_VIEWS_FILE.read_text()

    async with await psycopg.AsyncConnection.connect(
        database_url, autocommit=True
    ) as conn:
        # Check if pgvector extension is available
        result = await conn.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
        )
        row = await result.fetchone()
        if not row:
            print(
                "WARNING: pgvector extension not available. "
                "vector(1536) columns will fail. "
                "Use pgvector/pgvector:pg16 Docker image."
            )

        if drop_existing:
            print("Dropping existing schema...")
            # Drop the four Verity-owned schemas. CASCADE removes every
            # table, view, type, and index within each.
            for schema in ("governance", "runtime", "compliance", "analytics"):
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            print("Existing schema dropped.")

        print("Applying Verity schema...")

        # Split and execute statements individually for better error reporting.
        # schema.sql uses semicolons to delimit statements.
        statements = _split_sql_statements(schema_sql)
        for i, stmt in enumerate(statements, 1):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await conn.execute(stmt)
            except Exception as e:
                # Skip "already exists" errors for idempotency
                err_msg = str(e)
                if "already exists" in err_msg:
                    continue
                print(f"Error on statement {i}: {err_msg}")
                print(f"Statement: {stmt[:200]}...")
                raise

        print("Applying Verity compliance schema (L3 metamodel + L4 reports + mart_field)...")
        compliance_statements = _split_sql_statements(compliance_schema_sql)
        for i, stmt in enumerate(compliance_statements, 1):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await conn.execute(stmt)
            except Exception as e:
                err_msg = str(e)
                if "already exists" in err_msg:
                    continue
                print(f"Compliance schema error on statement {i}: {err_msg}")
                print(f"Statement: {stmt[:200]}...")
                raise

        print("Applying Verity intake schema (governance intake / requirements / approvals)...")
        intake_statements = _split_sql_statements(intake_schema_sql)
        for i, stmt in enumerate(intake_statements, 1):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await conn.execute(stmt)
            except Exception as e:
                err_msg = str(e)
                if "already exists" in err_msg:
                    continue
                print(f"Intake schema error on statement {i}: {err_msg}")
                print(f"Statement: {stmt[:200]}...")
                raise

        print("Applying analytics views (logical mart over L1)...")
        view_statements = _split_sql_statements(compliance_views_sql)
        for i, stmt in enumerate(view_statements, 1):
            stmt = stmt.strip()
            if not stmt:
                continue
            try:
                await conn.execute(stmt)
            except Exception as e:
                # CREATE OR REPLACE VIEW is idempotent; only catch a missing
                # underlying L1 table here (e.g. before main schema applied).
                err_msg = str(e)
                print(f"View creation error on statement {i}: {err_msg}")
                print(f"Statement: {stmt[:200]}...")
                raise

        # Verify key tables exist in each schema. The exact counts are
        # informational — the canonical correctness check is the test
        # suite (test_schema_applies, test_no_cross_schema_collisions).
        for schema in ("governance", "runtime", "compliance", "analytics"):
            result = await conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = %s "
                "ORDER BY tablename",
                (schema,),
            )
            tables = [row[0] for row in await result.fetchall()]
            print(f"{schema} tables ({len(tables)}): {', '.join(tables) or '(none)'}")

        # Verify pgvector extension
        result = await conn.execute(
            "SELECT extname FROM pg_extension WHERE extname = 'vector'"
        )
        row = await result.fetchone()
        if row:
            print("pgvector extension: installed")
        else:
            print("pgvector extension: NOT installed (vector columns will be NULL)")

        # Seed governance applications (idempotent — skips if already exist).
        # These are Verity platform applications, not business app registrations.
        # They provide execution identity for testing, validation, and audit activities.
        governance_apps = [
            ("ai_ops", "AI Operations",
             "AI/ML engineering team: test suite runs, regression testing, development experimentation."),
            ("model_validation", "Model Validation",
             "Model Risk Management (MRM) team: ground truth validation for promotion gates, independent model assessment."),
            ("compliance_audit", "Compliance & Audit",
             "Compliance officers and internal audit: audit reruns, regulatory reproduction, adverse action verification."),
        ]
        for name, display_name, description in governance_apps:
            try:
                await conn.execute(
                    "INSERT INTO application (name, display_name, description) "
                    "VALUES (%s, %s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, display_name, description),
                )
            except Exception:
                pass  # Table may not exist yet on first run
        print("Governance applications seeded: ai_ops, model_validation, compliance_audit")

        # Persist the database-level search_path so every future connection
        # resolves unqualified DML the same way the DDL just did. The
        # session-level SET search_path inside schema.sql only affects this
        # one connection; the ALTER DATABASE here makes it durable.
        #
        # The current database name comes from psycopg's connection info.
        db_name = conn.info.dbname
        # Identifier comes from a system catalog field, not user input,
        # so direct interpolation is safe (parameter binding can't be
        # used for object names anyway). Quote-ident defensively.
        await conn.execute(
            f'ALTER DATABASE "{db_name}" '
            "SET search_path TO governance, runtime, compliance, analytics, public"
        )
        print(
            f"Database default search_path set on {db_name}: "
            "governance, runtime, compliance, analytics, public"
        )


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL text into individual statements.

    Handles:
    - Single-line comments (-- ...) which may contain semicolons
    - Dollar-quoted blocks ($$...$$) which may contain semicolons
    - String literals ('...') which may contain semicolons
    """
    statements = []
    current = []
    in_dollar_quote = False
    in_single_quote = False
    dollar_tag = ""
    i = 0

    while i < len(sql):
        char = sql[i]

        # Inside a single-quoted string: only look for closing quote
        if in_single_quote:
            current.append(char)
            if char == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                # Escaped quote ('') — skip both
                current.append(sql[i + 1])
                i += 2
                continue
            elif char == "'":
                in_single_quote = False
            i += 1
            continue

        # Inside a dollar-quoted block: only look for closing tag
        if in_dollar_quote:
            if char == "$" and sql[i : i + len(dollar_tag)] == dollar_tag:
                current.append(dollar_tag)
                i += len(dollar_tag)
                in_dollar_quote = False
                continue
            current.append(char)
            i += 1
            continue

        # -- single-line comment: skip to end of line (semicolons inside are NOT delimiters)
        if char == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
            end_of_line = sql.find("\n", i)
            if end_of_line == -1:
                # Comment runs to end of file
                current.append(sql[i:])
                i = len(sql)
            else:
                current.append(sql[i : end_of_line + 1])
                i = end_of_line + 1
            continue

        # Start of single-quoted string
        if char == "'":
            in_single_quote = True
            current.append(char)
            i += 1
            continue

        # Start of dollar-quoted block
        if char == "$":
            j = i + 1
            while j < len(sql) and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < len(sql) and sql[j] == "$":
                dollar_tag = sql[i : j + 1]
                in_dollar_quote = True
                current.append(dollar_tag)
                i = j + 1
                continue

        # Semicolon: statement delimiter
        if char == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(char)
        i += 1

    # Handle last statement (might not end with semicolon)
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements
