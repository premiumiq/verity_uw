# Verity — Initial Setup Guide

This guide walks you through setting up the development infrastructure for PremiumIQ Verity from scratch.

---

## What We're Setting Up

Three services run in Docker containers:


| Service      | Image                                      | Purpose                                                                                                               | Port                           |
| -------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------- |
| **postgres** | `pgvector/pgvector:pg16`                   | PostgreSQL 16 with pgvector extension pre-installed. Hosts`verity_db` (governance data) and `pas_db` (business data). | 5432                           |
| **minio**    | `minio/minio:RELEASE.2024-11-07T00-52-20Z` | S3-compatible object storage for documents (ACORD forms, loss runs, etc.).                                            | 9000 (API), 9001 (web console) |
| **app**      | Built from`./Dockerfile`                   | The FastAPI application (Verity + UW demo). Not needed yet — we'll run locally during development.                   | 8000                           |

The `docker-compose.yml` also defines a **minio-setup** service. This is a one-shot container that runs the MinIO client (`mc`) to create storage buckets (like folders in S3) and then exits. It's not a long-running service — just an initialization helper. You can do the same thing manually from the MinIO web console.

---

## Prerequisites

- Docker Desktop running (you've already started it)
- Python 3.12+ installed
- The `.env` file at project root with your `ANTHROPIC_API_KEY`

---

## Step 1: Start PostgreSQL and MinIO

These are the infrastructure services. We start them first, independently from the application.

```bash
cd ~/verity_uw

# Start just the database and document store
docker compose up -d postgres minio
```

**What this does:**

- Pulls the `pgvector/pgvector:pg16` image (PostgreSQL 16 + pgvector extension)
- Pulls the `minio/minio` image
- Creates Docker volumes `postgres_data` and `minio_data` for persistent storage
- Runs the `scripts/init-multiple-dbs.sh` script inside PostgreSQL on first start, which:
  - Creates `verity_db` database
  - Creates `pas_db` database
  - Enables `uuid-ossp` and `vector` extensions in `verity_db`

**Note on the "version" warning:** Docker Compose shows a warning about `version: '3.9'` being obsolete. This is cosmetic — the file works fine. We can remove the version line later.

### Verify Step 1

```bash
# Check containers are running and healthy
docker compose ps
```

You should see both `verity_postgres` and `verity_minio` with status `Up ... (healthy)`.

```bash
NAME              IMAGE                                      COMMAND                  SERVICE    CREATED         STATUS                   PORTS
verity_minio      minio/minio:RELEASE.2024-11-07T00-52-20Z   "/usr/bin/docker-ent…"   minio      5 minutes ago   Up 5 minutes (healthy)   0.0.0.0:9000-9001->9000-9001/tcp, [::]:9000-9001->9000-9001/tcp
verity_postgres   pgvector/pgvector:pg16                     "docker-entrypoint.s…"   postgres   5 minutes ago   Up 4 minutes (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
```

Next, we will verify PostgreSQL database, check if it is accepting connections.

```bash
# Verify PostgreSQL is accepting connections
docker exec verity_postgres pg_isready -U verityuser
```

Expected: `/var/run/postgresql:5432 - accepting connections`

```bash
# Verify the two databases exist
docker exec verity_postgres psql -U verityuser -l | grep -E "verity_db|pas_db"
```

Expected: Two lines showing `verity_db` and `pas_db`.

```bash
# Verify pgvector extension is installed in verity_db
docker exec verity_postgres psql -U verityuser -d verity_db -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Expected: One row showing `vector` with a version number.

---

## Step 2: Create MinIO Buckets

MinIO needs storage buckets created before we can upload documents. You can do this two ways:

### Option A: Use the MinIO web console (recommended for learning)

1. Open http://localhost:9001 in your browser
2. Log in with: Username `minioadmin`, Password `minioadmin123`
3. Click "Buckets" in the left sidebar
4. Click "Create Bucket" and create these three buckets:
   - `submissions` — for uploaded insurance documents
   - `uw-guidelines` — for underwriting guidelines documents
   - `ground-truth-datasets` — for test/validation datasets

### Option B: Use the minio-setup container

This is what the "sidecar" in docker-compose does — it runs a one-shot container with the MinIO client tool:

```bash
docker compose up minio-setup
```

It creates the three buckets and exits. You can verify in the MinIO web console.

### Verify Step 2

Open http://localhost:9001, log in, and check that the three buckets exist under "Buckets".

---

## Step 3: Set Up Python Environment

We need Python set up before applying the schema (Option A) or running the app.

A **virtual environment** isolates this project's dependencies from your system Python. We use `uv` (fast, modern) if available, otherwise standard `venv` as shown here.

```bash
cd ~/verity_uw

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the Verity package in editable mode
pip install -e ./verity
```

### What `pip install -e ./verity` does

This single command does two things:

1. **Installs all dependencies** listed in `verity/pyproject.toml` — psycopg, pydantic, fastapi, anthropic, etc. This is when all the Python libraries get installed. There is no separate `pip install -r requirements.txt` step needed.
2. **Registers `verity` as an importable package** so that `from verity import Verity` works from anywhere in the project. The `-e` (editable) flag creates a symlink to your source code — when you edit any file under `verity/verity/`, the change takes effect immediately without reinstalling.

**Why can't you just run `python verity/verity/cli.py` directly?** Because Python wouldn't know how to resolve `from verity.core.client import Verity` — it needs the package to be registered on the Python path first. The `pip install -e` step is what does that registration.

**Note on requirements.txt:** The `requirements.txt` at the project root exists only for the Docker build. For local development, `pip install -e ./verity` installs everything you need — the dependencies are defined in `verity/pyproject.toml` (the single source of truth).

### Verify Step 3

```bash
# Check Verity is importable
python -c "from verity import Verity; print('Verity imported successfully')"

# Check the CLI works
verity --help
```

---

## Step 4: Apply the Verity Database Schema

Now we apply the Verity schema (all the governance tables) to the `verity_db` database.

```bash
source .venv/bin/activate
verity init --database-url "postgresql://verityuser:veritypass123@localhost:5432/verity_db"
```

### Verify Step 4

```bash
# List all tables in verity_db
docker exec verity_postgres psql -U verityuser -d verity_db -c "\dt"
```

Expected: ~25 tables including `agent`, `agent_version`, `task`, `task_version`, `prompt`, `prompt_version`, `inference_config`, `tool`, `pipeline`, `agent_decision_log`, etc.

```bash
# Verify the lifecycle_state enum has all 7 values
docker exec verity_postgres psql -U verityuser -d verity_db -c "SELECT unnest(enum_range(NULL::lifecycle_state));"
```

Expected: 7 rows: `draft`, `candidate`, `staging`, `shadow`, `challenger`, `champion`, `deprecated`.

```bash
# Verify vector column exists on agent table
docker exec verity_postgres psql -U verityuser -d verity_db -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'agent' AND column_name = 'description_embedding';"
```

Expected: One row showing `description_embedding` with type `USER-DEFINED` (that's pgvector's vector type).

---

## Step 5: Run the Application (local development)

During development, you run the FastAPI app locally (not in Docker) so you get fast reload and easy debugging. The Docker `app` container is for deployment only.

```bash
cd ~/verity_uw
source .venv/bin/activate

# Run the UW demo app
uvicorn uw_demo.app.main:app --host 0.0.0.0 --port 8000 --reload
```

Then open http://localhost:8000/health — you should see `{"status": "healthy", "app": "uw_demo", "env": "demo"}`.

---

## What We Have After Setup


| Component     | URL            | Status                                                |
| --------------- | ---------------- | ------------------------------------------------------- |
| PostgreSQL    | localhost:5432 | Running, verity_db + pas_db created, pgvector enabled |
| MinIO API     | localhost:9000 | Running, buckets created                              |
| MinIO Console | localhost:9001 | Web UI for browsing documents                         |
| FastAPI App   | localhost:8000 | Running locally, /health endpoint working             |

---

## Stopping and Starting

```bash
# Stop all containers (preserves data in volumes)
docker compose down

# Start again (data persisted)
docker compose up -d postgres minio

# Nuclear option: stop and DELETE all data
docker compose down -v
# (the -v flag removes volumes — you'll need to redo Steps 1-3)
```

---

## Troubleshooting

### "port 5432 already in use"

Another PostgreSQL is running. Either stop it or change the port in docker-compose.yml:

```yaml
ports:
  - "5433:5432"  # Use 5433 externally
```

Then use port 5433 in all connection strings.

### "pgvector extension not found"

Make sure you're using the `pgvector/pgvector:pg16` image, not plain `postgres:16`. The pgvector image has the extension pre-installed.

### "permission denied" on init-multiple-dbs.sh

The script needs to be executable:

```bash
chmod +x scripts/init-multiple-dbs.sh
```

### MinIO buckets don't appear

If the minio-setup container ran before MinIO was healthy, re-run it:

```bash
docker compose up minio-setup
```

Or create them manually via the MinIO web console at http://localhost:9001.
