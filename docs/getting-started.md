# Getting Started

Stand up Verity, [Vault][vault], and the reference [UW demo application][application] on Docker Compose, end-to-end, in about 15 minutes.

This is the fastest path to a working setup. For a deeper walkthrough of each service, the database, or troubleshooting, see [guides/initial_setup.md](guides/initial_setup.md). For the day-2 reading after this, jump straight to the [worked end-to-end example](example-end-to-end.md).

---

## Prerequisites

- **Docker Desktop** running (Mac/Windows) or Docker Engine + Compose v2 (Linux). Allocate at least **8 GB RAM** to Docker.
- **Anthropic API key** (any tier). Set as `ANTHROPIC_API_KEY` in `.env` below.
- **~5 GB disk** for images, the postgres volume, and the MinIO volume.
- (Optional) **Python 3.12** if you want to run scripts outside Docker (e.g. the seed scripts or the `ds_workbench` Jupyter kernel).

> No Python install needed for the basic Docker path — every service runs in a container.

---

## Step 1 — Clone and configure

```bash
git clone <this-repo> verity_uw
cd verity_uw
```

Create a `.env` file at the project root with your Anthropic API key. The compose file expects one variable:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
```

That's the only required setting. Postgres credentials, MinIO credentials, and service URLs are set in `docker-compose.yml` with safe defaults for local development.

---

## Step 2 — Start the stack

```bash
docker compose up -d
```

First-time startup builds the `verity`, `edms` (Vault), and `uw_demo` images and pulls postgres + MinIO. Allow ~3–5 minutes.

Check everything is healthy:

```bash
docker compose ps
```

You should see all containers in `running (healthy)` state. The `minio-setup` and any `*-setup` containers are one-shot — they exit cleanly after creating buckets / running migrations.

---

## Step 3 — What's running and where

| Service | URL | Purpose |
|---|---|---|
| `postgres` | `localhost:5432` | `verity_db`, `edms_db` (Vault), `uw_db` |
| `minio` (object store) | `localhost:9000` (API) · `localhost:9001` (Web console) | Document blobs |
| `edms` (Vault) | `http://localhost:8002` | Document side app + Web UI |
| `verity` | `http://localhost:8000` | Governance + Runtime + Admin UI |
| `uw_demo` | `http://localhost:8001` | Reference UW application |
| `ds_workbench` | `http://localhost:8888` | JupyterLab against Verity REST API |

> **Naming note:** the **service** is named `edms` in `docker-compose.yml` and the **directory** is `edms/`. In docs we now call it [Vault][vault] — the rename to code/env vars is tracked as Phase 0 of [enhancements/production-readiness-k8s.md](enhancements/production-readiness-k8s.md).

MinIO console default login: `minioadmin` / `minioadmin123`. Postgres default login: `verityuser` / `veritypass123`.

---

## Step 4 — Seed the demo

The empty stack has no governed entities yet. Two seed scripts populate it: one for [Vault][vault] (sample submission documents) and one for Verity (the four UW agents/tasks plus their compositions).

Run them inside the existing `verity` container so you don't need a local Python install:

```bash
# Vault: upload sample submission PDFs and run text extraction
docker compose exec verity python -m uw_demo.app.setup.seed_edms

# Verity: register the uw_demo application + agents/tasks/prompts/tools/connectors
docker compose exec verity python -m uw_demo.app.setup.seed_uw
```

Each script is idempotent — re-running them won't duplicate rows; entities already at the latest version stay put.

After seeding you'll see in the Verity Admin UI:

- 1 [application][application] (`uw_demo`)
- 2 [Tasks][task]: `document_classifier`, `field_extractor`
- 2 [Agents][agent]: `triage_agent`, `appetite_agent`
- ~6 [prompts (versioned)][prompt-version], 2 [inference configs][inference-config], 4 [tools][tool-authorization], 1 [data connector][data-connector] (`vault`)
- All four execution units promoted to `champion` via the fast-track (`candidate → champion`)

---

## Step 5 — Verify the UI

Open in your browser:

1. **Verity Admin UI** → http://localhost:8000
   - Dashboard tile counts: 1 application, 4 governed entities, 0 decisions (yet)
   - Click **Registry** → see the seeded agents and tasks with their versions
   - Click **Lifecycle** → all four show as `champion`
2. **UW Demo app** → http://localhost:8001
   - Submission list: 2–3 sample submissions (Acme Dynamics, TechFlow, …)
   - Click one to open the submission detail page
3. **Vault** → http://localhost:8002
   - Browse the `underwriting` collection → submission folders → uploaded PDFs

If any of the UIs don't load, check `docker compose logs <service>` for the failed container.

---

## Step 6 — Run a workflow end-to-end

From the UW demo submission detail page (port 8001), click **Process Documents** on a submission. The app:

1. Generates a fresh [`workflow_run_id`][workflow-run-id]
2. Pulls the document index from Vault (originals only)
3. Calls `verity.execute_task("document_classifier", ...)` per document
4. For documents classified as `do_application`, calls `verity.execute_task("field_extractor", ...)`

Then click **Run Risk Assessment**:

1. New [`workflow_run_id`][workflow-run-id], same [`execution_context_id`][execution-context]
2. Calls `verity.execute_agent("triage_agent", ...)`
3. Calls `verity.execute_agent("appetite_agent", ...)` with the triage output

Each call writes to the [decision log][decision-log]. Open the Verity Admin UI → **Decisions** to see the rows landing in real time. Click any row to see the full I/O, tool calls, message history, and token cost.

For the full walkthrough of what every step writes to the database, see [example-end-to-end.md](example-end-to-end.md).

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `ANTHROPIC_API_KEY` not set | Missing or empty `.env` | `cat .env` to check; key must be on a single line, no quotes needed |
| `verity` container fails health check | Postgres still bootstrapping | Wait ~30s and `docker compose ps` again; or check `docker compose logs postgres` |
| MinIO buckets missing | `minio-setup` container errored on first run | `docker compose up minio-setup` to re-run it |
| Seed scripts complain about missing tables | Verity migrations didn't run | `docker compose exec verity python -m verity.db.migrate` |
| Port already in use | Something else on 5432/8000/8001/8002/9000/9001/8888 | Edit `docker-compose.yml` to remap, or stop the conflicting service |
| `model_invocation_log` row count not increasing after a run | Wrong `ANTHROPIC_API_KEY` (calls 401-ing) | Check `docker compose logs verity` for HTTP 401 from Anthropic |

---

## Tear down

Stop everything but keep the data:

```bash
docker compose down
```

Stop and **delete** the postgres + MinIO volumes (full reset):

```bash
docker compose down -v
```

After a `down -v` you'll need to re-run the seed scripts in Step 4.

---

## Next steps

1. **Read** [example-end-to-end.md](example-end-to-end.md) — the same flow you just clicked through, with sequence diagrams, JSON contracts, status transitions, and a summary table of every database row written for one submission.
2. **Build something** — [development/application-guide.md](development/application-guide.md) walks through anatomy of [Tasks][task] and [Agents][agent], the composition handbook, and orchestration patterns. Single ~700-line doc with TOC.
3. **Look up a term** — [glossary/](glossary/README.md) (48 terms).
4. **See what's planned next** — [enhancements/](enhancements/README.md).


<!-- ─────────────────────── Glossary references ─────────────────────────────── -->
<!-- Hover linked terms above for tooltips; click to read the full glossary entry. -->
[application]: glossary/application.md "Consuming business app registered with Verity; every entity and decision is scoped/attributed to one or more applications."
[vault]: glossary/vault.md "Companion document service (collections, lineage, tags, text extraction). Independent DB. Verity reaches it via the canonical data_connector."
[task]: glossary/task.md "Single-shot LLM call with input_schema → structured output_schema. No tool loop, no sub-agents."
[agent]: glossary/agent.md "Multi-turn agentic loop with tool use and (optionally) sub-agent delegation. Authorized tools per version."
[prompt-version]: glossary/prompt-version.md "Versioned prompt template with governance_tier. Pinned to entity versions; immutable after promotion."
[inference-config]: glossary/inference-config.md "Versioned LLM API parameter set: model, temperature, max_tokens, extended_params. Frozen on entity version promotion."
[tool-authorization]: glossary/tool-authorization.md "Per-agent-version row authorizing one tool. Unauthorized tool calls are rejected and Claude is informed."
[data-connector]: glossary/data-connector.md "Registered integration providing fetch/write methods used by source_bindings and write_targets. Vault is the canonical example."
[workflow-run-id]: glossary/workflow-run-id.md "Caller-supplied UUID threaded through every execute_* call in one workflow so the audit clusters correctly."
[execution-context]: glossary/execution-context.md "Business-level grouping registered by the consuming app; opaque to Verity. Scopes runs to a customer-facing operation (e.g. submission)."
[decision-log]: glossary/decision-log.md "One immutable row per AI invocation in agent_decision_log capturing prompts, config, I/O, tool calls, tokens, durations."
