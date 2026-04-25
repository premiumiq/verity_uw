"""UW workflows — plain Python orchestrators for the demo's two flows.

Replaces the pipeline runtime that was descoped from Verity. Each
top-level function below defines one multi-step business workflow as
an ordered sequence of `verity.execution.run_task` /
`verity.execution.run_agent` calls. A single `workflow_run_id` is
threaded through every call so all step audit rows cluster under one
correlation id (queryable via the unified Runs view in Verity).

Mock mode: when `use_mock=True` and a fixture exists for the
submission, that step's output is returned via `FixtureEngine` rather
than a real Claude call. The decision-log row is still written
(mock_mode=True) so the audit trail is identical in shape — only the
LLM round-trip is skipped.

Two workflows live here:
  - run_doc_processing: classify → extract
  - run_risk_assessment: triage → appetite

Both return a `WorkflowResult` whose attributes (`workflow_run_id`,
`status`, `all_steps`) match what `uw_demo/app/ui/routes.py` reads
off pipeline results today, so the UI layer needs minimal change.

Pre-built fixture data lives near the bottom of this file. Keyed by
`step_name` (e.g. `classify_documents`, not the entity name) — that
matches what FixtureEngine looks up.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4

from verity.client.inprocess import Verity
from verity.contracts.decision import ExecutionResult
from verity.runtime.fixture_backend import Fixture, FixtureEngine

logger = logging.getLogger("uw_demo.workflows")


# ══════════════════════════════════════════════════════════════
# RESULT SHAPES — matches what UW routes.py expected from the
# old PipelineResult / StepResult; field-for-field compatible.
# ══════════════════════════════════════════════════════════════


@dataclass
class StepRun:
    """One step in a multi-step workflow.

    `step_name` is the label this workflow gave the step (used by
    FixtureEngine lookup and for audit clarity).
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
    decision-log rows carry. `status` rolls up per-step statuses:
    'complete' if every step completed, 'failed' on first failure,
    'partial' if some steps completed and some were skipped.
    """
    workflow_run_id: UUID
    status: str   # 'complete' | 'failed' | 'partial'
    all_steps: list[StepRun] = field(default_factory=list)
    error_message: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# WORKFLOW 1 — DOCUMENT PROCESSING (classify → extract)
# ══════════════════════════════════════════════════════════════


async def run_doc_processing(
    verity: Verity,
    *,
    submission_id: str,
    pipeline_context: dict[str, Any],
    execution_context_id: Optional[UUID] = None,
    use_mock: bool = False,
) -> WorkflowResult:
    """Two-step doc-processing workflow.

    Step 1 (classify_documents) runs the document_classifier task; its
    output is merged into the input for step 2.
    Step 2 (extract_fields) runs the field_extractor task.
    A fixture map exists for submission ids 0000000{1..4} and is used
    only when use_mock=True; otherwise both tasks call Claude live.
    """
    workflow_run_id = uuid4()
    all_steps: list[StepRun] = []

    fixtures = _doc_processing_fixtures(submission_id) if use_mock else None

    classify = await _run_step(
        verity,
        entity_kind="task",
        entity_name="document_classifier",
        input_data=pipeline_context,
        step_name="classify_documents",
        fixture=(fixtures or {}).get("classify_documents"),
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

    # Merge classify output into the extractor's input. Same dict-merge
    # the old pipeline runtime did between dependent steps.
    extract_input = dict(pipeline_context)
    if classify.execution_result and classify.execution_result.output:
        extract_input.update(classify.execution_result.output)

    extract = await _run_step(
        verity,
        entity_kind="task",
        entity_name="field_extractor",
        input_data=extract_input,
        step_name="extract_fields",
        fixture=(fixtures or {}).get("extract_fields"),
        workflow_run_id=workflow_run_id,
        execution_context_id=execution_context_id,
    )
    all_steps.append(extract)

    if extract.status != "complete":
        return WorkflowResult(
            workflow_run_id=workflow_run_id,
            status="failed",
            all_steps=all_steps,
            error_message=extract.error_message,
        )

    return WorkflowResult(
        workflow_run_id=workflow_run_id,
        status="complete",
        all_steps=all_steps,
    )


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

    fixtures = _risk_assessment_fixtures(submission_id) if use_mock else None

    triage = await _run_step(
        verity,
        entity_kind="agent",
        entity_name="triage_agent",
        input_data=pipeline_context,
        step_name="triage_submission",
        fixture=(fixtures or {}).get("triage_submission"),
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
        fixture=(fixtures or {}).get("assess_appetite"),
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
    fixture: Optional[Fixture],
    workflow_run_id: UUID,
    execution_context_id: Optional[UUID],
) -> StepRun:
    """Dispatch one step, building a StepRun from the engine's result.

    When `fixture` is supplied, FixtureEngine returns the pre-built
    output and writes a decision row with mock_mode=True. Otherwise the
    real ExecutionEngine drives the call.
    """
    try:
        if fixture is not None:
            engine = _build_fixture_engine(verity, step_name, fixture)
            if entity_kind == "task":
                exec_result = await engine.run_task(
                    task_name=entity_name,
                    input_data=input_data,
                    step_name=step_name,
                    workflow_run_id=workflow_run_id,
                    execution_context_id=execution_context_id,
                )
            else:
                exec_result = await engine.run_agent(
                    agent_name=entity_name,
                    context=input_data,
                    step_name=step_name,
                    workflow_run_id=workflow_run_id,
                    execution_context_id=execution_context_id,
                )
        else:
            if entity_kind == "task":
                exec_result = await verity.execution.run_task(
                    task_name=entity_name,
                    input_data=input_data,
                    step_name=step_name,
                    workflow_run_id=workflow_run_id,
                    execution_context_id=execution_context_id,
                )
            else:
                exec_result = await verity.execution.run_agent(
                    agent_name=entity_name,
                    context=input_data,
                    step_name=step_name,
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


def _build_fixture_engine(
    verity: Verity, step_name: str, fixture: Fixture,
) -> FixtureEngine:
    """Construct a per-step FixtureEngine that writes through the same
    governance plane as the live engine — decision log, model invocation
    log, etc. Reuses the verity SDK's registry + decisions writer so
    nothing about audit fidelity changes between mock and live.

    A new engine per call is cheap (lightweight wiring class) and avoids
    holding a long-lived FixtureEngine reference inside the SDK now that
    pipeline_executor is gone.
    """
    engine = FixtureEngine(
        registry=verity._gov.registry,
        decisions=verity._rt.decisions_writer,
        fixtures={step_name: fixture},
        application=verity.application,
    )
    # FixtureEngine doesn't dispatch tools, but accepts registrations
    # for parity with the real engine. Sharing the dict means tools
    # registered at app startup work in both paths.
    engine.tool_implementations = verity._rt.execution.tool_implementations
    return engine


# ══════════════════════════════════════════════════════════════
# DOC PROCESSING FIXTURES
# Keyed by step_name (matches FixtureEngine lookup). Pre-built outputs
# for the four seed submissions; returns None when no fixture exists,
# which the caller treats as "fall back to live execution."
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
