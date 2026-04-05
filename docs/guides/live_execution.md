# Live Claude Execution Guide

This guide explains how to run the AI pipeline with real Claude API calls.

## Prerequisites

1. PostgreSQL running (`docker compose ps` shows `verity_postgres` healthy)
2. Seed data loaded (`python -m uw_demo.app.setup.register_all` ran successfully)
3. `.env` file in project root has your Anthropic API key:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
   ```

## Start the App

```bash
cd ~/verity_uw
source .venv/bin/activate
uvicorn uw_demo.app.main:app --port 8000 --reload
```

## Run a Live Pipeline

1. Open http://localhost:8000/uw/
2. Click any submission (e.g., Acme Dynamics D&O)
3. Click **"Run Pipeline"**
4. On the pipeline page, click **"Run Pipeline (Live — calls Claude)"**
5. Wait ~30-60 seconds (Claude processes 4 steps: classify, extract, triage, appetite)
6. See the step-by-step results with real AI reasoning

## What Happens During Live Execution

For each pipeline step, the execution engine:

1. **Resolves config from Verity** — prompts, tools, inference params (temperature, model)
2. **Assembles the prompt** — system prompt + user context with variable substitution
3. **Calls Claude API** — real API call using the governed inference config
4. **Claude calls tools** — agents request tool data (submission context, guidelines, etc.)
5. **Tools return real data** — hardcoded realistic data for the demo submissions
6. **Claude reasons and produces output** — risk score, appetite determination, etc.
7. **Decision logged in Verity** — with full inference_config_snapshot, tool calls, output
8. **Next step runs** — previous step's output feeds into the next step's context

## Mock vs Live Comparison

| Aspect | Mock Mode | Live Mode |
|---|---|---|
| Claude API called | No | Yes |
| Cost per run | Free | ~$0.03-0.05 |
| Time per run | Instant | 30-60 seconds |
| AI output | Pre-built (same every time) | Real Claude reasoning (varies) |
| Tool calls | Mocked (from pre-built data) | Real (returns hardcoded demo data) |
| Decision logged | Yes (identical governance trail) | Yes (identical governance trail) |
| Tokens recorded | 0 / 0 | Real input/output token counts |

## Viewing Results in Verity Admin

After a live run:

1. Click **"View Audit Trail in Verity"** on the pipeline results page
2. Or go to http://localhost:8000/verity/admin/decisions — the new decisions appear at the top
3. Click any decision to see:
   - The exact inference config snapshot (temperature, model, max_tokens)
   - The tool calls Claude made and what each tool returned
   - The full AI output (risk score, reasoning, citations)
   - Input/output token counts and duration

## Troubleshooting

### "No Anthropic API key configured"
Check that `.env` exists in the project root and contains `ANTHROPIC_API_KEY=sk-ant-...`

### Pipeline takes very long (> 2 minutes)
The triage agent makes multiple tool calls (get_submission_context, get_guidelines, get_enrichment, get_loss_history, store_result). Each tool call → Claude processes → next call. This is normal for multi-turn agents.

### "tools.0.custom.input_schema: JSON schema is invalid"
The task's output_schema has informal types (e.g., `"confidence": "number"` instead of `"confidence": {"type": "number"}`). The execution engine detects this and falls back to plain text output. If you want structured output (tool_choice), update the output_schema in the seed data to use proper JSON Schema format.
