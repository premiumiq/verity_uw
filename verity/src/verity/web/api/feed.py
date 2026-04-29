"""Verity Compliance Feed (Rung 1) — incremental data pull endpoint.

Architecture: docs/architecture/compliance-stack.md (Incremental Feed Rung 1).

Contract:
    GET /api/v1/feed/{view_name}
        ?since=<ISO timestamp OR opaque cursor>
        &until=<ISO timestamp; optional, defaults to now>
        &limit=<int 1..5000; default 1000>
        &format=jsonl

    Returns:
        {
          "view":       str,
          "since":      ISO timestamp at start of pulled batch,
          "until":      ISO timestamp at upper bound of window,
          "row_count":  int,
          "complete":   bool   — true when row_count < limit
                                (window drained as far as data exists),
          "next_since": opaque cursor or null,
          "rows":       [...]
        }

Rules:
  - Always sorted ascending by (ingest_ts, source_pk).
  - Closed window: rows where (ingest_ts, source_pk) > since AND ingest_ts < until.
  - Caller iterates with `since = next_since` until `complete = true`.
  - Cursor is opaque — encoded keyset (ingest_ts, source_pk).

Allowlist:
  - Only views registered in verity_analytics.feed_view are serveable.
  - View name validated server-side before any SQL is built;
    the view name is parameterized into a quoted SQL identifier.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg import sql as psycopg_sql

# Defaults / limits
DEFAULT_LIMIT = 1000
MAX_LIMIT     = 5000


# =============================================================================
# Cursor codec — encodes (ingest_ts, source_pk) as an opaque base64 string
# =============================================================================

def encode_cursor(ts: datetime, pk: str) -> str:
    """Pack a keyset cursor into an opaque base64 string."""
    payload = json.dumps(
        {"ts": ts.isoformat(), "pk": pk}, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def decode_cursor(s: str) -> tuple[datetime, str]:
    """Reverse of encode_cursor. Raises ValueError on bad input."""
    pad = "=" * (-len(s) % 4)
    raw = base64.urlsafe_b64decode(s + pad)
    obj = json.loads(raw.decode("utf-8"))
    return _parse_iso(obj["ts"]), str(obj["pk"])


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp; tolerate trailing 'Z' for UTC.

    Returns a *naive* datetime in UTC — verity_analytics views expose
    `timestamp without time zone` columns, so we keep the API side naive
    too to avoid Python tz-aware/naive comparison errors.
    """
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_since(since: str) -> tuple[datetime, str]:
    """Try to interpret `since` as either an ISO timestamp (first call) or
    an opaque cursor (subsequent calls).

    Heuristic: ISO-8601 timestamps always contain ':'. URL-safe base64
    cursors never do (the alphabet is A-Z, a-z, 0-9, '-', '_', '=').
    """
    if ":" in since:
        # Looks like ISO timestamp; pk='' is the lexicographic floor.
        try:
            return _parse_iso(since), ""
        except Exception as e:
            raise ValueError(
                f"`since` looks like an ISO timestamp but is unparseable: {e}"
            ) from e
    # Otherwise treat as opaque cursor.
    try:
        return decode_cursor(since)
    except Exception as e:
        raise ValueError(
            f"`since` is neither an ISO-8601 timestamp nor a valid cursor: {e}"
        ) from e


# =============================================================================
# Router
# =============================================================================

def build_feed_router(verity) -> APIRouter:
    router = APIRouter(prefix="/feed", tags=["feed"])

    async def _allowlisted(view_name: str) -> dict:
        row = await verity.db.fetch_one("get_active_feed_view", {"view_name": view_name})
        if not row:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"View {view_name!r} is not in the feed allowlist. "
                    f"Active views: GET /api/v1/feed (no view_name)."
                ),
            )
        return row

    @router.get("")
    async def list_views():
        """List the views available through this feed."""
        await verity.ensure_connected()
        rows = await verity.db.fetch_all("list_active_feed_views")
        return {"views": rows}

    @router.get("/{view_name}")
    async def feed_view(
        view_name: str,
        since:  Optional[str] = Query(None,  description="ISO timestamp or opaque cursor (REQUIRED)"),
        until:  Optional[str] = Query(None,  description="ISO timestamp; defaults to now"),
        limit:  int           = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        format: str           = Query("jsonl", regex="^(jsonl|json)$"),
    ):
        await verity.ensure_connected()
        await _allowlisted(view_name)  # raises 404 if not in allowlist

        if not since:
            raise HTTPException(
                status_code=400,
                detail="`since` is required (ISO timestamp or opaque cursor).",
            )

        # Decode since.
        try:
            since_ts, since_pk = _parse_since(since)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Decode until (default to now). Keep naive UTC to match the
        # views' timestamp-without-tz columns.
        if until:
            try:
                until_ts = _parse_iso(until)
            except Exception as e:
                raise HTTPException(
                    status_code=400, detail=f"`until` must be ISO-8601: {e}"
                )
        else:
            until_ts = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        if until_ts <= since_ts:
            raise HTTPException(
                status_code=400,
                detail=f"`until` ({until_ts.isoformat()}) must be > `since` "
                       f"({since_ts.isoformat()}).",
            )

        # Build SQL with the view name as a *safely quoted identifier*.
        # The keyset predicate (ingest_ts, source_pk) > (:since_ts, :since_pk)
        # is what makes pagination loss-free across rows that share an
        # ingest_ts. View name has been validated against the active
        # feed_view allowlist above.
        view_id = psycopg_sql.Identifier("verity_analytics", view_name)
        query = psycopg_sql.SQL(
            """
            SELECT *
            FROM {view}
            WHERE (ingest_ts, COALESCE(source_pk, '')) > (%(since_ts)s, %(since_pk)s)
              AND ingest_ts < %(until_ts)s
            ORDER BY ingest_ts ASC, source_pk ASC
            LIMIT %(limit)s
            """
        ).format(view=view_id)
        params = {
            "since_ts": since_ts,
            "since_pk": since_pk,
            "until_ts": until_ts,
            "limit":    limit,
        }

        # Execute the composable query against a pooled connection.
        from psycopg.rows import dict_row
        async with verity.db._pool.connection() as conn:  # type: ignore[attr-defined]
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(query, params)
            rows = await cursor.fetchall()

        # Compute next cursor + completeness.
        if rows:
            last = rows[-1]
            next_since = encode_cursor(last["ingest_ts"], last.get("source_pk") or "")
        else:
            next_since = None

        complete = len(rows) < limit  # window fully drained when we got less than asked

        return {
            "view":       view_name,
            "since":      since_ts.isoformat(),
            "until":      until_ts.isoformat(),
            "row_count":  len(rows),
            "complete":   complete,
            "next_since": next_since if not complete else None,
            "rows":       rows,
        }

    return router
