# Running the Applications

Verity and the UW Demo are two separate applications on separate ports.

## Start Both Apps

Open **two terminals**.

**Terminal 1 — Verity (port 8000):**
```bash
cd ~/verity_uw
source .venv/bin/activate
uvicorn verity.main:app --port 8000 --reload
```

**Terminal 2 — UW Demo (port 8001):**
```bash
cd ~/verity_uw
source .venv/bin/activate
uvicorn uw_demo.app.main:app --port 8001 --reload
```

## Access the Apps

| App | URL | What It Is |
|---|---|---|
| Verity | http://localhost:8000 | AI governance platform (agents, decisions, model inventory) |
| UW Demo | http://localhost:8001 | Underwriting business app (submissions, pipeline, AI results) |

## How They Connect

- Both apps connect to the same `verity_db` database through the Verity Python SDK
- The UW app imports `from verity import Verity` — direct Python calls, not HTTP
- "View in Verity" links in the UW app open `http://localhost:8000/admin/...`
- "UW Demo →" link in the Verity sidebar opens `http://localhost:8001/`

## Stopping

Press `Ctrl+C` in each terminal. Or:
```bash
pkill -f "uvicorn verity.main"
pkill -f "uvicorn uw_demo"
```
