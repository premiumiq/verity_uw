"""Where-used reverse lookup endpoint.

``GET /api/v1/where-used/{entity_type}/{entity_id}``

Returns the agent_version / task_version rows that consume the named
asset. Studio's safe-edit guarantee depends on this:

  - Editing a global prompt/tool/config shows a "Used by N versions"
    panel. Each consumer's lifecycle_state tells the editor whether
    in-place save is safe (drafts only) or must force a clone-to-draft
    (champion / challenger / staging consumers exist).
  - Future YAML import / promotion-batch flows can use the same lookup
    to print impact analyses before committing.

The asset edges are captured by the ``governance.entity_consumers``
view (defined in schema.sql); this endpoint is a thin wrapper around
``Registry.get_entity_consumers``.

See docs/plans/studio-build-plan.md §2.13.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException


# Asset types we currently capture FK-based consumers for. Any other
# value returns 400. Adding a new asset type means: extend the
# ``governance.entity_consumers`` view AND extend this set.
_VALID_ENTITY_TYPES: frozenset[str] = frozenset({
    "prompt",
    "tool",
    "inference_config",
    "data_connector",
})


def build_where_used_router(verity) -> APIRouter:
    """Build the where-used router. Mounted under /api/v1/."""
    router = APIRouter(tags=["where-used"])

    @router.get("/where-used/{entity_type}/{entity_id}")
    async def where_used(entity_type: str, entity_id: str) -> dict:
        """Reverse-lookup consumers for a Verity asset.

        Path params:
            entity_type: 'prompt' | 'tool' | 'inference_config'
                | 'data_connector'.
            entity_id: The asset's UUID.

        Returns:
            ``{used_type, used_id, consumers: [...]}`` where each
            consumer carries ``consumer_type``, ``consumer_id``,
            ``consumer_name``, ``version_label``, and
            ``lifecycle_state``.

        Errors:
            400 — entity_type is not one of the supported values.
            (No 404 for unknown asset id — the contract is that an
            asset with no consumers returns ``consumers: []``, which
            is true for both "exists but unused" and "doesn't exist".
            Existence checks belong on the registry endpoints, not
            here.)
        """
        if entity_type not in _VALID_ENTITY_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"entity_type must be one of "
                    f"{sorted(_VALID_ENTITY_TYPES)}; got {entity_type!r}."
                ),
            )

        consumers = await verity.registry.get_entity_consumers(
            used_type=entity_type, used_id=entity_id,
        )

        return {
            "used_type": entity_type,
            "used_id": entity_id,
            "consumers": consumers,
        }

    return router
