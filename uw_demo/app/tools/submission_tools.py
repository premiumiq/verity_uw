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

            # Get finalized extracted fields (overridden values take precedence)
            await cur.execute(
                """SELECT field_name,
                    CASE WHEN overridden THEN override_value ELSE extracted_value END AS value,
                    confidence, overridden, needs_review
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
            "status": sub.get("status"),
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
) -> dict:
    """Store extracted fields in uw_db.

    Writes one row per field to submission_extraction. Flags
    low-confidence and missing fields for HITL review.

    Args:
        submission_id: UUID of the submission.
        fields: Dict of field_name -> {value, confidence, note}.
        low_confidence_fields: List of field names with low confidence.
        unextractable_fields: List of field names that couldn't be extracted.
        source_document_id: EDMS document ID the fields came from.
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

                # Upsert — update if re-running extraction
                await cur.execute(
                    """INSERT INTO submission_extraction (
                        submission_id, field_name, extracted_value,
                        confidence, extraction_notes, needs_review, review_reason,
                        source_document_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, field_name)
                    DO UPDATE SET
                        extracted_value = EXCLUDED.extracted_value,
                        confidence = EXCLUDED.confidence,
                        extraction_notes = EXCLUDED.extraction_notes,
                        needs_review = EXCLUDED.needs_review,
                        review_reason = EXCLUDED.review_reason,
                        source_document_id = EXCLUDED.source_document_id
                    """,
                    (
                        submission_id, field_name, str(value) if value is not None else None,
                        confidence, note, needs_review, review_reason,
                        source_document_id,
                    ),
                )
                stored += 1

            # Update submission status
            status = "review" if flagged > 0 else "documents_processed"
            await cur.execute(
                "UPDATE submission SET status = %s, updated_at = NOW() WHERE id = %s",
                (status, submission_id),
            )

        await conn.commit()

    return {"stored": True, "fields_stored": stored, "fields_flagged": flagged}


async def store_triage_result(
    submission_id: str,
    risk_score: str,
    routing: str = "",
    reasoning: str = "",
) -> dict:
    """Stores the triage agent's risk assessment in uw_db."""
    import json

    result = {
        "risk_score": risk_score,
        "routing": routing,
        "reasoning": reasoning,
    }

    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO submission_assessment (
                    submission_id, assessment_type, result,
                    risk_score, routing, reasoning
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (submission_id, assessment_type)
                DO UPDATE SET
                    result = EXCLUDED.result,
                    risk_score = EXCLUDED.risk_score,
                    routing = EXCLUDED.routing,
                    reasoning = EXCLUDED.reasoning,
                    created_at = NOW()
                """,
                (
                    submission_id, "triage", json.dumps(result),
                    risk_score, routing, reasoning,
                ),
            )
            await cur.execute(
                "UPDATE submission SET status = 'triaged', updated_at = NOW() WHERE id = %s",
                (submission_id,),
            )
        await conn.commit()

    return {"stored": True, "submission_id": submission_id, "risk_score": risk_score}


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
