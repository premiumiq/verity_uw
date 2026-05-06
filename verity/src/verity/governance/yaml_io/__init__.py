"""YAML import/export for Verity entities.

This package implements the YAML round-trip surface described in
docs/plans/studio-build-plan.md §2.6. The format itself is documented
in §"YAML format for review" of that doc.

Public surface:

    from verity.governance.yaml_io import Exporter, dumps_bundle

    exporter = Exporter(verity.registry)
    bundle = await exporter.export_agent("triage_agent")
    yaml_text = dumps_bundle(bundle)

Slice 4A (this slice) ships the export path only. Slice 4B adds the
importer plus the round-trip property test.
"""

from verity.governance.yaml_io.exporter import Exporter
from verity.governance.yaml_io.importer import (
    ImportError,
    ImportResult,
    Importer,
    ImportValidationError,
)
from verity.governance.yaml_io.models import (
    AgentEntry,
    AgentVersionEntry,
    Bundle,
    DataConnectorEntry,
    InferenceConfigEntry,
    PromptAssignment,
    PromptEntry,
    PromptVersionEntry,
    TaskEntry,
    TaskVersionEntry,
    ToolAuthorization,
    ToolEntry,
)
from verity.governance.yaml_io.serialization import dumps_bundle, loads_bundle

__all__ = [
    "Exporter",
    "Importer",
    "ImportResult",
    "ImportError",
    "ImportValidationError",
    "dumps_bundle",
    "loads_bundle",
    "Bundle",
    "AgentEntry",
    "AgentVersionEntry",
    "DataConnectorEntry",
    "InferenceConfigEntry",
    "PromptAssignment",
    "PromptEntry",
    "PromptVersionEntry",
    "TaskEntry",
    "TaskVersionEntry",
    "ToolAuthorization",
    "ToolEntry",
]
