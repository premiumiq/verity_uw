"""Data connector & task-version source/target models.

These are the governance-internal DB read shapes for the declarative I/O
feature. A TaskVersion can declare sources (inputs resolved from external
systems via a registered connector) and targets (outputs written out via
a registered connector).

Runtime plumbing — the provider registry and the fetch/write execution
paths — lives in verity.runtime.connectors. This module is just the
data shapes.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class DataConnector(BaseModel):
    """A registered integration (e.g. 'edms') that Tasks can read/write via.

    The consuming app registers a ConnectorProvider callable under the
    connector's `name` at startup — Verity never imports the integration
    library directly. Secrets live in env vars; non-secret tuning goes in
    `config`.
    """
    id: UUID
    name: str
    connector_type: str
    display_name: str
    description: Optional[str] = None
    config: dict[str, Any] = {}
    owner_name: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskVersionSource(BaseModel):
    """Per-TaskVersion input source declaration.

    If the caller passes `input_field_name` in `input_data`, the execution
    engine fetches `connector.fetch(fetch_method, ref)` and binds the
    payload to `{{maps_to_template_var}}` in the prompt before calling
    Claude. Resolution is eager.
    """
    id: UUID
    task_version_id: UUID
    input_field_name: str
    connector_id: UUID
    connector_name: Optional[str] = None   # populated by joined reads
    fetch_method: str
    maps_to_template_var: str
    required: bool = True
    execution_order: int = 1
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class TaskVersionTarget(BaseModel):
    """Per-TaskVersion output target declaration.

    After Claude returns structured output, the engine takes
    `output_field_name` from the output dict and calls
    `connector.write(write_method, target_container, payload)`. Gated by
    channel and the engine's runtime `write_mode` — see schema comment
    on task_version_target for the gating rules.
    """
    id: UUID
    task_version_id: UUID
    output_field_name: str
    connector_id: UUID
    connector_name: Optional[str] = None
    write_method: str
    target_container: Optional[str] = None
    required: bool = False
    execution_order: int = 1
    description: Optional[str] = None
    created_at: Optional[datetime] = None
