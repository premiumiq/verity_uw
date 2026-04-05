# PremiumIQ Verity — Project Context

## What This Is
PremiumIQ Verity is an AI governance platform for P&C insurance. "Application X powered by Verity" — Verity is the governance infrastructure, business apps are consumers.

## Repository Layout
- `verity/` — The Verity Python package project (pip-installable).
  - `verity/src/verity/` — Package source code (src layout to avoid import shadowing).
  - `verity/pyproject.toml` — Package metadata, dependencies, build config.
- `uw_demo/` — The UW business application (powered by Verity).
- `docs/architecture/` — Build plan, architectural decisions.
- `docs/guides/` — Step-by-step setup and operational guides.
- `VERITY_COMBINED_PRD_v3.md` — The full PRD (source of truth for requirements).

## Key Architecture Decisions
1. **Verity is a Python package** — usable as SDK, API service, or web app. The `verity/` directory is pip-installable.
2. **No ORM** — Raw SQL in `.sql` files with Pydantic models. Transparent and debuggable.
3. **Full 7-state lifecycle** — draft → candidate → staging → shadow → challenger → champion → deprecated. Schema is complete from day one.
4. **pgvector from day one** — `vector(1536)` columns present but nullable. Populated later.
5. **Clear separation** — Verity knows nothing about insurance. UW demo registers its agents/tasks in Verity and calls `verity.execute_agent()`.
6. **Single process for demo** — Business app mounts Verity API + Web as FastAPI sub-applications.

## Database Approach
- `psycopg` v3 (async) for PostgreSQL access
- SQL queries in `verity/src/verity/db/queries/*.sql` as named queries
- Pydantic models in `verity/src/verity/models/` for validation/serialization
- No SQLAlchemy, no Alembic, no ORM of any kind

## UI Tech Stack
- Jinja2 for server-side rendering
- HTMX for dynamic updates (no JavaScript to write)
- DaisyUI (Tailwind CSS component library) via CDN for styling

## Coding Conventions
- All SQL queries must be in `.sql` files, never inline Python strings
- All data models are Pydantic, never dataclasses or dicts
- The Verity package must not import anything from `uw_demo/`
- Every AI invocation must go through Verity's execution engine
- No hardcoded AI parameters (temperature, prompts, etc.) in business app code

## Two Databases
- `verity_db` — All AI governance data (agents, tasks, prompts, configs, tools, decisions, etc.)
- `pas_db` — Business data (accounts, submissions)

## Docker Services
- `postgres` — pgvector/pgvector:pg16 (both databases)
- `minio` — Document storage
- `app` — Single FastAPI process (Verity + UW demo)
