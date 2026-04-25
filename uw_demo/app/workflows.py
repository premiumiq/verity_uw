"""UW workflows — plain Python orchestrators for the demo's two flows.

Replaces the pipeline runtime that was descoped from Verity. Each
top-level function below defines one multi-step business workflow as
an ordered sequence of `verity.execution.run_task` /
`verity.execution.run_agent` calls. A single `workflow_run_id` is
threaded through every call so all step audit rows cluster under one
correlation id (queryable via the unified Runs view in Verity).

Mock mode: when `use_mock=True` and a step output exists for the
submission, the engine short-circuits — Claude isn't called, source
resolution is skipped, target writes are skipped, and the canned
output is returned. Decision_log + execution_run rows still get
written (mock_mode=True) so the audit shape is identical to a real
run. Mock output dicts are built once per workflow into a
MockContext.step_responses keyed by step_name.

Two workflows live here:
  - run_doc_processing: classify → extract
  - run_risk_assessment: triage → appetite

Both return a `WorkflowResult` whose attributes (`workflow_run_id`,
`status`, `all_steps`) match what `uw_demo/app/ui/routes.py` reads
off pipeline results today, so the UI layer needs minimal change.

Pre-built canned outputs live near the bottom of this file. Keyed by
`step_name` (e.g. `classify_documents`, not the entity name) — the
same lookup MockContext.get_step_response uses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4

from verity.client.inprocess import Verity
from verity.contracts.decision import ExecutionResult
from verity.contracts.mock import MockContext

logger = logging.getLogger("uw_demo.workflows")


# ══════════════════════════════════════════════════════════════
# RESULT SHAPES — matches what UW routes.py expected from the
# old PipelineResult / StepResult; field-for-field compatible.
# ══════════════════════════════════════════════════════════════


@dataclass
class StepRun:
    """One step in a multi-step workflow.

    `step_name` is the label this workflow gave the step (used by
    MockContext.step_responses lookup and for audit clarity).
    `execution_result` is what the engine returned; populated for
    every status except 'skipped'.
    `error_message` is duplicated from execution_result.error_message
    for callers that want it without unwrapping the ExecutionResult.
    """
    step_name: str
    status: str   # 'complete' | 'failed' | 'skipped'
    execution_result: Optional[ExecutionResult] = None
    error_message: Optional[str] = None


@dataclass
class WorkflowResult:
    """Aggregate result for one workflow invocation.

    `workflow_run_id` is the caller-supplied correlation id all step
    decision-log rows carry. `status` is one of:
      - 'complete'                   — every step succeeded.
      - 'partial'                    — some triggered extractions failed.
      - 'no_extractable_documents'   — classifier ran on every doc but
                                        none matched a registered
                                        extractor (e.g. submission
                                        contains only loss runs and
                                        financials, no application
                                        form). The UI must surface
                                        this distinctly from 'complete'.
      - 'failed'                     — a hard step failure stopped the
                                        workflow.
    """
    workflow_run_id: UUID
    status: str
    all_steps: list[StepRun] = field(default_factory=list)
    error_message: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# WORKFLOW 1 — DOCUMENT PROCESSING (classify → extract)
# ══════════════════════════════════════════════════════════════


# Map a classifier-returned document_type to the extractor task that
# knows how to handle it. Document types not in this map (loss_run,
# financial_statement, board_resolution, supplemental_*, other, etc.)
# are intentionally skipped — they don't have a registered extractor.
# Adding a new extractor is a two-line change here plus its task seed.
_EXTRACTOR_FOR_DOC_TYPE: dict[str, str] = {
    "do_application": "field_extractor",
    "gl_application": "gl_field_extractor",
}


async def run_doc_processing(
    verity: Verity,
    *,
    submission_id: str,
    pipeline_context: dict[str, Any],
    execution_context_id: Optional[UUID] = None,
    use_mock: bool = False,
) -> WorkflowResult:
    """Per-document doc-processing workflow.

    Iterates `pipeline_context["documents"]` (the EDMS reference list).
    For every document:
      1. classify_documents:<filename> — runs document_classifier with
         the single ref. Each call gets its own audit row.
      2. extract_fields:<filename> — runs the extractor matching the
         classification's document_type (do_application →
         field_extractor; gl_application → gl_field_extractor; anything
         else → skipped). Each extract call gets its own audit row and
         writes its own JSON-derivative child to EDMS under that
         document.

    Workflow status rolls up:
      - `complete`                — every classify succeeded AND every
                                     triggered extract succeeded.
      - `partial`                 — some extracts failed (others may
                                     have succeeded; classifier finished).
      - `no_extractable_documents` — every classify succeeded but no
                                     document matched a registered
                                     extractor. The submission has no
                                     extracted fields, and the UI
                                     should say so explicitly.
      - `failed`                  — a classify hard-failed OR every
                                     triggered extract failed.
    """
    workflow_run_id = uuid4()
    all_steps: list[StepRun] = []
    mock = _build_mock(_doc_processing_outputs(submission_id) if use_mock else None)

    documents: list[dict[str, Any]] = pipeline_context.get("documents") or []
    if not documents:
        return WorkflowResult(
            workflow_run_id=workflow_run_id,
            status="failed",
            all_steps=all_steps,
            error_message="No documents in submission to process.",
        )

    extract_failures = 0
    extract_attempts = 0
    classified_count = 0

    for doc in documents:
        doc_id = doc.get("id")
        doc_label = _short_doc_label(doc)

        # Per-doc input: only the metadata fields the prompts need plus
        # a single-element documents list. The source_binding fetches
        # text for that one ref; the prompt sees one document.
        per_doc_input = {
            "submission_id": pipeline_context.get("submission_id"),
            "lob": pipeline_context.get("lob"),
            "named_insured": pipeline_context.get("named_insured"),
            "documents": [doc],
        }

        classify = await _run_step(
            verity,
            entity_kind="task",
            entity_name="document_classifier",
            input_data=per_doc_input,
            step_name=f"classify_documents:{doc_label}",
            mock=mock,
            workflow_run_id=workflow_run_id,
            execution_context_id=execution_context_id,
        )
        all_steps.append(classify)
        if classify.status != "complete":
            return WorkflowResult(
                workflow_run_id=workflow_run_id,
                status="failed",
                all_steps=all_steps,
                error_message=classify.error_message,
            )

        classified_count += 1

        # Look up the right extractor for this document_type. Anything
        # not in _EXTRACTOR_FOR_DOC_TYPE is intentionally skipped —
        # loss_run, financial_statement, board_resolution, etc. don't
        # have a registered extractor and that's fine.
        classification = (
            classify.execution_result.output
            if classify.execution_result and classify.execution_result.output
            else {}
        )
        doc_type = classification.get("document_type")
        extractor_name = _EXTRACTOR_FOR_DOC_TYPE.get(doc_type)
        if not extractor_name:
            logger.info(
                "doc_processing skip-extract submission=%s doc_id=%s "
                "classified_as=%s reason=no_extractor_for_type",
                submission_id, doc_id, doc_type,
            )
            continue

        extract_attempts += 1
        extract_input = {
            "submission_id": pipeline_context.get("submission_id"),
            "named_insured": pipeline_context.get("named_insured"),
            "documents": [doc],
            **classification,
        }
        extract = await _run_step(
            verity,
            entity_kind="task",
            entity_name=extractor_name,
            input_data=extract_input,
            step_name=f"extract_fields:{doc_label}",
            mock=mock,
            workflow_run_id=workflow_run_id,
            execution_context_id=execution_context_id,
        )
        all_steps.append(extract)
        if extract.status != "complete":
            extract_failures += 1
            logger.warning(
                "doc_processing extract failed submission=%s doc_id=%s "
                "extractor=%s reason=%s",
                submission_id, doc_id, extractor_name, extract.error_message,
            )

    # Roll up status.
    if extract_attempts == 0:
        # Every classification ran (otherwise we would have returned
        # 'failed' above) but no document matched a registered
        # extractor. This is a real outcome the UI must surface — the
        # submission has no extracted fields, and that's not a hidden
        # success.
        status = "no_extractable_documents"
        error_message = (
            f"{classified_count} document(s) classified, none matched a "
            f"registered extractor. Supported types: "
            f"{sorted(_EXTRACTOR_FOR_DOC_TYPE.keys())}."
        )
    elif extract_failures and extract_failures == extract_attempts:
        status = "failed"
        error_message = (
            f"All {extract_attempts} extractions failed."
        )
    elif extract_failures:
        status = "partial"
        error_message = (
            f"{extract_failures} of {extract_attempts} extractions failed."
        )
    else:
        status = "complete"
        error_message = None

    return WorkflowResult(
        workflow_run_id=workflow_run_id,
        status=status,
        all_steps=all_steps,
        error_message=error_message,
    )


def _short_doc_label(doc: dict[str, Any]) -> str:
    """Build a step_name suffix that's human-readable in audit views.

    Prefer the filename (truncated) so multiple per-doc rows are
    distinguishable at a glance; fall back to the first 8 chars of
    the EDMS UUID when filename is missing.
    """
    fname = doc.get("filename")
    if fname:
        return fname[:60]
    doc_id = doc.get("id", "")
    return doc_id.split("-")[0] if doc_id else "unknown"


# ══════════════════════════════════════════════════════════════
# WORKFLOW 2 — RISK ASSESSMENT (triage → appetite)
# ══════════════════════════════════════════════════════════════


async def run_risk_assessment(
    verity: Verity,
    *,
    submission_id: str,
    pipeline_context: dict[str, Any],
    execution_context_id: Optional[UUID] = None,
    use_mock: bool = False,
) -> WorkflowResult:
    """Two-step risk-assessment workflow: triage → appetite."""
    workflow_run_id = uuid4()
    all_steps: list[StepRun] = []
    mock = _build_mock(_risk_assessment_outputs(submission_id) if use_mock else None)

    triage = await _run_step(
        verity,
        entity_kind="agent",
        entity_name="triage_agent",
        input_data=pipeline_context,
        step_name="triage_submission",
        mock=mock,
        workflow_run_id=workflow_run_id,
        execution_context_id=execution_context_id,
    )
    all_steps.append(triage)
    if triage.status != "complete":
        return WorkflowResult(
            workflow_run_id=workflow_run_id,
            status="failed",
            all_steps=all_steps,
            error_message=triage.error_message,
        )

    appetite_input = dict(pipeline_context)
    if triage.execution_result and triage.execution_result.output:
        appetite_input.update(triage.execution_result.output)

    appetite = await _run_step(
        verity,
        entity_kind="agent",
        entity_name="appetite_agent",
        input_data=appetite_input,
        step_name="assess_appetite",
        mock=mock,
        workflow_run_id=workflow_run_id,
        execution_context_id=execution_context_id,
    )
    all_steps.append(appetite)

    if appetite.status != "complete":
        return WorkflowResult(
            workflow_run_id=workflow_run_id,
            status="failed",
            all_steps=all_steps,
            error_message=appetite.error_message,
        )

    return WorkflowResult(
        workflow_run_id=workflow_run_id,
        status="complete",
        all_steps=all_steps,
    )


# ══════════════════════════════════════════════════════════════
# PER-STEP DISPATCHER (mock vs live)
# ══════════════════════════════════════════════════════════════


async def _run_step(
    verity: Verity,
    *,
    entity_kind: str,        # 'task' | 'agent'
    entity_name: str,
    input_data: dict[str, Any],
    step_name: str,
    mock: Optional[MockContext],
    workflow_run_id: UUID,
    execution_context_id: Optional[UUID],
) -> StepRun:
    """Dispatch one step through the engine, return a StepRun.

    The engine itself decides whether to short-circuit on a step mock
    (`mock.step_responses`) or run for real — there's only one code
    path here, regardless of mock vs live. Keeps audit shape identical
    in both modes.
    """
    try:
        if entity_kind == "task":
            exec_result = await verity.execution.run_task(
                task_name=entity_name,
                input_data=input_data,
                step_name=step_name,
                mock=mock,
                workflow_run_id=workflow_run_id,
                execution_context_id=execution_context_id,
            )
        else:
            exec_result = await verity.execution.run_agent(
                agent_name=entity_name,
                context=input_data,
                step_name=step_name,
                mock=mock,
                workflow_run_id=workflow_run_id,
                execution_context_id=execution_context_id,
            )
    except Exception as exc:
        # The engine catches its own internal exceptions and returns
        # ExecutionResult(status='failed'); reaching this branch means
        # something failed earlier (e.g. registry lookup, source
        # resolution before the run_task try-block). Surface as a
        # failed StepRun without an execution_result so the workflow
        # caller can short-circuit cleanly.
        logger.exception("workflow step %s/%s failed before engine entry",
                         entity_kind, entity_name)
        return StepRun(
            step_name=step_name,
            status="failed",
            execution_result=None,
            error_message=str(exc),
        )

    return StepRun(
        step_name=step_name,
        status=exec_result.status if exec_result.status in (
            "complete", "failed", "skipped",
        ) else "complete",
        execution_result=exec_result,
        error_message=exec_result.error_message,
    )


def _build_mock(
    step_outputs: Optional[dict[str, dict]],
) -> Optional[MockContext]:
    """Wrap a per-step canned-output dict in a MockContext, or None.

    Caller passes in {step_name: output_dict, ...} or None. When None,
    the engine runs Claude for real. When a dict is supplied, the
    engine short-circuits on each matching step_name and returns the
    canned output verbatim.
    """
    if not step_outputs:
        return None
    return MockContext(step_responses=step_outputs)


# ══════════════════════════════════════════════════════════════
# DOC PROCESSING FIXTURES
# Keyed by step_name to match MockContext.step_responses lookup.
# Pre-built outputs for the four seed submissions; returns None when
# no fixture exists, which the caller treats as "fall back to live
# execution."
# ══════════════════════════════════════════════════════════════


def _doc_processing_fixtures(submission_id: str) -> Optional[dict[str, Fixture]]:
    outputs = _doc_processing_outputs(submission_id)
    if not outputs:
        return None
    return {
        "classify_documents": Fixture(output=outputs["classify_documents"]),
        "extract_fields": Fixture(output=outputs["extract_fields"]),
    }


def _doc_processing_outputs(submission_id: str) -> Optional[dict[str, dict]]:
    if submission_id.startswith("00000001"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-001", "document_type": "do_application", "confidence": 0.97,
                     "classification_notes": "Clear D&O liability application with board composition section"},
                    {"document_id": "mock-002", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report with 3-year claims summary"},
                    {"document_id": "mock-003", "document_type": "board_resolution", "confidence": 0.93,
                     "classification_notes": "Board resolution authorizing D&O coverage"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Acme Dynamics LLC", "confidence": 0.98, "note": "Section I header"},
                    "fein": {"value": "12-3456789", "confidence": 0.97, "note": "Section I, FEIN field"},
                    "entity_type": {"value": "LLC", "confidence": 0.95, "note": "Entity type checkbox"},
                    "state_of_incorporation": {"value": "Delaware", "confidence": 0.96, "note": "State field"},
                    "annual_revenue": {"value": 50000000, "confidence": 0.95, "note": "Section II revenue"},
                    "employee_count": {"value": 250, "confidence": 0.94, "note": "Section II employees"},
                    "board_size": {"value": 7, "confidence": 0.92, "note": "Section III directors"},
                    "independent_directors": {"value": 4, "confidence": 0.90, "note": "Section III independent"},
                    "effective_date": {"value": "2026-07-01", "confidence": 0.98, "note": "Coverage dates"},
                    "expiration_date": {"value": "2027-07-01", "confidence": 0.98, "note": "Coverage dates"},
                    "limits_requested": {"value": 5000000, "confidence": 0.96, "note": "Coverage limits"},
                    "retention_requested": {"value": 100000, "confidence": 0.95, "note": "Retention field"},
                    "prior_carrier": {"value": "National Union", "confidence": 0.93, "note": "Prior coverage"},
                    "prior_premium": {"value": 45000, "confidence": 0.91, "note": "Prior premium"},
                    "ipo_planned": {"value": False, "confidence": 0.88, "note": "IPO question - No checked"},
                    "going_concern_opinion": {"value": False, "confidence": 0.90, "note": "Going concern - No"},
                    "non_renewed_by_carrier": {"value": False, "confidence": 0.89, "note": "Non-renewal - No"},
                },
                "low_confidence_fields": [],
                "unextractable_fields": [
                    "securities_class_action_history",
                    "merger_acquisition_activity",
                    "regulatory_investigation_history",
                ],
                "extraction_complete": True,
            },
        }
    if submission_id.startswith("00000002"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-004", "document_type": "do_application", "confidence": 0.94,
                     "classification_notes": "D&O application with some non-standard formatting"},
                    {"document_id": "mock-005", "document_type": "loss_run", "confidence": 0.96,
                     "classification_notes": "Loss run with claim details"},
                    {"document_id": "mock-006", "document_type": "financial_statement", "confidence": 0.92,
                     "classification_notes": "Financial statements with auditor report"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "TechFlow Industries Inc", "confidence": 0.98, "note": "Header"},
                    "annual_revenue": {"value": 120000000, "confidence": 0.95, "note": "Revenue field"},
                    "employee_count": {"value": 800, "confidence": 0.94, "note": "Employees field"},
                    "board_size": {"value": 9, "confidence": 0.92, "note": "Directors section"},
                    "regulatory_investigation_history": {"value": "SEC inquiry pending", "confidence": 0.65, "note": "Regulatory section - text unclear"},
                },
                "low_confidence_fields": ["regulatory_investigation_history"],
                "unextractable_fields": [],
                "extraction_complete": True,
            },
        }
    if submission_id.startswith("00000003"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-007", "document_type": "gl_application", "confidence": 0.91,
                     "classification_notes": "GL application form"},
                    {"document_id": "mock-008", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report"},
                    {"document_id": "mock-009", "document_type": "financial_statement", "confidence": 0.90,
                     "classification_notes": "Financial statements"},
                ],
                "total_documents": 3,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Meridian Holdings Corp", "confidence": 0.97, "note": "Header"},
                    "annual_revenue": {"value": 25000000, "confidence": 0.94, "note": "Revenue"},
                    "employee_count": {"value": 150, "confidence": 0.93, "note": "Employees"},
                },
                "low_confidence_fields": ["prior_premium"],
                "unextractable_fields": ["board_size"],
                "extraction_complete": True,
            },
        }
    if submission_id.startswith("00000004"):
        return {
            "classify_documents": {
                "documents_classified": [
                    {"document_id": "mock-010", "document_type": "gl_application", "confidence": 0.93,
                     "classification_notes": "Standard GL application"},
                    {"document_id": "mock-011", "document_type": "loss_run", "confidence": 0.95,
                     "classification_notes": "Loss run report"},
                ],
                "total_documents": 2,
            },
            "extract_fields": {
                "fields": {
                    "named_insured": {"value": "Acme Dynamics LLC", "confidence": 0.97, "note": "Header"},
                    "annual_revenue": {"value": 50000000, "confidence": 0.95, "note": "Revenue"},
                    "employee_count": {"value": 250, "confidence": 0.94, "note": "Employees"},
                },
                "low_confidence_fields": [],
                "unextractable_fields": [],
                "extraction_complete": True,
            },
        }
    return None


# ══════════════════════════════════════════════════════════════
# RISK ASSESSMENT FIXTURES
# ══════════════════════════════════════════════════════════════


def _risk_assessment_fixtures(submission_id: str) -> Optional[dict[str, Fixture]]:
    outputs = _risk_assessment_outputs(submission_id)
    if not outputs:
        return None
    return {
        "triage_submission": Fixture(output=outputs["triage_submission"]),
        "assess_appetite": Fixture(output=outputs["assess_appetite"]),
    }


def _risk_assessment_outputs(submission_id: str) -> Optional[dict[str, dict]]:
    if submission_id.startswith("00000001"):
        return {
            "triage_submission": {
                "risk_score": "Green", "routing": "assign_to_uw", "confidence": 0.89,
                "reasoning": "Strong financials with $50M revenue, clean loss history, experienced 7-member board.",
                "risk_factors": [{"factor": "Revenue concentration", "severity": "low", "detail": "Single market segment"}],
            },
            "assess_appetite": {
                "determination": "within_appetite", "confidence": 0.92,
                "reasoning": "Meets all D&O guidelines criteria per §2.1-2.4.",
                "guideline_citations": [
                    {"section": "§2.1", "criterion": "Revenue > $10M", "submission_value": "$50M", "meets_criterion": True},
                ],
            },
        }
    if submission_id.startswith("00000002"):
        return {
            "triage_submission": {
                "risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.72,
                "reasoning": "Mixed profile. Strong revenue but pending SEC inquiry and recent board turnover.",
                "risk_factors": [
                    {"factor": "Regulatory investigation", "severity": "medium", "detail": "SEC inquiry pending"},
                    {"factor": "Board turnover", "severity": "low", "detail": "3 directors replaced in 12 months"},
                ],
            },
            "assess_appetite": {
                "determination": "borderline", "confidence": 0.65,
                "reasoning": "Meets most criteria but §3.2 flags pending regulatory matters.",
                "guideline_citations": [
                    {"section": "§3.2", "criterion": "No pending regulatory investigations", "submission_value": "SEC inquiry pending", "meets_criterion": False},
                ],
            },
        }
    if submission_id.startswith("00000003"):
        return {
            "triage_submission": {
                "risk_score": "Red", "routing": "refer_to_management", "confidence": 0.85,
                "reasoning": "High claims frequency, going concern qualification, excluded SIC codes.",
                "risk_factors": [
                    {"factor": "Claims frequency", "severity": "high", "detail": "12 claims in 3 years"},
                    {"factor": "Going concern", "severity": "critical", "detail": "Auditor qualified opinion"},
                ],
            },
            "assess_appetite": {
                "determination": "outside_appetite", "confidence": 0.94,
                "reasoning": "Multiple guideline violations: §4.1 excluded SIC code and §4.3 going concern.",
                "guideline_citations": [
                    {"section": "§4.1", "criterion": "SIC code not excluded", "submission_value": "Excluded SIC", "meets_criterion": False},
                    {"section": "§4.3", "criterion": "No going concern opinion", "submission_value": "Qualified opinion", "meets_criterion": False},
                ],
            },
        }
    if submission_id.startswith("00000004"):
        return {
            "triage_submission": {
                "risk_score": "Amber", "routing": "assign_to_senior_uw", "confidence": 0.74,
                "reasoning": "Adequate financials but GL exposure from manufacturing operations.",
                "risk_factors": [
                    {"factor": "Manufacturing operations", "severity": "medium", "detail": "Products liability exposure"},
                    {"factor": "Claims trend", "severity": "low", "detail": "Increasing frequency, stable severity"},
                ],
            },
            "assess_appetite": {
                "determination": "within_appetite", "confidence": 0.81,
                "reasoning": "Meets GL criteria. Manufacturing operations within acceptable risk classes per §5.2.",
                "guideline_citations": [
                    {"section": "§5.2", "criterion": "Manufacturing SIC codes allowed", "submission_value": "Allowed SIC", "meets_criterion": True},
                ],
            },
        }
    return None
