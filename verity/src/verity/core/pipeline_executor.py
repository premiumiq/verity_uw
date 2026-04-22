"""Pipeline executor — re-export shim.

The pipeline executor now lives at verity.runtime.pipeline (renamed from
pipeline_executor). This module re-exports PipelineExecutor, PipelineResult,
and StepResult so existing
`from verity.core.pipeline_executor import PipelineExecutor, PipelineResult`
imports keep working during the registry/runtime split.
"""

from verity.runtime.pipeline import PipelineExecutor, PipelineResult, StepResult  # noqa: F401

__all__ = ["PipelineExecutor", "PipelineResult", "StepResult"]
