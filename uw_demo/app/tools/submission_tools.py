"""Submission Tools — read/write submission data from uw_db.

These are the tool implementations that Claude calls during agent execution.
Each function queries uw_db (the underwriting database) for real data.

All functions are async because they use psycopg3 async connections.
The execution engine checks asyncio.iscoroutinefunction() and awaits them.

Each function's signature must match the tool's registered input_schema.
The execution engine calls these as: await func(**tool_input) where
tool_input is the dict Claude provides.
"""

import psycopg

from uw_demo.app.config import settings


async def _get_conn():
    """Get an async database connection to uw_db."""
    return await psycopg.AsyncConnection.connect(settings.UW_DB_URL)


# ── READ TOOLS ───────────────────────────────────────────────

async def get_submission_context(submission_id: str) -> dict:
    """Returns full submission data: account info, policy details, loss history.

    Called by triage_agent and appetite_agent to gather context
    before making their assessment. Reads finalized data from uw_db
    (post-HITL if any extraction overrides were made).
    """
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            # Get submission record
            await cur.execute(
                "SELECT * FROM submission WHERE id = %s", (submission_id,)
            )
            row = await cur.fetchone()
            if not row:
                return {"error": f"Submission {submission_id} not found"}

            # Column names from cursor description
            cols = [d.name for d in cur.description]
            sub = dict(zip(cols, row))

            # Get finalized extracted fields. The two-channel model
            # (ai_*, hitl_*) means the displayed/used value is
            # hitl_value if set, else ai_value. `overridden` is
            # derived: the field has a HITL value.
            await cur.execute(
                """SELECT field_name,
                    COALESCE(hitl_value, ai_value) AS value,
                    ai_confidence,
                    (hitl_value IS NOT NULL) AS overridden,
                    needs_review
                FROM submission_extraction
                WHERE submission_id = %s""",
                (submission_id,),
            )
            extractions = await cur.fetchall()
            extracted_fields = {}
            for field_name, value, confidence, overridden, needs_review in extractions:
                extracted_fields[field_name] = {
                    "value": value,
                    "confidence": float(confidence) if confidence else None,
                    "overridden": overridden,
                }

            # Get loss history
            await cur.execute(
                """SELECT policy_year, claims_count, incurred, paid, reserves
                FROM loss_history
                WHERE submission_id = %s
                ORDER BY policy_year""",
                (submission_id,),
            )
            loss_rows = await cur.fetchall()
            loss_history = [
                {"year": y, "claims": c, "incurred": float(i), "paid": float(p), "reserves": float(r)}
                for y, c, i, p, r in loss_rows
            ]

    # Build response in the same structure agents expect
    return {
        "account": {
            "name": sub["named_insured"],
            "fein": sub.get("fein"),
            "entity_type": sub.get("entity_type"),
            "state_of_incorporation": sub.get("state_of_incorporation"),
            "sic_code": sub.get("sic_code"),
            "sic_description": sub.get("sic_description"),
        },
        "submission": {
            "id": str(sub["id"]),
            "lob": sub["lob"],
            "named_insured": sub["named_insured"],
            "annual_revenue": sub.get("annual_revenue"),
            "employee_count": sub.get("employee_count"),
            "board_size": sub.get("board_size"),
            "independent_directors": sub.get("independent_directors"),
            "effective_date": str(sub["effective_date"]) if sub.get("effective_date") else None,
            "expiration_date": str(sub["expiration_date"]) if sub.get("expiration_date") else None,
            "limits_requested": sub.get("limits_requested"),
            "retention_requested": sub.get("retention_requested"),
            "prior_carrier": sub.get("prior_carrier"),
            "prior_premium": sub.get("prior_premium"),
        },
        "extracted_fields": extracted_fields,
        "loss_history": loss_history,
    }


async def get_loss_history(submission_id: str) -> dict:
    """Returns loss history for the given submission.

    Takes the submission UUID (same value used in the pipeline context).
    In the demo there is no separate account table; loss history is
    keyed by submission_id directly on the loss_history table.
    """
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            # Get insured name
            await cur.execute(
                "SELECT named_insured FROM submission WHERE id = %s",
                (submission_id,),
            )
            row = await cur.fetchone()
            account_name = row[0] if row else "Unknown"

            # Get loss history
            await cur.execute(
                """SELECT policy_year, claims_count, incurred, paid, reserves
                FROM loss_history
                WHERE submission_id = %s
                ORDER BY policy_year""",
                (submission_id,),
            )
            rows = await cur.fetchall()

    years = [
        {"year": y, "claims": c, "incurred": float(i), "paid": float(p), "reserves": float(r)}
        for y, c, i, p, r in rows
    ]
    return {
        "account": account_name,
        "years": years,
        "total_claims": sum(y["claims"] for y in years),
        "total_incurred": sum(y["incurred"] for y in years),
    }


# ── WRITE TOOLS ──────────────────────────────────────────────

async def store_extraction_result(
    submission_id: str,
    fields: dict,
    low_confidence_fields: list = None,
    unextractable_fields: list = None,
    source_document_id: str = None,
    workflow_run_id: str = None,
    decision_log_id: str = None,
    extractor_id: str = None,
) -> dict:
    """Store extracted fields in uw_db.

    Writes one row per field to submission_extraction's AI channel,
    plus the structured provenance the override API and sparkle UX
    need: source document id (already), extractor id (e.g.
    'field_extractor@1.0.0'), Verity decision-log id of the run that
    produced the value, JSONPath of the field within that run's
    output, and the UW-side workflow_run_id.

    Args:
        submission_id: UUID of the submission.
        fields: Dict of field_name -> {value, confidence, note}.
        low_confidence_fields: Field names flagged low-confidence.
        unextractable_fields: Field names the AI couldn't find.
        source_document_id: uw_db `document.id` the fields came from.
        workflow_run_id: UW-side correlation id for this pipeline run.
        decision_log_id: Verity-side id of the extracting agent's
            decision row. Stored on submission_extraction.verity_execution_run_id;
            the override API uses this to anchor a HITL flip back
            to the specific run that produced the value.
        extractor_id: Identifier of the extracting agent
            (e.g. 'field_extractor@1.0.0'). Drives the
            sparkle-tooltip 'Extractor:' line.
    """
    low_conf = set(low_confidence_fields or [])
    unextractable = set(unextractable_fields or [])
    stored = 0
    flagged = 0

    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            for field_name, field_data in fields.items():
                value = field_data.get("value") if isinstance(field_data, dict) else field_data
                confidence = field_data.get("confidence", 0.0) if isinstance(field_data, dict) else 0.0
                note = field_data.get("note", "") if isinstance(field_data, dict) else ""

                # Determine if this field needs review
                needs_review = False
                review_reason = None
                if field_name in unextractable:
                    needs_review = True
                    review_reason = "missing"
                elif field_name in low_conf:
                    needs_review = True
                    review_reason = "low_confidence"
                elif confidence is not None and confidence < 0.70:
                    needs_review = True
                    review_reason = "low_confidence"

                if needs_review:
                    flagged += 1

                # Upsert into the AI channel of submission_extraction.
                # ai_found is TRUE for any field the AI produced a row
                # for — even if the produced value is NULL ("AI looked
                # but didn't find") which is the unextractable case.
                # hitl_* columns are untouched here; the approve_extraction
                # handler is the only writer to that channel.
                ai_found = field_name not in unextractable

                # Map the extractor's free-form note to source_snippet
                # (the verbatim quote that drives the sparkle tooltip);
                # if the extractor didn't supply one we leave it null.
                source_snippet = note or None

                # JSONPath into this run's output_json. The
                # field_extractor task produces
                # {fields: {<name>: {value, confidence, note}}}
                # so a per-field path of $.fields.<name>.value is
                # what the override API will resolve at edit time.
                output_path = f"$.fields.{field_name}.value"

                await cur.execute(
                    """INSERT INTO submission_extraction (
                        submission_id, field_name,
                        ai_value, ai_confidence, ai_found,
                        source_document_id, source_snippet,
                        verity_execution_run_id, output_path, extractor_id,
                        workflow_run_id,
                        needs_review, review_reason
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, field_name)
                    DO UPDATE SET
                        ai_value                = EXCLUDED.ai_value,
                        ai_confidence           = EXCLUDED.ai_confidence,
                        ai_found                = EXCLUDED.ai_found,
                        source_document_id      = EXCLUDED.source_document_id,
                        source_snippet          = EXCLUDED.source_snippet,
                        verity_execution_run_id = EXCLUDED.verity_execution_run_id,
                        output_path             = EXCLUDED.output_path,
                        extractor_id            = EXCLUDED.extractor_id,
                        workflow_run_id         = EXCLUDED.workflow_run_id,
                        needs_review            = EXCLUDED.needs_review,
                        review_reason           = EXCLUDED.review_reason
                    """,
                    (
                        submission_id, field_name,
                        str(value) if value is not None else None,
                        confidence, ai_found,
                        source_document_id, source_snippet,
                        decision_log_id, output_path, extractor_id,
                        workflow_run_id,
                        needs_review, review_reason,
                    ),
                )
                stored += 1

            # NOTE: stage transitions are owned by the route handler
            # (run_document_processing decides whether to flip
            # information_review to running vs complete based on
            # whether any field needs_review). This tool no longer
            # writes to the old submission.status column — that
            # column was dropped in 4.1.

        await conn.commit()

    return {"stored": True, "fields_stored": stored, "fields_flagged": flagged}


# store_triage_result removed 2026-04-25.
# triage_agent now uses enforce_output_schema=True. The agent's
# structured output_json is the canonical conclusion; persistence to
# submission_assessment is driven by the route reading
# agent_decision_log.output_json after the run, not by a tool call
# during the agent loop. The transition to status='triaged' is now
# stamped by the route via _update_submission_status when the
# workflow completes.


async def update_submission_event(
    submission_id: str,
    event_type: str,
    details: dict = None,
) -> dict:
    """Logs a workflow event. Currently just acknowledges."""
    return {
        "event_id": f"evt-{submission_id[:8]}",
        "event_type": event_type,
        "logged": True,
    }
