# Verity Logging Architecture

## Problem

The platform has zero logging configuration. 130+ print() calls (seed scripts only), 3 files with inline `import logging` and no configuration, no structured logging, no correlation IDs, no log level control, silent exception swallowing throughout, stack traces lost when exceptions convert to result objects. Docker containers have no log rotation — unbounded growth.

## Design Principles

1. **Library-safe**: Verity is a pip-installable SDK. It must never call `logging.basicConfig()` or attach handlers to the root logger. Libraries get loggers, applications configure handlers.
2. **Async-native**: Use `contextvars.ContextVar` for correlation IDs — propagates automatically through `await` chains without argument threading.
3. **Dual format**: JSON for Docker/production (machine-parseable), console for development (human-readable). One env var switches.
4. **RCA-intuitive**: Every log line includes correlation_id, service, and contextual fields (submission_id, pipeline_run_id, step_name). When something fails, grep the correlation_id to see the full story across services.

---

## Logger Hierarchy

```
verity                          # Root — NullHandler for SDK safety
verity.core.execution           # LLM calls, tool calls, agent/task execution
verity.core.pipeline            # Pipeline orchestration, step management
verity.core.registry            # Config resolution
verity.core.decisions           # Decision log writes
verity.core.lifecycle           # Promotion state transitions
verity.db                       # Database operations, pool management

edms                            # EDMS root (independent of verity package)
edms.service                    # REST API routes
edms.core                       # Storage, text extraction

uw_demo                         # UW Demo root
uw_demo.pipeline                # Pipeline triggers, result processing
uw_demo.tools                   # Tool implementations
uw_demo.ui                      # UI routes
```

**Module-level loggers**: `logger = logging.getLogger(__name__)` at top of every file. No more inline `import logging` inside functions.

---

## Structured Log Format

**Library**: `python-json-logger` (v3.x) — wraps stdlib `logging.Formatter`, zero new concepts.

**Console format** (development):
```
2026-04-10T14:23:45.123Z INFO  verity.core.execution [abc123] run_agent agent=triage_agent sub=SUB-001 | Starting agent execution
```

**JSON format** (Docker/production):
```json
{"timestamp": "2026-04-10T14:23:45.123Z", "level": "INFO", "logger": "verity.core.execution", "message": "Starting agent execution", "correlation_id": "abc123", "service": "uw_demo", "agent_name": "triage_agent", "submission_id": "SUB-001", "pipeline_run_id": "...", "step_name": "triage_submission", "mock_mode": false}
```

### Mandatory fields (every log line)

| Field | Source | Purpose |
|---|---|---|
| `timestamp` | ISO 8601, UTC, milliseconds | Time ordering |
| `level` | DEBUG/INFO/WARNING/ERROR/CRITICAL | Severity |
| `logger` | Python logger name | Component ID |
| `message` | Log message | Human description |
| `service` | Set at startup | Which container |
| `correlation_id` | ContextVar, auto-propagated | Request tracing |

### Contextual fields (attached via ContextVar + logging Filter)

| Field | When present | Purpose |
|---|---|---|
| `pipeline_run_id` | During pipeline execution | Groups all steps |
| `step_name` | During step execution | Which pipeline step |
| `entity_name` | During agent/task execution | Which entity |
| `entity_type` | During execution | agent, task, tool |
| `submission_id` | During UW operations | Business context |
| `duration_ms` | On completion events | Performance |
| `input_tokens` | After LLM call | Cost tracking |
| `output_tokens` | After LLM call | Cost tracking |
| `mock_mode` | During execution | Mock vs live |

---

## Correlation IDs

**Mechanism**: `contextvars.ContextVar` — async-safe, auto-propagates through `await` chains.

**HTTP flow** (API mode):
1. FastAPI middleware generates `correlation_id = uuid4().hex[:12]`
2. Checks `X-Correlation-ID` header first (inter-service calls)
3. Sets `correlation_id_var`
4. All downstream loggers include it via `ContextFilter`
5. Response includes `X-Correlation-ID` header

**SDK mode** (no HTTP):
1. `pipeline_executor.run_pipeline()` generates correlation_id if none set
2. Sets `pipeline_run_id_var`, updates `step_name_var` per step
3. Consuming app can set correlation_id before calling Verity

**Inter-service propagation**:
UW Demo's httpx calls to EDMS include `X-Correlation-ID` header. EDMS middleware picks it up. Unified trace across services, zero infrastructure.

---

## Log Targets

### Target 1: Console (stdout)
```python
"console": {
    "class": "logging.StreamHandler",
    "stream": "ext://sys.stdout",
    "formatter": "json",  # or "console" in dev
    "filters": ["context"],
}
```

### Target 2: Rotating file
```python
"file": {
    "class": "logging.handlers.RotatingFileHandler",
    "filename": "./logs/{service}.log",
    "maxBytes": 50_000_000,   # 50 MB
    "backupCount": 5,         # 250 MB max per service
    "formatter": "json",
    "filters": ["context"],
}
```

### Target 3: Database (future)
Not in v1. The `agent_decision_log` table already captures execution failures. A dedicated `system_log` table only makes sense when querying operational logs becomes a requirement.

### Configuration
Environment variables (no config files):
```
LOG_LEVEL=INFO              # Default log level
LOG_FORMAT=json             # "json" or "console"
LOG_FILE_ENABLED=false      # Whether to write rotating files
LOG_DIR=./logs              # Relative to app working directory (each app has its own)
```

---

## Log Levels Strategy

| Level | What gets logged | When to use |
|---|---|---|
| DEBUG | Full payloads, SQL params, internal state | Development only — never in production |
| INFO | Business events, lifecycle transitions | Every pipeline start/complete, tool call, decision logged |
| WARNING | Degraded operation, retries, handled errors | API retries, missing data, skipped steps |
| ERROR | Failed operations that affect results | Pipeline failures, tool errors, DB connection lost |
| CRITICAL | Cannot serve requests | Pool exhausted, API key missing, service won't start |

**Runtime level changes**: Read from `app_settings` table (`key='log_level'`). Change in DB, next request picks it up. Also available via admin API endpoint `POST /admin/api/log-level`.

---

## Error Handling Standards

### Rule 1: Never silent swallow
```python
# BAD
except Exception:
    pass

# GOOD
except Exception:
    logger.warning("Could not load config for %s", name, exc_info=True)
```

### Rule 2: Log before converting exceptions to results
```python
# BAD — stack trace lost
except Exception as e:
    return ExecutionResult(error_message=str(e))

# GOOD — traceback preserved in logs, summary in result
except Exception as e:
    logger.error("Agent execution failed: %s", agent_name, exc_info=True)
    return ExecutionResult(error_message=str(e))
```

### Rule 3: `exc_info=True` for every caught exception worth diagnosing
The stack trace goes to logs. The summary `str(e)` goes to API responses and result objects.

### Rule 4: Log at the handling boundary
Log where you HANDLE the error, not where you re-raise it.

---

## Lifecycle Management

**File rotation**: `RotatingFileHandler` — 50 MB per file, 5 backups, 250 MB max per service.

**Docker log limits** (add to each service in docker-compose.yml):
```yaml
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "3"
```

**Log volume** (persistent across container restarts):
```yaml
volumes:
  - app_logs:./logs
```

---

## Specific Log Points

### Execution Engine (verity.core.execution)
```
INFO   Agent/task execution starting     | entity_name, mock_mode, pipeline_run_id
INFO   LLM call starting                 | model, max_tokens, has_tools
WARN   LLM call retry                    | attempt, status_code, delay_seconds
ERROR  LLM call failed (final)           | status_code, attempts, error_message
INFO   LLM call complete                 | input_tokens, output_tokens, duration_ms
INFO   Tool call starting                | tool_name, mock_mode
INFO   Tool call complete                | tool_name, duration_ms, has_error
ERROR  Tool execution failed             | tool_name, error (exc_info=True)
INFO   Execution complete                | entity_name, status, duration_ms, token_total
```

### Pipeline Executor (verity.core.pipeline)
```
INFO   Pipeline run starting             | pipeline_name, run_id, step_count, mock_mode
INFO   Step starting                     | step_name, entity_type, entity_name
INFO   Step complete                     | step_name, status, duration_ms
ERROR  Step failed                       | step_name, error_message
INFO   Pipeline run complete             | pipeline_name, run_id, status, duration_ms
```

### UW Demo Routes (uw_demo.pipeline)
```
INFO   Document processing triggered     | submission_id, document_count
INFO   EDMS documents fetched            | submission_id, doc_count
INFO   Extraction results stored         | submission_id, fields_stored, fields_flagged
INFO   HITL review triggered             | submission_id, review_count
INFO   HITL approval processed           | submission_id, overrides_count
INFO   Risk assessment triggered         | submission_id
INFO   Assessment results stored         | submission_id, risk_score, determination
ERROR  Pipeline execution failed         | submission_id, error (exc_info=True)
```

### EDMS (edms.service)
```
INFO   Document uploaded                 | document_id, filename, size_bytes
INFO   Text extracted                    | document_id, char_count
INFO   Document type updated             | document_id, document_type
ERROR  Storage read failed               | document_id, error (exc_info=True)
```

---

## Implementation

### New files
| File | Purpose |
|---|---|
| `verity/src/verity/logging.py` | ContextFilter, ContextVars, setup_logging(), build_logging_config() |
| `edms/src/edms/logging.py` | Minimal copy for EDMS independence (same pattern, no verity import) |

### Files modified
| File | Change |
|---|---|
| `verity/src/verity/__init__.py` | Add `NullHandler` for SDK safety |
| `verity/src/verity/core/execution.py` | Module-level logger, instrument all gateways, fix exception handling |
| `verity/src/verity/core/pipeline_executor.py` | Add pipeline/step lifecycle logging, set context vars |
| `verity/src/verity/main.py` | Call `setup_logging()`, add `CorrelationMiddleware` |
| `uw_demo/app/main.py` | Call `setup_logging()`, add `CorrelationMiddleware` |
| `uw_demo/app/ui/routes.py` | Module-level logger, fix silent swallows, add pipeline event logging |
| `edms/src/edms/service/main.py` | Call `setup_logging()`, add `CorrelationMiddleware` |
| `docker-compose.yml` | Add log rotation limits, log volume, LOG_LEVEL env vars |
| `verity/pyproject.toml` | Add `python-json-logger>=3.0` dependency |
| `requirements.txt` | Add `python-json-logger>=3.0` dependency |

### Implementation phases

**Phase 1 — Foundation**: Create logging module, NullHandler, setup_logging(), CorrelationMiddleware, Docker log limits. All three services get configured logging. (~1 hour)

**Phase 2 — Critical instrumentation**: Instrument execution.py and pipeline_executor.py. Fix all silent exception swallows. These two files handle every AI call and every pipeline step. (~1 hour)

**Phase 3 — Comprehensive coverage**: Instrument routes, tools, EDMS, database layer. Add correlation ID propagation in inter-service httpx calls. (~1 hour)

**Phase 4 — Polish**: Runtime log level endpoint, rotating file handler with volume mount, documentation. (~30 min)
