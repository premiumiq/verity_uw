# Verity Data Science Workbench

Interactive JupyterLab environment for exercising every Verity capability
over its `/api/v1/*` REST API. The workbench registers itself as the
`ds_workbench` application in Verity, so every run you make from these
notebooks is cleanly attributed and can be purged via the cleanup notebook.

## Running from Docker (canonical)

```bash
# From the repo root:
docker compose up -d ds-workbench

# Open JupyterLab in a browser:
#   http://localhost:8888?token=dev
```

Inside the container, notebooks reach Verity at `http://verity:8000`
(set via the `VERITY_API_URL` env var). The `./ds_workbench` tree is
bind-mounted into `/home/jovyan/work`, so any edits you make in VSCode
on your host show up immediately in the container (and vice versa).

To restart just the workbench without touching Verity or Postgres:

```bash
docker compose restart ds-workbench
```

## Running from VSCode (secondary)

Open the repo in VSCode with the Jupyter and Python extensions.
Create a local virtualenv and install the workbench deps:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r ds_workbench/requirements.txt
export VERITY_API_URL=http://localhost:8000
```

Then open any `.ipynb` under `ds_workbench/notebooks/` and pick the
`.venv` kernel.

## Typical flow

1. **`00_setup.ipynb`** — checks Verity is reachable, registers the
   `ds_workbench` application if needed, and seeds a handful of
   sample execution contexts.
2. Pick a capability notebook under `notebooks/<component>/`.
   Each notebook is structured as:
   - *What this demonstrates* — markdown explainer of the Verity
     capability.
   - *Prerequisites* — what must already exist; minimal setup calls
     if missing.
   - *Execute* — the capability invocation.
   - *Review results* — pull artifacts via the API and render with
     the visualizations helper (tables, charts, flow diagrams).
3. **`99_cleanup.ipynb`** — show activity counts, confirm, purge
   decisions / overrides / execution_contexts, unregister the app.

## Layout

```
ds_workbench/
├── Dockerfile
├── README.md                     (this file)
├── requirements.txt
├── utility/
│   ├── verity.py                 HTTP client + endpoint registry
│   └── visualizations.py         Reusable viz helpers
├── 00_setup.ipynb
├── 99_cleanup.ipynb
└── notebooks/
    ├── registry/                 List catalog, resolve by date, map entities.
    ├── authoring/                Register + clone + edit drafts + promote.
    ├── lifecycle/                Promote / rollback.
    ├── runtime/                  Run agent / task / pipeline.
    ├── compliance/               Decision log walkthrough, audit trail.
    ├── testing/                  Test suites.
    ├── validation/               Ground-truth validation.
    ├── mcp/                      MCP server + tool registration.
    └── delegation/               Sub-agent delegation graph.
```

## Environment variables

| Variable          | Default                | Purpose |
|-------------------|------------------------|---------|
| `VERITY_API_URL`  | `http://localhost:8000`| Where `utility/verity.py` sends requests. Compose sets it to `http://verity:8000` inside the container. |
| `JUPYTER_TOKEN`   | `dev`                  | JupyterLab auth token — local-dev convenience only. |
