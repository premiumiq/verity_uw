# Verity + Vault: Production Readiness & K8s Migration Plan

> **Doc location note:** Per project convention (`feedback_no_shadow_docs`), once approved this file must be copied to `docs/architecture/production_readiness_plan.md`. This path exists only because plan mode requires it.
>
> **Naming:** `edms` is renamed to `vault` everywhere in this plan. The rename is a Phase 0 task (rename the directory, the Python package, the Docker service name, the env vars `EDMS_URL` → `VAULT_URL`, `EDMS_DB_URL` → `VAULT_DB_URL`, the bucket prefixes, and the docs).

---

## Context

Today's stack is a local `docker compose` demo: six services on one host, hardcoded credentials, no auth, no metrics, no CI, schemas applied on app startup, Python SDK calls in-process. That's fine for a CIO/CTO demo — it falls apart the moment two people need to run it or anything fails in a way the logs don't capture.

Goal: take the same four applications (`verity-api`, `verity-runtime`, `uw-demo`, `vault`) plus their data plane and make them deployable to any Kubernetes cluster with:

1. **Runtime fully separated** from Verity (own image, own pod, own scaling; shared DB with verity-api is OK).
2. **uw_demo decoupled** from Verity's in-process SDK (SDK import stays; under the hood it goes HTTP).
3. **Rename edms → vault** (Phase 0).
4. **Vault on its own Postgres instance** (not a second database on the shared cluster — a separate Postgres deployment).
5. **User management + role management + simple authentication** on both Verity and Vault (login page, sessions, API keys, role-based access).
6. **Secrets hygiene** — no hardcoded creds, K8s `Secret` objects, a single source of truth per secret.
7. **Observability** — Prometheus metrics, OpenTelemetry traces, Grafana dashboards.
8. **Target-agnostic manifests** — a Helm chart that runs on any cluster (Docker Desktop K8s, kind, k3d, EKS, GKE, on-prem).

Explicitly **out of scope this round**: CI/CD pipelines, HA Postgres with PITR/DR, multi-tenancy, service mesh, managed-cloud-specific resources, federated identity (OIDC/SAML), autoscaling beyond CPU-based HPA.

---

## Part A — What you need on your laptop (you're new to K8s)

### The short version
You have **Docker Desktop on Windows + WSL2 Ubuntu**. That's enough. Docker Desktop ships a single-node Kubernetes cluster you can enable with one checkbox. You do not need to install a cloud account, buy anything, or set up a separate VM.

### Tools to install

| Tool | What it is | Why you need it | How to get it |
|---|---|---|---|
| **Docker Desktop** | Already installed. Runs Docker + a tiny Kubernetes inside it. | Gives you a K8s cluster on your laptop. | Settings → Kubernetes → **Enable Kubernetes** → Apply. Wait ~2 min. |
| **kubectl** | CLI to talk to Kubernetes (`kubectl get pods`, etc.). | The primary tool you'll use. | `sudo apt install kubectl` in WSL Ubuntu. |
| **Helm** | Package manager for Kubernetes. Takes a "chart" (bunch of YAML templates) + your values and installs it. | This plan ships a Helm chart; you install the whole stack with `helm install`. | `sudo apt install helm` in WSL. |
| **k9s** | Terminal UI for Kubernetes. Shows pods, logs, events in real time. | Makes learning K8s much faster than raw `kubectl`. | `curl -sS https://webinstall.dev/k9s | bash` in WSL. |
| **stern** (optional) | Tail logs from multiple pods at once. | Useful for debugging. | `sudo apt install stern` or from GitHub releases. |

### Why Docker Desktop's built-in K8s and not kind/minikube/k3d?

All four work. For a beginner, Docker Desktop's built-in one is simplest because:
- It's **already there**, one checkbox.
- `kubectl` is auto-configured (you don't set up contexts).
- It integrates with Docker Desktop's image cache — `docker build` on your laptop produces an image that K8s can immediately use with `imagePullPolicy: Never`. No "push to registry" dance.
- It turns off with a checkbox when you don't want it running.

If you later outgrow it (you want multi-node, or want it to run without Docker Desktop), `kind` is the right next step. The Helm chart in this plan runs unchanged on either.

### Concepts you'll meet and what they mean

Before reading the rest of the plan, a 60-second glossary. Feel free to skim past if already familiar.

- **Pod** — one or more containers that run together on the same node and share a network. In our stack each service becomes one pod per replica.
- **Deployment** — tells K8s "always keep N copies of this pod running." If one crashes, K8s replaces it. This is what you use for stateless apps: verity-api, verity-runtime, uw-demo, vault.
- **StatefulSet** — like a Deployment but each pod has a stable name and its own storage volume. Use this for postgres and minio.
- **Service** — a stable DNS name + IP that load-balances to a set of pods. Other services talk to `verity-api:8000`, not to individual pod IPs.
- **Ingress** — an HTTP router that exposes Services to the outside world at a hostname. Optional in dev (you can `kubectl port-forward`); required in prod.
- **ConfigMap** — non-secret config (env vars, small files) you inject into pods.
- **Secret** — like ConfigMap but for sensitive values (DB passwords, API keys). Base64 encoded, stored in etcd, ideally encrypted at rest.
- **PersistentVolume (PV) / PersistentVolumeClaim (PVC)** — how pods get disk storage that survives restarts. Postgres and MinIO use this.
- **Job** — a pod that runs to completion then stops. We use Jobs for DB migrations and MinIO bucket creation.
- **Namespace** — a logical scope inside the cluster. We'll put everything in a `verity` namespace so it doesn't mingle with system pods.
- **Helm chart** — a bundle of templated YAML files + a `values.yaml` file. You customize values, Helm renders the YAML and applies it.

You will not need to hand-write any of these. You will edit `values.yaml` and run `helm install`.

---

## Part B — Current state assessment

### What's already good
- **Runtime is ~75% decoupled.** `verity-worker` (`python -m verity.runtime.worker`) is a separate CLI, stateless, claims runs via `FOR UPDATE SKIP LOCKED`, heartbeats.
- **Clean database boundaries.** Three databases (`verity_db`, `uw_db`, and the one we're renaming `edms_db` → `vault_db`) with no cross-DB joins. Vault already talks to uw_demo only over HTTP.
- **Structured JSON logging + correlation IDs** (`CorrelationMiddleware` in verity and vault).
- **Connection pooling** via `psycopg_pool.AsyncConnectionPool` (`verity/src/verity/db/connection.py`).

### What's demo-grade and will break in production
- **One shared `Dockerfile`** for verity-api, uw-demo, and verity-worker — they only differ by `command:`. Forces co-versioning, bloats every image.
- **Hardcoded credentials** in `docker-compose.yml` (`verityuser:veritypass123`, `minioadmin:minioadmin123`) and default fallbacks in `uw_demo/app/config.py`.
- **Zero authentication.** `POST /api/v1/runs/submit`, `POST /documents/upload` (vault), every uw_demo route — all open.
- **No user or role model at all.** The DB has no `user` table, no `role` table. Admin UI is wide open.
- **uw_demo uses the in-process SDK** (`verity.client.inprocess.Verity`) and opens a connection directly to `verity_db`. Defeats network-level isolation.
- **Schemas applied at app startup** via `apply_schema()` in the FastAPI lifespan. Works for demos; in K8s this races on multi-replica rollouts.
- **One shared Postgres** for all three databases. Vault should be on its own instance (your requirement), so blast radius of a Vault DB crash doesn't affect governance.
- **No tests, no CI/CD, no Prometheus/OTEL, no lockfile.** `requirements.txt` is not pinned transitively.

---

## Part C — Target topology

```
┌──────────────────────────────────────────────────────────────┐
│                  Kubernetes cluster (namespace: verity)      │
│                                                               │
│  ┌──────────────┐   ┌────────────────┐   ┌────────────────┐ │
│  │  verity-api  │   │ verity-runtime │   │    uw-demo     │ │
│  │ (govern+UI)  │   │ (worker × N)   │   │   (FastAPI)    │ │
│  │  login/RBAC  │   │                │   │                │ │
│  └──────┬───────┘   └────────┬───────┘   └──────┬─────────┘ │
│         │                    │                   │           │
│         │       HTTP (service key)                           │
│         │◄───────────────────┘                   │           │
│         │◄───────────────────────────────────────┤           │
│         │                                         │           │
│         │                ┌──────────────┐        │           │
│         │                │    vault     │◄───────┘           │
│         │                │  login/RBAC  │                    │
│         │                └──────┬───────┘                    │
│         │                       │                             │
│   ┌─────▼─────────────┐   ┌─────▼──────────┐   ┌──────────┐ │
│   │  postgres-verity  │   │ postgres-vault │   │  minio   │ │
│   │  (StatefulSet)    │   │ (StatefulSet)  │   │  (STS)   │ │
│   │  verity_db,uw_db  │   │   vault_db     │   │          │ │
│   └───────────────────┘   └────────────────┘   └──────────┘ │
│                                                               │
│  Bootstrap Jobs: migrate-verity, migrate-vault, minio-setup, │
│                  seed (optional)                              │
└──────────────────────────────────────────────────────────────┘
```

Two Postgres instances (your requirement). MinIO stays single because it's only used by vault. verity-runtime shares `postgres-verity` with verity-api (your runtime-split choice).

---

## Part D — Roadmap

Each phase leaves the system working. You can ship them one at a time. The "Why", "What changes", and "How to see it worked" are spelled out so you can execute yourself (per `feedback_explain_commands` and `feedback_explain_before_change`).

---

### Phase 0 — Rename edms → vault

**Why:** naming lands cleanly before the auth and schema work pile on top. Trying to rename later means touching user-facing URLs and migration scripts.

**What changes:**
- Rename directory `edms/` → `vault/`.
- Rename Python package `edms` → `vault` (module imports).
- Rename service in `docker-compose.yml`: `edms:` → `vault:`.
- Rename env vars: `EDMS_URL` → `VAULT_URL`, `EDMS_DB_URL` → `VAULT_DB_URL`.
- Rename DB: `edms_db` → `vault_db` in `scripts/init-multiple-dbs.sh` (still shared Postgres at this point; split comes in Phase 6 data plane).
- Rename `uw_demo/app/edms_provider.py` → `vault_provider.py`, `uw_demo/app/tools/edms_tools.py` → `vault_tools.py`.
- Update all docs in `docs/architecture/` and `docs/guides/` (grep + replace).

**How to see it worked:** `docker compose up` runs the renamed service; uw_demo loads submission documents from vault exactly as before.

---

### Phase 1 — Per-service Dockerfiles + pinned deps

**Why:** one image per service is the foundation of independent deploy, scale, and rollback. Today all three Python services share a single image, which means an upgrade to uw_demo forces re-rolling verity-api for no reason.

**What changes:**
- Split into four Dockerfiles:
  - `verity/Dockerfile` — builds `verity-api` (the governance plane + admin UI; **does not** install the `[runtime]` extra, saves ~300MB of LLM SDKs and reduces attack surface).
  - `verity/Dockerfile.runtime` — installs `verity[runtime]`, entrypoint `python -m verity.runtime.worker`.
  - `uw_demo/Dockerfile` — uw_demo only; depends on a built `verity` wheel, no bind-mount of verity source.
  - `vault/Dockerfile` — already separate, just verify it works without bind-mounts.
- Introduce `uv` as the dependency manager (faster than pip, produces a `uv.lock`).
- Multi-stage builds (builder + runtime) to keep images small.
- Non-root user (`USER 10001`), OCI labels (`org.opencontainers.image.source`, `version`).

**How to see it worked:** `docker build` each image, then `docker run --env-file .env.sample <image>` with no bind-mounts. Each image starts cleanly.

---

### Phase 2 — Runtime extraction at the deploy boundary

**Why:** delivers your core ask: runtime becomes an independently deployable service, scaled and versioned separately from Verity.

**Note:** we are not splitting the source tree. `verity/runtime/*.py` stays inside the `verity` package (the `[runtime]` extra in `pyproject.toml` already gates the heavy deps). The split is at the image + Deployment level — that's the right amount of separation for "shared DB" mode (your pick).

**What changes:**
- Confirm `verity-runtime` reads only env (`VERITY_DB_URL`, `ANTHROPIC_API_KEY`, `VERITY_WORKER_APPLICATION`, `VAULT_URL`); remove the `.env` file loader from the worker path.
- Add `--metrics-port 9090` to the worker so Prometheus can scrape it (used in Phase 5).
- Document the shared-DB contract explicitly in `docs/architecture/runtime_db_contract.md`:
  - **Runtime reads:** `agent_version`, `task_version`, `prompt`, `inference_config`, `tool_authorization`, `source_binding`, `write_target`
  - **Runtime writes:** `agent_decision_log`, `execution_run`, `workflow_run`
  - Anything else is off-limits — a contract we can enforce later with a DB role per service.

**How to see it worked:** `docker compose up verity-runtime` with `verity-api` stopped — runtime keeps draining runs. `docker compose up verity-api` with `verity-runtime` stopped — API responds but submitted runs sit in `pending` until the worker comes back.

---

### Phase 2.5 (optional) — NATS JetStream dispatch layer

**Defer until you see one of:** (a) polling load on `execution_run` is measurable in `pg_stat_activity` with >10 workers; (b) you want multiple independent consumers of run events (e.g. an analytics sink or a live dashboard); (c) you need proper DLQ/backoff semantics that are painful to build in SQL. Until then, Postgres-as-queue is enough and strictly simpler.

**Why:** Postgres stays the source of truth; NATS becomes a low-latency *dispatch notification* layer so workers don't poll. This is the transactional outbox pattern — adds resilience (retries/DLQ), scalability (no hot-row contention under load), and decoupling (a different runtime implementation can subscribe to the same topic tomorrow).

**Why NATS and not Redpanda:** ~20 MB single binary vs ~200 MB distributed log; 3 small pods for HA vs a memory-hungry cluster; runs identically on laptop, any K8s, or Synadia Cloud. Redpanda is a great tool if you need Kafka-wire compatibility for downstream streaming consumers (Flink, Debezium, Spark) — we don't.

**What changes:**

1. **New outbox table** in `verity_db`:
   ```sql
   CREATE TABLE run_dispatch_outbox (
       id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       execution_run_id UUID NOT NULL REFERENCES execution_run(id),
       payload        JSONB NOT NULL,
       published_at   TIMESTAMPTZ,
       attempts       INT NOT NULL DEFAULT 0,
       last_error     TEXT,
       created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
   );
   CREATE INDEX ON run_dispatch_outbox (published_at) WHERE published_at IS NULL;
   ```

2. **`verity-api` submit path** (unchanged on the outside):
   - Same DB transaction inserts the `execution_run` row **and** a `run_dispatch_outbox` row.
   - No direct NATS publish from the API handler — it's always safe to commit, even if NATS is down.

3. **New tiny service `verity-relay`** (~50 lines of Python):
   - Reads unpublished rows from `run_dispatch_outbox` (with `FOR UPDATE SKIP LOCKED`), publishes to NATS subject `verity.runs.pending`, marks `published_at`. Retries forever on NATS failure, emits a metric.
   - Runs as a Deployment with 1 replica (it's idempotent; duplicate publishes are fine because workers dedupe on row status).

4. **`verity-runtime` workers**:
   - Subscribe to `verity.runs.pending` via a durable JetStream consumer (consumer group `verity-runtime`).
   - On message: attempt to claim by updating `execution_run.status` from `pending` to `running` (optimistic concurrency). If another worker already claimed, ack-and-skip. If claim succeeded, run it, write decisions, ack.
   - On worker crash: JetStream redelivers after ack-timeout (default 30s) — combined with the row-based claim, this is at-least-once with natural dedup.
   - Remove the `FOR UPDATE SKIP LOCKED` poll loop. (Keep it as a fallback code path gated by `VERITY_DISPATCH_MODE=postgres` so you can flip back instantly.)

5. **New reconciliation Job** (`verity-dispatch-sweep`, runs every 60s as a CronJob):
   - Finds rows where `execution_run.status='pending'` and `run_dispatch_outbox.published_at IS NOT NULL AND created_at < now() - interval '5 minutes'` — meaning the message was published but no worker claimed it. Republishes.
   - Catches the rare "NATS lost the message" case without needing to trust NATS for durability.

6. **NATS deployment**:
   - Helm chart `nats` (official) as a subchart, 3-replica JetStream cluster.
   - PVC-backed for durability; ~5 Gi per replica in dev, tune in prod.
   - NetworkPolicies: `verity-api` (no, it writes to DB only), `verity-relay` → NATS publish, `verity-runtime` → NATS subscribe.

**Feature flag:** `values.dispatch.mode=nats|postgres` (default `postgres`). Flipping to `nats` requires the NATS subchart and the relay Deployment to be enabled.

**How to see it worked:** `VERITY_DISPATCH_MODE=nats`, submit 100 runs at once, watch worker claim latency drop from poll-interval (~2s) to <50ms. Kill a worker mid-run → JetStream redelivers → another worker claims → run completes. Stop NATS entirely → submit continues working (rows land in outbox) → start NATS → relay drains the outbox.

**What this does not buy you:** it does not replace Postgres, does not change the API contract, does not make runs "faster" except in dispatch latency. The value is in resilience and the ability to add more consumers of run events without touching the DB.

---

### Phase 3 — uw_demo switches to HTTP

**Why:** uw_demo should not hold a connection to `verity_db` in production. The HTTP client path is already planned (`verity/src/verity/client/http.py` referenced in the split plan but not yet implemented).

**What changes:**
- Implement `verity/src/verity/client/http.py` — same surface as `inprocess.Verity` (`execute_pipeline`, `register_tool_implementation`, `get_audit_trail`) but dispatches to `/api/v1/*` via `httpx`.
- Make `verity.Verity(...)` pick the transport: if `database_url=` is passed → inprocess; if `api_url=` is passed → http. Import stays `from verity import Verity`, uw_demo code doesn't change.
- Update `uw_demo/app/main.py` to construct with `api_url=settings.VERITY_API_URL` and remove `VERITY_DB_URL` from uw-demo's env.
- Tool callbacks: uw_demo keeps tool implementations in-process; it subscribes to "tool needed" events for its own runs via a new endpoint `GET /api/v1/runs/{id}/tool-requests` (long-polling). This keeps tool code inside the business app where it belongs.

**How to see it worked:** while uw_demo processes a submission, `SELECT usename, application_name FROM pg_stat_activity WHERE datname='verity_db'` shows only `verity-api` and `verity-runtime`, never `uw-demo`.

---

### Phase 4 — User management, roles, authentication (Verity + Vault)

**Why:** you asked for this, and everything else (secrets hygiene, auth gateway, audit attribution) depends on it. Simple = local username/password, server-side sessions for the web UI, API keys for programmatic access. No OIDC/SAML this round.

**Design (applies to both Verity and Vault):**

**New DB tables** (added to both `verity_db` and `vault_db` — same schema, independent data; later we could unify via an auth service, not this round):

```sql
CREATE TABLE app_user (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT,
    password_hash TEXT,          -- bcrypt; NULL if disabled
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE role (
    id   TEXT PRIMARY KEY,       -- e.g. 'admin', 'governance_editor', 'operator', 'viewer'
    description TEXT
);

CREATE TABLE user_role (
    user_id UUID REFERENCES app_user(id) ON DELETE CASCADE,
    role_id TEXT REFERENCES role(id),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE api_key (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES app_user(id),
    name         TEXT NOT NULL,              -- human label
    key_hash     TEXT NOT NULL,              -- bcrypt of the raw key
    key_prefix   TEXT NOT NULL,              -- first 8 chars, for display
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ
);

CREATE TABLE session (
    id         TEXT PRIMARY KEY,              -- opaque random token stored in cookie
    user_id    UUID REFERENCES app_user(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Initial roles** (seeded on first migrate):

| Role | Permissions (Verity) | Permissions (Vault) |
|---|---|---|
| `admin` | Everything, including user/role management, API key issuance, deleting decisions, promoting lifecycle states | Everything, including uploading, deleting, managing collections |
| `governance_editor` | Register agents/tasks/prompts/tools; draft-edit; request lifecycle promotions; read decisions | Read-only |
| `operator` | Submit runs, read own runs, read decisions for visible agents | Upload documents, read documents |
| `viewer` | Read-only on registry and decisions | Read-only |

**What changes in code:**
- New module `verity/src/verity/auth/` with `passwords.py` (bcrypt), `sessions.py`, `permissions.py` (role → permission mapping), `middleware.py` (FastAPI dependency that resolves session cookie OR `X-API-Key` header → current user → permissions).
- Same module structure inside `vault/src/vault/auth/`.
- Login page (`/login`) and logout (`/logout`) added to both admin UIs (Jinja2 templates).
- Admin page (`/admin/users`, `/admin/roles`, `/admin/api-keys`) gated to `admin` role.
- Every existing route decorated with a `requires(permission)` dependency. Missing permission → 403.
- First-boot bootstrap: on the first run after migration, if zero users exist, print a one-time password for a new `admin@localhost` user to the logs and require password change on first login.
- Service-to-service calls (uw-demo → verity-api, runtime → verity-api if needed) use a **service API key** stored in a K8s Secret. Service keys belong to a system user `system:<service>` with a restricted role.

**What changes in config:**
- Remove hardcoded creds from `docker-compose.yml` and `uw_demo/app/config.py` defaults. Missing env → explicit startup error.
- ds-workbench: `JUPYTER_TOKEN` from secret, `--allow-origin=*` removed.

**How to see it worked:** `curl /api/v1/runs/submit` without a key → 401. With the operator service key → 200. Log in to `/admin/users` as admin; create a new user with `viewer` role; try to register an agent as that user → 403.

---

### Phase 5 — Observability

**Why:** you can't operate what you can't see. Today there's no way to know the worker's queue depth or which agent is burning tokens.

**What changes:**
- **Metrics:**
  - Add `prometheus-fastapi-instrumentator` to verity-api, uw-demo, vault — gives you `/metrics` with request count, latency histograms, in-flight gauges for free.
  - verity-runtime isn't FastAPI; embed `prometheus_client` and start an HTTP server on the `--metrics-port`.
  - Custom metrics that matter day one:
    - `verity_runtime_runs_claimed_total{application}`
    - `verity_runtime_run_duration_seconds{application,status}` (histogram)
    - `verity_runtime_queue_depth` (gauge, derived from `SELECT count(*) FROM execution_run WHERE status='pending'`)
    - `verity_decisions_written_total{entity_type}`
    - `verity_llm_tokens_total{model,kind}` (kind = input|output|cache)
- **Tracing:** OpenTelemetry Python SDK, auto-instrument FastAPI + psycopg + httpx + anthropic. Every span carries `correlation_id`, `workflow_run_id`, `execution_run_id`, `user_id` (from Phase 4). OTLP exporter to a collector.
- **Logs:** already JSON on stdout — K8s just collects them. Promtail+Loki added as optional subchart, off by default.
- **Dashboards** shipped as JSON under `k8s/observability/dashboards/`:
  - Verity Runtime: queue depth, runs/min by status, p50/p95 duration, worker heartbeat freshness
  - Verity API: RPS, latency, error rate by route, by user
  - LLM Spend: tokens/min, cost estimate joined with `model.pricing`
  - Vault: upload rate, bytes stored, failed text extractions
  - Postgres (via `postgres_exporter` subchart): connections, tx rate, slow queries
- `kube-prometheus-stack` included as an **optional subchart** (off by default; opt in via `observability.prometheus.enabled=true`). OpenTelemetry Collector as a Deployment.

**How to see it worked:** enable the observability stack in `values.yaml`, run `helm upgrade`, open Grafana → queue depth is zero, submit a run → it spikes to 1 then drops.

---

### Phase 6 — Helm chart (target-agnostic manifests)

**Why:** one `helm install` command turns the whole stack up on any cluster. Target-agnostic = no cloud-specific CRDs. Works on Docker Desktop K8s, kind, EKS, everything.

**Chart layout** under `k8s/charts/verity/`:

```
k8s/charts/verity/
├── Chart.yaml
├── values.yaml                  # dev-friendly defaults
├── values-prod.yaml.example     # prod overrides
├── templates/
│   ├── _helpers.tpl
│   ├── namespace.yaml
│   ├── serviceaccounts.yaml
│   ├── configmap-app.yaml
│   ├── secret-stubs.yaml
│   ├── verity-api/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   └── hpa.yaml
│   ├── verity-runtime/
│   │   ├── deployment.yaml      # replicas: N; no Service
│   │   └── hpa.yaml             # CPU-based to start
│   ├── uw-demo/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── vault/
│   │   ├── deployment.yaml
│   │   └── service.yaml
│   ├── postgres-verity/         # STS for verity+uw dbs
│   │   ├── statefulset.yaml
│   │   ├── service.yaml
│   │   └── configmap-init.yaml  # creates verity_db, uw_db
│   ├── postgres-vault/          # STS for vault_db (separate instance)
│   │   ├── statefulset.yaml
│   │   ├── service.yaml
│   │   └── configmap-init.yaml  # creates vault_db
│   ├── minio/
│   │   ├── statefulset.yaml
│   │   └── service.yaml
│   ├── jobs/
│   │   ├── migrate-verity.yaml  # pre-install, pre-upgrade Helm hook
│   │   ├── migrate-vault.yaml   # pre-install, pre-upgrade Helm hook
│   │   ├── minio-setup.yaml     # post-install Helm hook
│   │   ├── bootstrap-users.yaml # creates initial admin user
│   │   └── seed.yaml            # gated by values.seed.enabled
│   └── ingress.yaml             # optional, values.ingress.enabled
└── charts/                       # subcharts: postgres-exporter, otel-collector, kube-prometheus-stack (disabled by default)
```

**Values matrix** (what changes between dev and prod):

| Key | Dev default | Prod override |
|---|---|---|
| `verityApi.replicas` | 1 | 2+ |
| `verityRuntime.replicas` | 1 | 3+ |
| `verityRuntime.autoscaling.enabled` | false | true (min 2, max 10) |
| `postgresVerity.persistence.size` | 5Gi | 100Gi |
| `postgresVault.persistence.size` | 5Gi | 100Gi |
| `postgresVerity.external.enabled` | false | optional (skip STS, use existing DB) |
| `minio.persistence.size` | 5Gi | 100Gi |
| `ingress.enabled` | false (use port-forward) | true |
| `observability.prometheus.enabled` | false | true |
| `observability.otelCollector.enabled` | false | true |
| `auth.initialAdmin.email` | admin@localhost | real email |

**What the install sequence looks like for you** (what you'd actually run):

```bash
# one-time
kubectl create namespace verity

# build images locally (Docker Desktop K8s can see them directly)
docker build -t verity-api:dev -f verity/Dockerfile .
docker build -t verity-runtime:dev -f verity/Dockerfile.runtime .
docker build -t uw-demo:dev -f uw_demo/Dockerfile .
docker build -t vault:dev -f vault/Dockerfile .

# install the chart
helm install verity ./k8s/charts/verity \
  -n verity \
  --set images.tag=dev \
  --set images.pullPolicy=Never

# watch it come up (k9s shows this beautifully)
k9s -n verity

# open the admin UI
kubectl port-forward -n verity svc/verity-api 8000:8000
# then visit http://localhost:8000 in your browser
```

**How to see it worked:** all pods `Running`, migrate-verity and migrate-vault Jobs `Completed`, `/health` returns 200 on every service, you can log into the admin UI with the initial admin password printed in the bootstrap-users Job logs.

---

### Phase 7 — Data plane bootstrapping as Jobs

**Why:** today, schemas are applied on app startup. In K8s this races on multi-replica rollouts, hides migration errors, and makes rollbacks dangerous.

**What changes:**
- Promote `verity migrate` (already exists as a CLI) to be the only path to schema changes.
- `templates/jobs/migrate-verity.yaml` runs as a Helm `pre-install,pre-upgrade` hook. Applies:
  - `verity/src/verity/db/schema.sql`
  - `uw_demo/app/db/schema.sql`
  - `verity/src/verity/db/migrations/*.py` (e.g. `unified_wiring`)
- `templates/jobs/migrate-vault.yaml` same, but for `vault/src/vault/schema.sql` against the separate Postgres instance.
- `templates/jobs/minio-setup.yaml` runs post-install, creates buckets and service credentials for vault.
- `templates/jobs/bootstrap-users.yaml` runs post-install, seeds roles + initial admin (prints one-time password to logs).
- `templates/jobs/seed.yaml` runs seed scripts (UW submissions, vault docs) **only if `values.seed.enabled=true`**. Off in prod.
- App startup code loses its `apply_schema()` call; instead reads a `schema_version` row and refuses to start if out of date. That's how you catch a missed migrate.

**How to see it worked:** `helm install` on a fresh namespace — the migrate Job finishes before any app pod becomes `Ready`. Roll back to an older chart version → pre-upgrade migrate Job detects the downgrade and fails the upgrade (a feature, not a bug — prevents schema/code drift).

---

### Phase 8 — Hardening and end-to-end verification

**Why:** everything up to here is about structure. This phase is about making it robust and proving it.

**What changes:**
- **Readiness probes** hit `/health` (HTTP). **Liveness probes** check process responsiveness but do not cascade on DB availability (liveness should not kill pods on transient infra hiccups).
- **Runtime readiness:** worker maintains a row in `worker_heartbeat`; readiness probe checks its own heartbeat freshness in-process.
- **Resource requests/limits** on every Deployment. Starting point: CPU 100m/500m, memory 256Mi/1Gi. Tune from Grafana after the first soak.
- **PodSecurityStandard: restricted.** `runAsNonRoot: true`, `readOnlyRootFilesystem: true`, no `capabilities.add`, `seccompProfile: RuntimeDefault`.
- **NetworkPolicies** (templates included, enabled via `values.networkPolicies.enabled`):
  - uw-demo → verity-api:8000, vault:8002 only
  - verity-runtime → postgres-verity:5432, vault:8002, egress to `api.anthropic.com:443`
  - verity-api → postgres-verity:5432 only
  - vault → postgres-vault:5432, minio:9000 only
- **PodDisruptionBudgets** on postgres-verity, postgres-vault, minio (`minAvailable: 1`).
- **End-to-end smoke test** (`scripts/smoke-e2e.sh`): `helm install` in a fresh namespace → port-forward → submit a run → assert `agent_decision_log` has new rows, runtime pod logs show the run, Grafana shows metrics.

**How to see it worked:** smoke-e2e passes green on a fresh Docker Desktop K8s cluster.

---

## Part E — Critical files to touch

| Phase | Files |
|---|---|
| 0 | everything under `edms/`, `uw_demo/app/edms_*`, `docker-compose.yml`, `scripts/init-multiple-dbs.sh`, `docs/architecture/*` (grep for edms) |
| 1 | `Dockerfile` (split into 4), new `uv.lock`, `verity/pyproject.toml`, `vault/pyproject.toml` |
| 2 | `verity/src/verity/cli.py`, `verity/src/verity/runtime/worker.py`, new `docs/architecture/runtime_db_contract.md` |
| 2.5 (optional) | `verity/src/verity/db/schema.sql` (+ `run_dispatch_outbox`), new `verity/src/verity/dispatch/` module (publisher + subscriber), new `verity-relay` CLI entry, `verity/src/verity/runtime/worker.py` (NATS consumer path), chart additions for NATS subchart + `verity-relay` Deployment + sweep CronJob |
| 3 | new `verity/src/verity/client/http.py`, `verity/src/verity/client/__init__.py`, `uw_demo/app/main.py`, new route `verity/src/verity/web/api/tool_requests.py` |
| 4 | new `verity/src/verity/auth/*`, new `vault/src/vault/auth/*`, `verity/src/verity/db/schema.sql` (+ auth tables), `vault/src/vault/schema.sql` (+ auth tables), `verity/src/verity/web/templates/login.html`, admin pages, middleware wired into `main.py`, removal of hardcoded creds from `docker-compose.yml` and `uw_demo/app/config.py` |
| 5 | `verity/src/verity/main.py` (instrumentator), `verity/src/verity/runtime/worker.py` (prom client + metrics port), `vault/src/vault/service/main.py`, `uw_demo/app/main.py`, new `verity/src/verity/observability/*`, new `k8s/observability/dashboards/*.json` |
| 6 | entire `k8s/charts/verity/` tree |
| 7 | `verity/src/verity/db/migrate.py` (standalone CLI), remove `apply_schema()` from lifespans, add `schema_version` check |
| 8 | chart probe/resource/netpol templates, new `scripts/smoke-e2e.sh` |

---

## Part F — Verification

1. **Per-phase unit checks** (each phase self-contained):
   - Phase 0: `docker compose up` works; vault serves the same routes as before at the renamed service.
   - Phase 1: `docker build && docker run` each image with only env vars; no bind-mounts.
   - Phase 2: stop `verity-api`, `verity-runtime` keeps draining runs submitted via direct DB insert.
   - Phase 3: `SELECT application_name FROM pg_stat_activity WHERE datname='verity_db'` never shows `uw-demo`.
   - Phase 4: 401 without key / 403 with wrong role / 200 with right role; admin UI login works.
   - Phase 5: `curl /metrics` on each service; query Prometheus for `verity_runtime_queue_depth`.
   - Phase 6: `helm lint && helm template | kubectl apply --dry-run=server -f -` passes.
   - Phase 7: fresh `helm install` → migrate Job finishes before any app becomes Ready.
   - Phase 8: `scripts/smoke-e2e.sh` green.

2. **End-to-end happy path** (the demo you'd give):
   - Docker Desktop → Enable Kubernetes.
   - `docker build` the four images locally.
   - `helm install verity ./k8s/charts/verity -n verity --set images.pullPolicy=Never`.
   - Wait for all pods `Running` (k9s).
   - `kubectl port-forward svc/verity-api 8000:8000`.
   - Log in as admin, see your first successful login in `last_login_at`.
   - `kubectl port-forward svc/uw-demo 8001:8001`.
   - Process a submission end-to-end.
   - Confirm new rows in `agent_decision_log`, runtime pod logs show the run, Grafana (if enabled) shows the spike in queue depth then runs/min.

3. **Rollback rehearsal:**
   - `helm upgrade` with a deliberately broken image tag → rollout stuck on readiness → `helm rollback verity 1 -n verity` → back to healthy. Confirms deployments are atomic and recoverable.

---

## Part G — Sequencing & time estimate

Each phase ships standalone. You can stop after any phase and the system is better than before.

| Week | Phases | What you get at the end |
|---|---|---|
| 1 | 0, 1 | `vault` naming landed; four independent images |
| 2 | 2 | `verity-runtime` runs as its own container, scales independently |
| — | 2.5 (optional, deferred) | NATS JetStream + transactional outbox; flip `dispatch.mode=nats` when polling becomes painful |
| 3 | 3 | `uw-demo` no longer connects to `verity_db`; all Verity calls go HTTP |
| 4 | 4 (part A: DB tables + bcrypt + sessions) | Login page works on Verity; admin can create users |
| 5 | 4 (part B: roles + API keys + vault copy) | Role-gated routes; vault has its own auth; service API keys wired |
| 6 | 5 | Metrics and traces visible on compose (Prometheus + OTEL collector as compose services for now) |
| 7 | 6 | First `helm install` on Docker Desktop K8s; stack running in Kubernetes |
| 8 | 7, 8 | Migrate Jobs replace startup schema apply; probes, limits, NetworkPolicies; smoke-e2e green |

About **8 weeks of focused work** to go from "compose demo" to "runs on any K8s cluster with auth, RBAC, metrics, and traces." Everything stays runnable on your laptop throughout; no phase requires a cloud account or paid service.

---

## Part H — What we're deliberately *not* doing this round

Calling these out so scope doesn't creep:

- **CI/CD pipelines** — GitHub Actions for lint/test/build/push. Worth a separate round once tests exist.
- **HA Postgres** — CloudNativePG or Crunchy operator with replicas, PITR, backups. Big topic; plain StatefulSet is fine for now.
- **Federated identity** (OIDC/SAML). Local username/password is enough for this round. OIDC is a drop-in later because the middleware already abstracts "resolve request → user".
- **Multi-tenancy** — the data model partially supports it (`application` anchors) but UI, RBAC scoping, and quota enforcement are not in scope.
- **Service mesh** (Istio/Linkerd) — NetworkPolicies cover the current threat model.
- **Managed-cloud-specific resources** — cloud LB annotations, cloud storage classes. Target-agnostic chart means none of that is baked in.
- **Autoscaling beyond CPU-based HPA** — queue-depth-based scaling for the runtime is a natural follow-up once metrics land, but not required to ship.
