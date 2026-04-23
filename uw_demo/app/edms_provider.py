"""EdmsProvider — Verity ConnectorProvider over the EDMS REST API.

Verity declares Tasks with data sources that reference a `data_connector`
by name (e.g. "edms"). The runtime looks up a registered ConnectorProvider
under that name and calls provider.fetch(method, ref) before building the
prompt, so a declared input variable like {{document_text}} gets its
value from EDMS at execution time.

This file lives in uw_demo — it is the seam between Verity (which is
integration-agnostic) and EDMS (this app's document service). It calls
EDMS over plain HTTP via httpx, matching the pattern already used by
uw_demo/app/tools/edms_tools.py. No edms Python package dependency.

Supported fetch methods:
    get_document_text        — returns extracted text as a string
    get_document_metadata    — returns the document metadata dict
    get_document_children    — returns child documents (lineage lookup)
    get_document_content     — returns raw file bytes (e.g. PDF)

Supported write methods (none yet — Task target writes not implemented):
    create_document          — not implemented; a write call raises ConnectorMethodError

If a Task declares a fetch_method this provider doesn't implement, a
ConnectorMethodError is raised. That's preferable to silent fallthrough
and keeps unsupported operations visible in the decision log as failures.
"""

from typing import Any, Optional

import httpx

from verity.runtime.connectors import (
    ConnectorMethodError,
    ConnectorProvider,
)

# Timeout for EDMS calls. PDFs can be large and extraction can be slow,
# so a generous timeout is appropriate for a source fetch.
_TIMEOUT = 30.0


class EdmsProvider(ConnectorProvider):
    """HTTP adapter from Verity's ConnectorProvider protocol to EDMS REST."""

    def __init__(self, base_url: Optional[str] = None):
        """Construct the provider with an EDMS base URL.

        base_url defaults to the in-Docker hostname. The UW app passes
        its configured EDMS_URL so the same code runs against any EDMS
        deployment (dev, staging, prod).
        """
        self.base_url = (base_url or "http://edms:8002").rstrip("/")

    async def fetch(self, method: str, ref: Any) -> Any:
        """Resolve a reference to a payload the prompt can use.

        `ref` is whatever the caller put in input_data under the source's
        input_field_name — typically an EDMS document UUID (as string).
        """
        if method == "get_document_text":
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                resp = await http.get(f"{self.base_url}/documents/{ref}/text")
                resp.raise_for_status()
                return resp.json().get("text", "")
        if method == "get_document_metadata":
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                resp = await http.get(f"{self.base_url}/documents/{ref}")
                resp.raise_for_status()
                return resp.json()
        if method == "get_document_children":
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                resp = await http.get(f"{self.base_url}/documents/{ref}/children")
                resp.raise_for_status()
                return resp.json().get("children", [])
        if method == "get_document_content":
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                resp = await http.get(f"{self.base_url}/documents/{ref}/content")
                resp.raise_for_status()
                return resp.content
        raise ConnectorMethodError(
            f"EdmsProvider does not implement fetch method {method!r}. "
            f"Supported: get_document_text, get_document_metadata, "
            f"get_document_children, get_document_content."
        )

    async def write(self, method: str, container: str | None, payload: Any) -> Any:
        """Persist a payload via EDMS and return a handle.

        Not implemented yet. Any write call raises ConnectorMethodError
        so a premature target declaration surfaces in the decision log
        as a failure rather than silently succeeding.
        """
        raise ConnectorMethodError(
            f"EdmsProvider.write not yet implemented (requested method={method!r})."
        )
