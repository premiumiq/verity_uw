"""Connector provider registry.

Tasks can declare data sources (inputs resolved from external systems) and
targets (outputs written out to external systems). The declarations live
in the `task_version_source` / `task_version_target` tables and reference
a `data_connector` by name. This module holds the runtime mapping from
connector name → a Python provider callable that knows how to talk to the
actual integration.

SEPARATION OF CONCERNS:
  - Verity stores the connector identity + non-secret config in the
    `data_connector` table.
  - The consuming app (e.g. uw_demo) constructs a ConnectorProvider that
    wraps its integration client (e.g. EdmsClient) and registers it here
    at startup via `register_provider(name, provider)`.
  - Verity never imports the integration library itself.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConnectorProvider(Protocol):
    """The contract a connector provider must satisfy.

    `fetch` resolves an input ref to a payload the prompt can use.
    `write` persists an output payload and returns a handle (e.g. the new
    document id) that the decision log records.

    `method` is the fetch/write method name declared on the
    task_version_source / task_version_target row (e.g.
    'get_document_text', 'create_document'). Providers implement whichever
    methods their integration supports; unsupported methods should raise
    ConnectorMethodError.
    """

    async def fetch(self, method: str, ref: Any) -> Any: ...

    async def write(self, method: str, container: str | None, payload: Any) -> Any: ...


class ConnectorError(Exception):
    """Base class for connector-layer failures."""


class ConnectorNotRegistered(ConnectorError):
    """Raised when a TaskVersion references a connector name with no registered provider."""


class ConnectorMethodError(ConnectorError):
    """Raised when a provider doesn't implement the requested fetch/write method."""


class SourceResolutionError(ConnectorError):
    """Raised when a declared source cannot be resolved (required=True).

    Carries `partial_resolutions` so callers can still record what was
    resolved before the failure in the decision log.
    """

    def __init__(self, message: str, partial_resolutions: list | None = None):
        super().__init__(message)
        self.partial_resolutions = partial_resolutions or []


class TargetWriteError(ConnectorError):
    """Raised when a declared target write fails (required=True)."""


# Module-level registry. Populated at app startup by the consuming app.
# Not thread-safe for concurrent mutation — registration is a startup-only
# operation. Reads are concurrent-safe.
_REGISTRY: dict[str, ConnectorProvider] = {}


def register_provider(name: str, provider: ConnectorProvider) -> None:
    """Register a connector provider under the given name.

    `name` must match the `data_connector.name` row in the DB. Overwrites
    any existing registration — useful for hot-reload during development.
    """
    _REGISTRY[name] = provider


def get_provider(name: str) -> ConnectorProvider:
    """Look up a registered provider by connector name.

    Raises ConnectorNotRegistered if no provider has been registered —
    typically means the consuming app forgot to call register_provider at
    startup, or the TaskVersion references a connector that isn't wired.
    """
    try:
        return _REGISTRY[name]
    except KeyError as e:
        raise ConnectorNotRegistered(
            f"No connector provider registered for name={name!r}. "
            f"Registered: {sorted(_REGISTRY.keys())}"
        ) from e


def registered_connectors() -> list[str]:
    """Names of all currently-registered providers (introspection / debug)."""
    return sorted(_REGISTRY.keys())


def clear_registry() -> None:
    """Test-only: wipe the registry. Do not call from production code."""
    _REGISTRY.clear()
