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
    get_document_text         — single ref → extracted text string
    get_documents_text        — list of refs → concatenated extracted text
    get_document_metadata     — single ref → metadata dict
    get_document_children     — single ref → list of lineage-linked children
    get_document_content      — single ref → raw bytes
    get_document_content_blocks — list of refs → list of Claude content-block
                                  dicts. PDFs become {type:document, source:
                                  {type:base64, media_type, data}}; text/*
                                  becomes {type:text, text:<contents>};
                                  images become {type:image, source:{...}}.
                                  Used with source_binding binding_kind=
                                  'content_blocks' to drive vision/multi-
                                  modal Claude calls.

Supported write methods:
    create_derived_json      — POST /documents/{parent_id}/derived to store
                               a JSON derivative of an existing document.
                               Payload must contain: parent_id (or
                               destination_document_id), payload (dict),
                               transformation_type (str), and optionally
                               transformation_method + uploaded_by.

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
        if method == "get_documents_text":
            # `ref` is a list of EDMS document refs. Each entry can be a
            # bare id string or a dict with an `id` key (matches the shape
            # UW passes as `input.documents`). Returns the documents'
            # extracted text concatenated with a separator that mirrors
            # what consumers used to inline themselves.
            if not isinstance(ref, list):
                raise ConnectorMethodError(
                    f"get_documents_text expects a list, got {type(ref).__name__}"
                )
            texts: list[str] = []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                for entry in ref:
                    doc_id = entry["id"] if isinstance(entry, dict) else entry
                    if not doc_id:
                        continue
                    try:
                        resp = await http.get(f"{self.base_url}/documents/{doc_id}/text")
                        resp.raise_for_status()
                    except httpx.HTTPStatusError:
                        # Skip refs whose text endpoint can't service the
                        # request (e.g. an already-extracted child has no
                        # /text route). The audit still records that this
                        # ref was supplied; the connector simply can't
                        # contribute text for it.
                        continue
                    text = resp.json().get("text", "")
                    if text:
                        texts.append(text)
            return "\n\n---\n\n".join(texts)
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
        if method == "get_document_content_blocks":
            # `ref` is a list of EDMS document refs (bare ids or dicts
            # with an `id` key). Returns a list of Claude content-block
            # dicts, one per ref. Block shape switches on the doc's
            # content_type:
            #   application/pdf → {"type":"document", "source":{type:base64,...}}
            #   image/*         → {"type":"image",    "source":{type:base64,...}}
            #   text/*          → {"type":"text",     "text":"..."}
            # Refs whose content endpoint fails are skipped silently —
            # the audit's source_resolutions still records the ref list,
            # so a missing entry shows up as a smaller payload_size, not
            # a fatal error. Required-binding semantics are enforced one
            # level up by the runtime when the entire list is empty.
            import base64 as _b64
            if not isinstance(ref, list):
                raise ConnectorMethodError(
                    f"get_document_content_blocks expects a list, got "
                    f"{type(ref).__name__}"
                )
            blocks: list[dict] = []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                for entry in ref:
                    doc_id = entry["id"] if isinstance(entry, dict) else entry
                    if not doc_id:
                        continue
                    # Pull metadata first to learn the content_type
                    # without downloading bytes for unsupported types.
                    try:
                        m = await http.get(f"{self.base_url}/documents/{doc_id}")
                        m.raise_for_status()
                        meta = m.json()
                    except httpx.HTTPError:
                        continue
                    content_type = (meta.get("content_type") or "").lower()

                    if content_type.startswith("text/"):
                        # Text content: fetch /content and emit a text block.
                        try:
                            c = await http.get(
                                f"{self.base_url}/documents/{doc_id}/content"
                            )
                            c.raise_for_status()
                        except httpx.HTTPError:
                            continue
                        blocks.append({
                            "type": "text",
                            "text": c.text,
                        })
                        continue

                    # Binary path (PDF, image, …) — fetch bytes + base64.
                    try:
                        c = await http.get(
                            f"{self.base_url}/documents/{doc_id}/content"
                        )
                        c.raise_for_status()
                    except httpx.HTTPError:
                        continue
                    encoded = _b64.b64encode(c.content).decode("ascii")

                    if content_type == "application/pdf":
                        blocks.append({
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": encoded,
                            },
                        })
                    elif content_type.startswith("image/"):
                        blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": content_type,
                                "data": encoded,
                            },
                        })
                    else:
                        # Unsupported type — skip rather than fabricate.
                        continue
            return blocks
        raise ConnectorMethodError(
            f"EdmsProvider does not implement fetch method {method!r}. "
            f"Supported: get_document_text, get_document_metadata, "
            f"get_document_children, get_document_content."
        )

    async def write(self, method: str, container: str | None, payload: Any) -> Any:
        """Persist a payload via EDMS and return a handle.

        Verity's runtime calls `provider.write(method, container, payload)`
        once per write_target after a Task or Agent finishes. The
        `payload` dict is assembled from the write_target's
        target_payload_field rows (input.* / output.* / const:* refs).

        Returns a handle dict that becomes part of the decision_log's
        `target_writes` JSONB so operators can trace what got written
        where.
        """
        if method == "create_derived_json":
            # Pull the parent identifier from the assembled payload. Targets
            # name it `destination_document_id` to keep the input-schema
            # field name self-explanatory; some callers may use parent_id
            # directly.
            parent_id = payload.get("destination_document_id") or payload.get("parent_id")
            if not parent_id:
                raise ConnectorMethodError(
                    "create_derived_json payload missing destination_document_id"
                )

            # Extract the body keys EDMS expects; everything else under
            # `payload` becomes the stored JSON.
            transformation_type = payload.get("transformation_type", "verity_output")
            transformation_method = payload.get("transformation_method", "verity")
            uploaded_by = payload.get("uploaded_by", "verity")

            # `data` is the structured Verity output. Targets routinely map
            # this from `output.<top-level-field>` (e.g. output.fields).
            data = payload.get("data") or payload.get("payload")
            if not isinstance(data, dict):
                raise ConnectorMethodError(
                    "create_derived_json payload missing `data` (or `payload`) dict"
                )

            body = {
                "payload": data,
                "transformation_type": transformation_type,
                "transformation_method": transformation_method,
                "uploaded_by": uploaded_by,
            }
            async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
                resp = await http.post(
                    f"{self.base_url}/documents/{parent_id}/derived", json=body,
                )
                resp.raise_for_status()
                return resp.json()

        raise ConnectorMethodError(
            f"EdmsProvider.write does not implement {method!r}. "
            f"Supported: create_derived_json."
        )
