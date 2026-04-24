"""Verity worker — claims and dispatches async runs.

Stateless process that loops on:
  1. Claim the next available execution_run (FOR UPDATE SKIP LOCKED +
     INSERT 'claimed' status row, atomic).
  2. Dispatch via the existing engine (run_task / run_agent).
  3. Write a terminal completion or error row.
  4. Cancel the heartbeat task and pick up the next run.

Workers are horizontally scalable — `docker compose up --scale
verity-worker=N` runs N processes against the same DB; SKIP LOCKED
guarantees no two workers claim the same row.

Bootstrap (single-app demo): the worker imports uw_demo's EdmsProvider
and registers it under the connector name "edms". As more apps come
online this'll evolve into a pluggable connector-bootstrap mechanism
driven by the data_connector table; for now, hardcoding the UW
demo's wiring keeps things simple.

Known limitations (Phase C demo scope):
  - Mid-run cancel is not honored. cancel_run before claim works (the
    claim predicate skips runs with terminal rows). cancel_run mid-run
    inserts a completion row, but the worker doesn't poll for it
    between LLM calls. Apps that need mid-run cancel today should
    submit the run with a short timeout instead.
  - Graceful shutdown isn't implemented; SIGTERM kills any in-flight
    runs. They'll be reclaimed by the janitor query (which reads
    stuck claimed rows older than the threshold).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
import time
import traceback
from typing import Any, Optional
from uuid import UUID

from verity.client.inprocess import Verity
from verity.contracts.mock import MockContext

logger = logging.getLogger("verity.worker")


# How often to insert a 'heartbeat' status row while a run is in flight.
# Must be much shorter than the janitor's stuck-run threshold so the
# janitor only re-claims actually-dead workers, not active ones.
HEARTBEAT_INTERVAL_SECONDS = 30.0

# How long to sleep between claim attempts when the queue is empty.
# Short enough that a freshly-submitted run is picked up promptly;
# long enough that an idle worker doesn't hammer the DB.
EMPTY_QUEUE_SLEEP_SECONDS = 1.0

# How long the janitor waits before re-queuing a run whose latest
# claimed/heartbeat is older than this. Worker heartbeats every 30s,
# so 5 minutes is comfortably long enough to cover transient hiccups.
JANITOR_STUCK_THRESHOLD = "5 minutes"

# How often the janitor scans for stuck runs.
JANITOR_INTERVAL_SECONDS = 60.0


def _build_worker_id() -> str:
    """Distinct id per worker process — host + pid.

    Recorded on every status / completion / error row so operators can
    correlate worker logs back to the runs they touched.
    """
    return f"{socket.gethostname()}-{os.getpid()}"


def _bootstrap_connectors(verity: Verity) -> None:
    """Register the consuming app's connector providers.

    Single-app demo bootstrap: imports the UW demo's EdmsProvider and
    registers it under the connector name 'edms'. Will become
    pluggable when multi-app support arrives.
    """
    try:
        from verity.runtime.connectors import register_provider
        from uw_demo.app.edms_provider import EdmsProvider
    except ImportError as e:
        logger.warning(
            "Could not import EdmsProvider — task source resolution "
            "for connector 'edms' will fail. (%s)",
            e,
        )
        return

    edms_url = os.environ.get("EDMS_URL", "http://edms:8002")
    register_provider("edms", EdmsProvider(base_url=edms_url))
    logger.info("Registered connector provider: edms (base_url=%s)", edms_url)


async def _heartbeat_loop(
    verity: Verity, run_id: UUID, worker_id: str, stop: asyncio.Event,
) -> None:
    """Periodic heartbeat for a run currently being dispatched.

    Inserts a 'heartbeat' row every HEARTBEAT_INTERVAL_SECONDS until
    stop.is_set(). Failures are logged but never raise — a missed
    heartbeat shouldn't kill the run.
    """
    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)
                return  # stop was set during the wait
            except asyncio.TimeoutError:
                pass  # heartbeat tick
            try:
                await verity.runs_writer.heartbeat(run_id, worker_id)
            except Exception:
                logger.warning("heartbeat write failed for run %s", run_id, exc_info=True)
    except asyncio.CancelledError:
        return


async def _dispatch_run(verity: Verity, run: dict[str, Any], worker_id: str) -> None:
    """Execute one claimed run end-to-end and write its terminal row.

    Engine errors come back as ExecutionResult(status='failed') (the
    engine catches its own exceptions). True unhandled exceptions
    (worker-level bugs, DB outages mid-dispatch) propagate up here
    and become an error row.
    """
    run_id = run["id"]
    if isinstance(run_id, str):
        run_id = UUID(run_id)

    started = time.monotonic()
    stop_heartbeat = asyncio.Event()
    hb_task = asyncio.create_task(
        _heartbeat_loop(verity, run_id, worker_id, stop_heartbeat),
    )

    try:
        # Build the optional MockContext when the run was submitted in
        # mock mode. Phase C uses the simplest interpretation: all
        # registered tools fall back to their DB-stored mock_responses.
        mock_ctx: Optional[MockContext] = None
        if run.get("mock_mode"):
            mock_ctx = MockContext(mock_all_tools=True)

        input_data = run.get("input_json") or {}
        entity_kind = run["entity_kind"]
        entity_name = run["entity_name"]
        channel = run["channel"]
        workflow_run_id = _maybe_uuid(run.get("workflow_run_id"))
        parent_decision_id = _maybe_uuid(run.get("parent_decision_id"))
        execution_context_id = _maybe_uuid(run.get("execution_context_id"))
        application = run.get("application")

        logger.info(
            "dispatch run=%s kind=%s name=%s channel=%s app=%s",
            run_id, entity_kind, entity_name, channel, application,
        )

        # write_mode and enforce_output_schema flow through from the
        # submission row when the caller pinned them. Engine defaults
        # apply otherwise. enforce_output_schema is agent-only.
        write_mode = run.get("write_mode") or "auto"
        enforce_output_schema = bool(run.get("enforce_output_schema"))

        if entity_kind == "task":
            result = await verity.execution.run_task(
                task_name=entity_name,
                input_data=input_data,
                channel=channel,
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                execution_context_id=execution_context_id,
                application=application,
                mock=mock_ctx,
                write_mode=write_mode,
                execution_run_id=run_id,
            )
        elif entity_kind == "agent":
            result = await verity.execution.run_agent(
                agent_name=entity_name,
                context=input_data,
                channel=channel,
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                execution_context_id=execution_context_id,
                application=application,
                mock=mock_ctx,
                write_mode=write_mode,
                enforce_output_schema=enforce_output_schema,
                execution_run_id=run_id,
            )
        else:
            raise ValueError(f"Unknown entity_kind: {entity_kind!r}")

        duration_ms = int((time.monotonic() - started) * 1000)
        if result.status == "complete":
            await verity.runs_writer.complete(
                run_id,
                decision_log_id=result.decision_log_id,
                duration_ms=duration_ms,
                worker_id=worker_id,
                final_status="complete",
            )
            logger.info("complete run=%s decision_log_id=%s duration_ms=%d",
                        run_id, result.decision_log_id, duration_ms)
        else:
            # The engine returned a failure envelope (it caught its own
            # exception and logged a decision row with status='failed').
            # Mirror that on the run-tracking side as an error row.
            await verity.runs_writer.error(
                run_id,
                error_code=result.status,
                error_message=result.error_message or "engine returned failure",
                error_trace=None,
                worker_id=worker_id,
                decision_log_id=result.decision_log_id,
            )
            logger.warning(
                "engine failure run=%s status=%s msg=%s",
                run_id, result.status, result.error_message,
            )

    except Exception as exc:
        # Worker-level failure (DB outage mid-write, bad input shape,
        # unimplemented entity_kind, etc.). The engine never saw the
        # call or saw it but couldn't unwind. Record as an error row;
        # there's no decision_log_id to link.
        logger.exception("worker dispatch failed run=%s", run_id)
        try:
            await verity.runs_writer.error(
                run_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
                error_trace=traceback.format_exc(),
                worker_id=worker_id,
            )
        except Exception:
            # If even the error-row write fails, the janitor will
            # eventually re-queue the run from its stuck-heartbeat
            # state; better to leak the run than to crash the worker.
            logger.exception("failed to record error row for run=%s", run_id)
    finally:
        stop_heartbeat.set()
        hb_task.cancel()
        try:
            await hb_task
        except (asyncio.CancelledError, Exception):
            pass


def _maybe_uuid(value: Any) -> Optional[UUID]:
    """Coerce DB-returned value (string or UUID) to UUID, preserve None."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


async def _janitor_loop(verity: Verity, worker_id: str, stop: asyncio.Event) -> None:
    """Periodically reclaim runs whose claimed/heartbeat is too old.

    Runs in every worker (cheap, idempotent — concurrent janitors
    insert duplicate 'released' rows but that doesn't break anything,
    and the predicate excludes runs that already have a recent
    'released'). One worker per cluster is enough; sharing the
    responsibility means no single point of failure.
    """
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=JANITOR_INTERVAL_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        try:
            rows = await verity.db.fetch_all(
                "janitor_reclaim_stuck_runs",
                {
                    "janitor_id": f"{worker_id}-janitor",
                    "stuck_threshold": JANITOR_STUCK_THRESHOLD,
                },
            )
            if rows:
                logger.warning(
                    "janitor released %d stuck run(s): %s",
                    len(rows),
                    [r["execution_run_id"] for r in rows],
                )
        except Exception:
            logger.exception("janitor sweep failed")


async def main_async() -> None:
    """Worker entrypoint — claim loop + janitor + heartbeat machinery."""
    db_url = os.environ.get("VERITY_DB_URL")
    if not db_url:
        print("ERROR: VERITY_DB_URL not set in environment.", file=sys.stderr)
        sys.exit(2)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    application = os.environ.get("VERITY_WORKER_APPLICATION", "verity_worker")

    verity = Verity(database_url=db_url, anthropic_api_key=api_key, application=application)
    await verity.connect()
    _bootstrap_connectors(verity)

    worker_id = _build_worker_id()
    logger.info("worker started id=%s", worker_id)

    stop = asyncio.Event()

    def _on_signal(*_):
        logger.info("worker received shutdown signal; finishing in-flight work")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # add_signal_handler is unavailable on Windows or under
            # some uvicorn-style supervised setups; fall back to
            # synchronous signal.signal which is good enough for SIGTERM.
            signal.signal(sig, lambda *_: _on_signal())

    janitor = asyncio.create_task(_janitor_loop(verity, worker_id, stop))

    try:
        while not stop.is_set():
            try:
                run = await verity.runs_writer.claim_next(worker_id=worker_id)
            except Exception:
                logger.exception("claim_next failed; backing off")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=EMPTY_QUEUE_SLEEP_SECONDS)
                except asyncio.TimeoutError:
                    pass
                continue
            if not run:
                # No work available — wait a bit, then retry. Wakeable
                # by the stop event so SIGTERM doesn't have to wait
                # the full interval.
                try:
                    await asyncio.wait_for(
                        stop.wait(), timeout=EMPTY_QUEUE_SLEEP_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass
                continue
            await _dispatch_run(verity, run, worker_id)
    finally:
        stop.set()
        janitor.cancel()
        try:
            await janitor
        except (asyncio.CancelledError, Exception):
            pass
        await verity.close()
    logger.info("worker stopped id=%s", worker_id)


def main() -> None:
    """CLI entrypoint — `python -m verity.runtime.worker`."""
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
