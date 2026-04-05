# Web UI Validation Guide

This guide walks you through starting the Verity web UI and verifying it works.

---

## Prerequisites

Before starting, make sure:
1. PostgreSQL is running: `docker compose ps` should show `verity_postgres` as healthy
2. Verity schema is applied (you did this in initial setup)
3. Python venv is active: `source .venv/bin/activate`

---

## Step 1: Start the Application

```bash
cd ~/verity_uw
source .venv/bin/activate
uvicorn uw_demo.app.main:app --port 8000 --reload
```

**What this does:**
- Starts a local web server on port 8000
- `--reload` means it auto-restarts when you edit Python files (useful during development)
- The terminal will show `Uvicorn running on http://127.0.0.1:8000`
- Leave this terminal running — it's your server

**You may see a warning** about `psycopg_pool` — this is cosmetic, not an error. Ignore it.

### If port 8000 is already in use

This means a previous server is still running. Find and stop it:

```bash
# Find what's using port 8000
lsof -i :8000

# Kill it by PID (replace 12345 with the actual PID from above)
kill 12345

# Or kill all uvicorn processes
pkill -f "uvicorn uw_demo"

# Wait a moment, then start again
sleep 2
uvicorn uw_demo.app.main:app --port 8000 --reload
```

---

## Step 2: Open in Browser

### If you're on Windows (accessing WSL)

Open your Windows browser and go to:

```
http://localhost:8000/verity/admin/
```

This works because WSL2 forwards ports to Windows automatically.

### What you should see

1. **Left sidebar** — Dark grey (#4D4D4D) with "PremiumIQ / Verity" branding
2. **Navigation links** — Dashboard, Agents, Tasks, Prompts, etc. in the sidebar
3. **Breadcrumbs** — "Verity" at top left of the content area
4. **Dashboard title** — "Dashboard" as the page heading
5. **Eight stat cards** — All showing "0" (no seed data yet)
6. **Empty recent decisions table** — "No decisions logged yet" message
7. **Poppins font** — Clean, modern text throughout

---

## Step 3: Click Through Every Page

Click each link in the sidebar and verify it loads without errors:

| Sidebar Link | URL | What You Should See |
|---|---|---|
| Dashboard | `/verity/admin/` | Stat cards (all zeros) + empty decisions table |
| Agents | `/verity/admin/agents` | Empty table with "No agents registered yet" |
| Tasks | `/verity/admin/tasks` | Empty table with "No tasks registered yet" |
| Prompts | `/verity/admin/prompts` | Empty table |
| Inference Configs | `/verity/admin/configs` | Empty table |
| Tools | `/verity/admin/tools` | Empty table |
| Pipelines | `/verity/admin/pipelines` | Empty with "No pipelines registered yet" |
| Decision Log | `/verity/admin/decisions` | "0 total decisions logged" + empty table |
| Model Inventory | `/verity/admin/model-inventory` | Empty agents and tasks sections |
| Lifecycle | `/verity/admin/lifecycle` | Placeholder (shows agents list) |
| Test Results | `/verity/admin/test-results` | Placeholder (shows dashboard) |

**Every page should:**
- Load without errors (no "Internal Server Error")
- Show the sidebar with the correct link highlighted (blue left border)
- Show breadcrumbs at top
- Display Poppins font (check by inspecting any text element in browser DevTools)

---

## Step 4: Verify the CSS is Loading

The custom stylesheet (`verity.css`) provides the PremiumIQ color palette.

Open this URL directly in your browser:
```
http://localhost:8000/verity/admin/static/verity.css
```

You should see the raw CSS file with color variables like `--verity-blue: #8FAADC`.

**If the pages look unstyled (plain HTML, no colors):**
The CSS isn't loading. Check the browser's Developer Tools (F12 → Console tab) for 404 errors on the CSS file.

---

## Step 5: Verify Using curl (Optional — Command Line Check)

If you want to verify without a browser, open a **second terminal** (keep the server running in the first):

```bash
# Health check
curl -s http://localhost:8000/health
# Expected: {"status":"healthy","app":"uw_demo","env":"demo"}

# Dashboard page — check it returns HTML with correct title
curl -s http://localhost:8000/verity/admin/ | grep '<title>'
# Expected: <title>Dashboard — Verity Admin</title>

# Check all pages return HTTP 200
for page in "" "agents" "tasks" "prompts" "configs" "tools" "pipelines" "decisions" "model-inventory"; do
    status=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/verity/admin/$page")
    echo "$page: HTTP $status"
done
# Expected: every line shows HTTP 200
```

---

## Step 6: Check the Look and Feel

### What to look for visually:

**Sidebar (left side):**
- Background: dark blue (#405A8A)
- Text: white
- Active page has a blue left border highlight
- "PremiumIQ" in bold at top, "Verity Governance" below in smaller text
- "Verity v0.1.0" at the bottom

**Content area (right side):**
- White background
- Breadcrumbs in light grey text at top
- Page title in dark grey below breadcrumbs
- Stat cards with light borders and blue accent numbers
- Tables with grey header text, alternating row shading, hover highlights

**Typography:**
- All text should be Poppins (Google Font, loaded via CDN)
- If Poppins doesn't load (no internet), it falls back to system sans-serif — still looks fine

**Colors to verify:**
- Primary text: dark grey (#4D4D4D), not black
- Accent numbers in cards: deep blue (#2B4D8A)
- Borders: light grey (#DBDBDB)
- No bright colors visible yet (RAG colors only appear on status badges, which need seed data)

---

## Stopping the Server

Press `Ctrl+C` in the terminal where uvicorn is running.

Or from another terminal:
```bash
pkill -f "uvicorn uw_demo"
```

---

## Troubleshooting

### "Internal Server Error" on a page

Check the terminal where uvicorn is running — it will show the Python traceback. The most likely cause is a template syntax error in one of the HTML files.

### Pages are blank / unstyled

1. Check that `verity.css` loads: `curl http://localhost:8000/verity/admin/static/verity.css`
2. Check browser DevTools (F12) → Console for errors
3. Check browser DevTools → Network tab — are CSS/font requests failing?

### "Address already in use" on port 8000

```bash
# Find the PID using port 8000
lsof -i :8000
# Kill it
kill <PID>
```

### Database connection errors

Make sure PostgreSQL is running:
```bash
docker compose ps
# Should show verity_postgres as healthy
```

### Pages show data but it's all zeros

That's correct! The database has no seed data yet. Phase 4 (seed data) will populate agents, tasks, prompts, and demo decisions so the pages have content.
