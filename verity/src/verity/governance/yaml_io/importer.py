"""Bundle → DB import.

Two-phase, complementary to the Exporter:

  Phase 1 — Validate
    Walk every reference in the bundle (prompt+version, tool name,
    inference_config, data_connector, child_agent) and check that
    each one resolves to either:
      - another entry in the same bundle, OR
      - an existing row in the target DB.
    Failures are aggregated into a single ImportValidationError so
    the user sees every issue at once. Phase 2 only runs if
    validation passes.

  Phase 2 — Write
    Insert in dependency order (leaves first, agents last). For each
    entity:
      - Header (or non-versioned entity) missing → INSERT.
      - Header existing → SKIP. Header changes go through the
        registry's PATCH endpoints, not via YAML import; this keeps
        re-import safe and predictable.
      - Version missing → INSERT as draft (lifecycle_state in the
        YAML is informational, never honoured on write — promotion
        is always a deliberate human action).
      - Version existing (any state) → SKIP.

The "skip if existing" rule is the slice 4B v1 simplification.
Future work: support an explicit ``--update-drafts`` flag that
modifies in-place draft versions (per the build plan §6 rule), and
content-equality-based no-op for non-draft versions. Both can land
without changing the public API surface.

What the importer does NOT do (yet):
  - Wrap writes in a single transaction. A mid-import failure
    leaves partial state. Validation prevents most failure modes
    but not all (constraint violations not caught at validate time).
    Adding a transaction wrapper is a small follow-up.
  - Update existing draft versions. New deferred to slice 4B+.
  - Round-trip ``mock_responses`` on tools (insert_tool doesn't
    accept that column today; would need a small SQL change).

See docs/plans/studio-build-plan.md §2.6 and the YAML format design
discussion for the broader rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from verity.governance.yaml_io.models import (
    AgentEntry,
    AgentVersionEntry,
    Bundle,
    DataConnectorEntry,
    DelegationEntry,
    InferenceConfigEntry,
    PromptAssignment,
    PromptEntry,
    PromptVersionEntry,
    SourceBindingEntry,
    TaskEntry,
    TaskVersionEntry,
    ToolAuthorization,
    ToolEntry,
    WriteTargetEntry,
)


# ── Result + error types ────────────────────────────────────────────────────


@dataclass
class ImportError:
    """One validation error. Aggregated into ImportValidationError."""
    code: str            # "dangling_reference" | "missing_required_field" | ...
    path: str            # JSON-pointer-ish path: "entities[3].versions[0].prompts[1]"
    message: str         # human-readable explanation

    def to_dict(self) -> dict:
        return {"code": self.code, "path": self.path, "message": self.message}


class ImportValidationError(Exception):
    """Raised by ``Importer.import_bundle`` when phase 1 fails.

    All errors are reported at once so the user can fix everything
    in one round-trip rather than discovering them one at a time.
    """
    def __init__(self, errors: list[ImportError]):
        self.errors = errors
        super().__init__(
            f"Bundle validation failed with {len(errors)} error(s); "
            "see .errors for the full list."
        )


@dataclass
class ImportResult:
    """Per-entity outcome from a successful import.

    Each entry is a `(kind, name)` tuple for headers/non-versioned
    entities and a `(kind, name, version_label)` triple for
    versioned ones.
    """
    headers_inserted: list[tuple[str, str]] = field(default_factory=list)
    headers_skipped: list[tuple[str, str]] = field(default_factory=list)
    versions_inserted: list[tuple[str, str, str]] = field(default_factory=list)
    versions_skipped: list[tuple[str, str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "headers_inserted": [
                {"kind": k, "name": n} for (k, n) in self.headers_inserted
            ],
            "headers_skipped": [
                {"kind": k, "name": n} for (k, n) in self.headers_skipped
            ],
            "versions_inserted": [
                {"kind": k, "name": n, "version_label": v}
                for (k, n, v) in self.versions_inserted
            ],
            "versions_skipped": [
                {"kind": k, "name": n, "version_label": v}
                for (k, n, v) in self.versions_skipped
            ],
        }


# ── Importer ────────────────────────────────────────────────────────────────


class Importer:
    """Take a Bundle and persist it to the registry.

    Stateless aside from per-call caches on ``self``. Concurrent
    imports against the same registry must use separate instances.
    """

    def __init__(self, registry):
        self.registry = registry
        # Per-call caches mapping name → DB id, populated lazily.
        # Reset at the start of each ``import_bundle`` call so a
        # second import doesn't see stale entries.
        self._inference_config_id_cache: dict[str, str] = {}
        self._tool_id_cache: dict[str, str] = {}
        self._data_connector_id_cache: dict[str, str] = {}
        self._prompt_id_cache: dict[str, str] = {}
        self._prompt_version_id_cache: dict[tuple[str, str], str] = {}
        self._task_id_cache: dict[str, str] = {}
        self._task_version_id_cache: dict[tuple[str, str], str] = {}
        self._agent_id_cache: dict[str, str] = {}
        self._agent_version_id_cache: dict[tuple[str, str], str] = {}

    # ── Public entry point ────────────────────────────────────────

    async def import_bundle(self, bundle: Bundle) -> ImportResult:
        # Reset caches per-call.
        self._reset_caches()

        # Phase 1 — validation. Collect all errors before raising.
        errors = await self._validate(bundle)
        if errors:
            raise ImportValidationError(errors)

        # Phase 2 — write.
        return await self._write(bundle)

    async def plan_import(self, bundle: Bundle) -> ImportResult:
        """Dry-run version of ``import_bundle``: report what would
        change without writing anything.

        Runs the same validation pass as ``import_bundle`` (and raises
        ``ImportValidationError`` on the same conditions), then walks
        every header and version in the bundle and asks the registry
        whether it already exists. The returned ``ImportResult`` uses
        the same field shape, but the semantics shift from "what was
        inserted/skipped" to "what would be inserted/skipped if you
        called ``import_bundle`` next".

        This drives ``verity diff`` — preview an import before
        committing to the writes.
        """
        self._reset_caches()

        errors = await self._validate(bundle)
        if errors:
            raise ImportValidationError(errors)

        result = ImportResult()
        for entry in bundle.entities:
            existing_id = await self._lookup_header_id(entry)
            if existing_id is None:
                result.headers_inserted.append((entry.kind, entry.name))
            else:
                result.headers_skipped.append((entry.kind, entry.name))

            # Versioned entries also report per-version status.
            versions = getattr(entry, "versions", None) or []
            for v in versions:
                existing_v = await self._lookup_version_id(
                    entry.kind, entry.name, v.version_label,
                )
                triple = (entry.kind, entry.name, v.version_label)
                if existing_v is None:
                    result.versions_inserted.append(triple)
                else:
                    result.versions_skipped.append(triple)

        return result

    # ── Helpers shared by import_bundle and plan_import ──────────

    async def _lookup_header_id(self, entry) -> Optional[str]:
        """Dispatch on entry.kind to the right header resolver."""
        if isinstance(entry, InferenceConfigEntry):
            return await self._resolve_inference_config_id(entry.name)
        if isinstance(entry, ToolEntry):
            return await self._resolve_tool_id(entry.name)
        if isinstance(entry, DataConnectorEntry):
            return await self._resolve_data_connector_id(entry.name)
        if isinstance(entry, PromptEntry):
            return await self._resolve_prompt_id(entry.name)
        if isinstance(entry, TaskEntry):
            return await self._resolve_task_id(entry.name)
        if isinstance(entry, AgentEntry):
            return await self._resolve_agent_id(entry.name)
        return None

    async def _lookup_version_id(
        self, kind: str, name: str, version_label: str,
    ) -> Optional[str]:
        """Dispatch on kind to the right version resolver."""
        if kind == "Prompt":
            return await self._resolve_prompt_version_id(name, version_label)
        if kind == "Task":
            return await self._resolve_task_version_id(name, version_label)
        if kind == "Agent":
            return await self._resolve_agent_version_id(name, version_label)
        return None

    # ── Cache reset ───────────────────────────────────────────────

    def _reset_caches(self) -> None:
        self._inference_config_id_cache.clear()
        self._tool_id_cache.clear()
        self._data_connector_id_cache.clear()
        self._prompt_id_cache.clear()
        self._prompt_version_id_cache.clear()
        self._task_id_cache.clear()
        self._task_version_id_cache.clear()
        self._agent_id_cache.clear()
        self._agent_version_id_cache.clear()

    # ── Phase 1: Validation ───────────────────────────────────────

    async def _validate(self, bundle: Bundle) -> list[ImportError]:
        """Walk every reference and check it resolves.

        A reference resolves if the target is either present in the
        same bundle (the cheaper check) or already in the target DB
        (the registry lookup). Validation does not write.
        """
        errors: list[ImportError] = []

        # Build name indexes for quick "is this in the bundle?" checks.
        names_in_bundle: dict[str, set[str]] = {
            "Tool": set(),
            "InferenceConfig": set(),
            "DataConnector": set(),
            "Prompt": set(),
            "Task": set(),
            "Agent": set(),
        }
        # For prompts, also track which versions are in the bundle so
        # ``prompt: foo, version: 1.0.0`` references can resolve to a
        # bundle entry rather than the DB.
        prompt_versions_in_bundle: dict[str, set[str]] = {}
        for entry in bundle.entities:
            names_in_bundle.setdefault(entry.kind, set()).add(entry.name)
            if isinstance(entry, PromptEntry):
                prompt_versions_in_bundle[entry.name] = {
                    v.version_label for v in entry.versions
                }

        # Walk each entry's references.
        for i, entry in enumerate(bundle.entities):
            base_path = f"entities[{i}]"

            if isinstance(entry, AgentEntry):
                await self._validate_agent_entry(
                    entry, base_path, names_in_bundle,
                    prompt_versions_in_bundle, errors,
                )
            elif isinstance(entry, TaskEntry):
                await self._validate_task_entry(
                    entry, base_path, names_in_bundle,
                    prompt_versions_in_bundle, errors,
                )
            # PromptEntry, ToolEntry, InferenceConfigEntry,
            # DataConnectorEntry have no outgoing references — nothing
            # to validate for them.

        return errors

    async def _validate_agent_entry(
        self, entry: AgentEntry, base_path: str,
        names_in_bundle: dict[str, set[str]],
        prompt_versions_in_bundle: dict[str, set[str]],
        errors: list[ImportError],
    ) -> None:
        for vi, v in enumerate(entry.versions):
            v_path = f"{base_path}.versions[{vi}]"
            await self._validate_version_references(
                v_path=v_path,
                inference_config=v.inference_config,
                prompts=v.prompts,
                tools=v.tools,
                targets=v.targets,
                names_in_bundle=names_in_bundle,
                prompt_versions_in_bundle=prompt_versions_in_bundle,
                errors=errors,
            )
            # Delegations — agent-only.
            for di, d in enumerate(v.delegations):
                d_path = f"{v_path}.delegations[{di}]"
                if not d.child_agent:
                    errors.append(ImportError(
                        code="missing_required_field",
                        path=f"{d_path}.child_agent",
                        message="child_agent name is required.",
                    ))
                    continue
                if not await self._agent_exists(d.child_agent, names_in_bundle):
                    errors.append(ImportError(
                        code="dangling_reference",
                        path=d_path,
                        message=(
                            f"Delegation targets agent {d.child_agent!r} "
                            "which is not in the bundle and does not exist "
                            "in the target database."
                        ),
                    ))

    async def _validate_task_entry(
        self, entry: TaskEntry, base_path: str,
        names_in_bundle: dict[str, set[str]],
        prompt_versions_in_bundle: dict[str, set[str]],
        errors: list[ImportError],
    ) -> None:
        for vi, v in enumerate(entry.versions):
            v_path = f"{base_path}.versions[{vi}]"
            await self._validate_version_references(
                v_path=v_path,
                inference_config=v.inference_config,
                prompts=v.prompts,
                tools=v.tools,
                targets=v.targets,
                names_in_bundle=names_in_bundle,
                prompt_versions_in_bundle=prompt_versions_in_bundle,
                errors=errors,
            )

    async def _validate_version_references(
        self, *, v_path: str,
        inference_config: Optional[str],
        prompts: list[PromptAssignment],
        tools: list[ToolAuthorization],
        targets: list[WriteTargetEntry],
        names_in_bundle: dict[str, set[str]],
        prompt_versions_in_bundle: dict[str, set[str]],
        errors: list[ImportError],
    ) -> None:
        """Shared validation for agent and task version entries."""
        # inference_config
        if inference_config:
            if not await self._inference_config_exists(inference_config, names_in_bundle):
                errors.append(ImportError(
                    code="dangling_reference",
                    path=f"{v_path}.inference_config",
                    message=(
                        f"References inference_config {inference_config!r} "
                        "which is not in the bundle and does not exist "
                        "in the target database."
                    ),
                ))

        # prompt assignments — both header AND version_label must resolve
        for pi, pa in enumerate(prompts):
            pa_path = f"{v_path}.prompts[{pi}]"
            if not pa.prompt or not pa.version:
                errors.append(ImportError(
                    code="missing_required_field",
                    path=pa_path,
                    message="Prompt assignment requires both 'prompt' and 'version'.",
                ))
                continue
            if not await self._prompt_version_exists(
                pa.prompt, pa.version, prompt_versions_in_bundle,
            ):
                errors.append(ImportError(
                    code="dangling_reference",
                    path=pa_path,
                    message=(
                        f"References prompt {pa.prompt!r} version {pa.version!r} "
                        "which is not in the bundle and does not exist in the "
                        "target database."
                    ),
                ))

        # tool authorizations
        for ti, ta in enumerate(tools):
            t_path = f"{v_path}.tools[{ti}]"
            if not ta.tool:
                errors.append(ImportError(
                    code="missing_required_field",
                    path=t_path,
                    message="Tool authorization requires 'tool'.",
                ))
                continue
            if not await self._tool_exists(ta.tool, names_in_bundle):
                errors.append(ImportError(
                    code="dangling_reference",
                    path=t_path,
                    message=(
                        f"References tool {ta.tool!r} which is not in the "
                        "bundle and does not exist in the target database."
                    ),
                ))

        # write_target connectors
        for wti, wt in enumerate(targets):
            wt_path = f"{v_path}.targets[{wti}]"
            if not wt.connector:
                errors.append(ImportError(
                    code="missing_required_field",
                    path=f"{wt_path}.connector",
                    message="write_target requires a connector name.",
                ))
                continue
            if not await self._data_connector_exists(wt.connector, names_in_bundle):
                errors.append(ImportError(
                    code="dangling_reference",
                    path=f"{wt_path}.connector",
                    message=(
                        f"References connector {wt.connector!r} which is not "
                        "in the bundle and does not exist in the target database."
                    ),
                ))

    # ── Existence checks (bundle first, DB fallback) ─────────────

    async def _inference_config_exists(
        self, name: str, names_in_bundle: dict[str, set[str]],
    ) -> bool:
        if name in names_in_bundle["InferenceConfig"]:
            return True
        return await self._resolve_inference_config_id(name) is not None

    async def _tool_exists(
        self, name: str, names_in_bundle: dict[str, set[str]],
    ) -> bool:
        if name in names_in_bundle["Tool"]:
            return True
        return await self._resolve_tool_id(name) is not None

    async def _data_connector_exists(
        self, name: str, names_in_bundle: dict[str, set[str]],
    ) -> bool:
        if name in names_in_bundle["DataConnector"]:
            return True
        return await self._resolve_data_connector_id(name) is not None

    async def _prompt_version_exists(
        self, prompt_name: str, version_label: str,
        prompt_versions_in_bundle: dict[str, set[str]],
    ) -> bool:
        in_bundle = prompt_versions_in_bundle.get(prompt_name, set())
        if version_label in in_bundle:
            return True
        return await self._resolve_prompt_version_id(prompt_name, version_label) is not None

    async def _agent_exists(
        self, name: str, names_in_bundle: dict[str, set[str]],
    ) -> bool:
        if name in names_in_bundle["Agent"]:
            return True
        return await self._resolve_agent_id(name) is not None

    # ── Phase 2: Write ────────────────────────────────────────────

    async def _write(self, bundle: Bundle) -> ImportResult:
        """Insert in dependency order. Existing rows are skipped.

        Order:
          1. InferenceConfig
          2. Tool
          3. DataConnector
          4. Prompt headers + versions
          5. Task headers + versions (with wiring)
          6. Agent headers (so delegation lookups succeed)
          7. Agent versions (with wiring, no delegations yet)
          8. Agent version delegations (now every parent + child exists)
        """
        result = ImportResult()

        # Bucket entities by kind.
        ic_entries = [e for e in bundle.entities if isinstance(e, InferenceConfigEntry)]
        tool_entries = [e for e in bundle.entities if isinstance(e, ToolEntry)]
        dc_entries = [e for e in bundle.entities if isinstance(e, DataConnectorEntry)]
        prompt_entries = [e for e in bundle.entities if isinstance(e, PromptEntry)]
        task_entries = [e for e in bundle.entities if isinstance(e, TaskEntry)]
        agent_entries = [e for e in bundle.entities if isinstance(e, AgentEntry)]

        for e in ic_entries:
            await self._write_inference_config(e, result)
        for e in tool_entries:
            await self._write_tool(e, result)
        for e in dc_entries:
            await self._write_data_connector(e, result)
        for e in prompt_entries:
            await self._write_prompt(e, result)
        for e in task_entries:
            await self._write_task(e, result)

        # Agents in three passes — delegations need every agent_version
        # to exist first, regardless of import order in the YAML.
        for e in agent_entries:
            await self._write_agent_header(e, result)
        for e in agent_entries:
            await self._write_agent_versions_without_delegations(e, result)
        for e in agent_entries:
            await self._write_agent_delegations(e)

        return result

    # ── Per-entity writers ────────────────────────────────────────

    async def _write_inference_config(
        self, entry: InferenceConfigEntry, result: ImportResult,
    ) -> None:
        existing_id = await self._resolve_inference_config_id(entry.name)
        if existing_id is not None:
            result.headers_skipped.append(("InferenceConfig", entry.name))
            return

        params = {
            "name": entry.name,
            "display_name": entry.display_name,
            # description and intended_use are NOT NULL in the schema.
            # The YAML format doesn't carry intended_use; default both
            # to empty string when missing so hand-written or partial
            # bundles import cleanly. (A future "strict mode" could
            # demand they be present.)
            "description": entry.description or "",
            "intended_use": "",
            "model_name": entry.model_name,
            "temperature": entry.temperature,
            "max_tokens": entry.max_tokens,
            "top_p": entry.top_p,
            "top_k": entry.top_k,
            "stop_sequences": entry.stop_sequences,
            "extended_params": (
                json.dumps(entry.extended_params)
                if entry.extended_params is not None else None
            ),
        }
        row = await self.registry.db.execute_returning(
            "insert_inference_config", params,
        )
        if row is not None:
            self._inference_config_id_cache[entry.name] = str(row["id"])
            result.headers_inserted.append(("InferenceConfig", entry.name))

    async def _write_tool(self, entry: ToolEntry, result: ImportResult) -> None:
        existing_id = await self._resolve_tool_id(entry.name)
        if existing_id is not None:
            result.headers_skipped.append(("Tool", entry.name))
            return

        params = {
            "name": entry.name,
            "display_name": entry.display_name,
            # description is NOT NULL in the schema; default to empty
            # string when the YAML omits it.
            "description": entry.description or "",
            "input_schema": json.dumps(entry.input_schema),
            "output_schema": json.dumps(entry.output_schema),
            "transport": entry.transport,
            "mcp_server_name": entry.mcp_server_name,
            "mcp_tool_name": entry.mcp_tool_name,
            "implementation_path": entry.implementation_path,
            "mock_mode_enabled": entry.mock_mode_enabled or False,
            # mock_response_key is a separate string column from
            # mock_responses (JSONB). The YAML carries mock_responses;
            # round-trip of mock_response_key is a v1 limitation.
            "mock_response_key": None,
            # data_classification is an enum (tier1_public /
            # tier2_internal / tier3_confidential / tier4_pii_restricted).
            # Use the schema's column DEFAULT so the value is always
            # valid regardless of what the YAML says (the YAML format
            # doesn't carry this field today).
            "data_classification_max": "tier3_confidential",
            "is_write_operation": entry.is_write_operation or False,
            "requires_confirmation": entry.requires_confirmation or False,
            "tags": [],
        }
        row = await self.registry.db.execute_returning("insert_tool", params)
        if row is not None:
            self._tool_id_cache[entry.name] = str(row["id"])
            result.headers_inserted.append(("Tool", entry.name))

    async def _write_data_connector(
        self, entry: DataConnectorEntry, result: ImportResult,
    ) -> None:
        existing_id = await self._resolve_data_connector_id(entry.name)
        if existing_id is not None:
            result.headers_skipped.append(("DataConnector", entry.name))
            return

        params = {
            "name": entry.name,
            "connector_type": entry.connector_type,
            "display_name": entry.display_name,
            "description": entry.description,
            "config": json.dumps(entry.config or {}),
            "owner_name": entry.owner_name,
        }
        row = await self.registry.db.execute_returning("insert_data_connector", params)
        if row is not None:
            self._data_connector_id_cache[entry.name] = str(row["id"])
            result.headers_inserted.append(("DataConnector", entry.name))

    async def _write_prompt(
        self, entry: PromptEntry, result: ImportResult,
    ) -> None:
        # Header
        prompt_id = await self._resolve_prompt_id(entry.name)
        if prompt_id is None:
            params = {
                "name": entry.name,
                "display_name": entry.display_name,
                "description": entry.description,
                # primary_entity_type / primary_entity_id wiring is
                # not part of the v1 YAML format.
                "primary_entity_type": None,
                "primary_entity_id": None,
            }
            row = await self.registry.db.execute_returning("insert_prompt", params)
            if row is not None:
                prompt_id = str(row["id"])
                self._prompt_id_cache[entry.name] = prompt_id
                result.headers_inserted.append(("Prompt", entry.name))
        else:
            result.headers_skipped.append(("Prompt", entry.name))

        if prompt_id is None:
            return

        # Versions
        for v in entry.versions:
            existing = await self._resolve_prompt_version_id(entry.name, v.version_label)
            if existing is not None:
                result.versions_skipped.append(
                    ("Prompt", entry.name, v.version_label)
                )
                continue
            major, minor, patch = _parse_version_label(v.version_label)
            params = {
                "prompt_id": prompt_id,
                "major_version": major,
                "minor_version": minor,
                "patch_version": patch,
                "content": v.content,
                # template_variables is auto-extracted from content by
                # the registry's higher-level layer; for direct insert
                # we leave it empty and the consumer can re-derive.
                "template_variables": [],
                "api_role": v.api_role,
                "governance_tier": v.governance_tier,
                # Lifecycle state is ALWAYS draft on import — even if
                # the YAML claims champion, promotion is a deliberate
                # human action (see studio-build-plan.md §2.6).
                "lifecycle_state": "draft",
                "change_summary": v.change_summary,
                "sensitivity_level": v.sensitivity_level or "high",
                "author_name": v.author_name,
                "cloned_from_version_id": None,
            }
            row = await self.registry.db.execute_returning(
                "insert_prompt_version", params,
            )
            if row is not None:
                self._prompt_version_id_cache[(entry.name, v.version_label)] = str(row["id"])
                result.versions_inserted.append(
                    ("Prompt", entry.name, v.version_label)
                )

    async def _write_task(
        self, entry: TaskEntry, result: ImportResult,
    ) -> None:
        # Header
        task_id = await self._resolve_task_id(entry.name)
        if task_id is None:
            params = {
                "name": entry.name,
                "display_name": entry.display_name,
                "description": entry.description or "",
                "capability_type": entry.capability_type,
                "purpose": entry.purpose or "",
                "domain": entry.domain or "underwriting",
                "materiality_tier": entry.materiality_tier or "low",
                "input_schema": json.dumps(entry.input_schema or {}),
                "output_schema": json.dumps(entry.output_schema or {}),
                "owner_name": entry.owner_name or "Unknown",
                "owner_email": None,
                "business_context": entry.business_context,
                "known_limitations": entry.known_limitations,
                "regulatory_notes": entry.regulatory_notes,
            }
            row = await self.registry.db.execute_returning("insert_task", params)
            if row is not None:
                task_id = str(row["id"])
                self._task_id_cache[entry.name] = task_id
                result.headers_inserted.append(("Task", entry.name))
        else:
            result.headers_skipped.append(("Task", entry.name))

        if task_id is None:
            return

        # Versions + wiring
        for v in entry.versions:
            existing = await self._resolve_task_version_id(entry.name, v.version_label)
            if existing is not None:
                result.versions_skipped.append(
                    ("Task", entry.name, v.version_label)
                )
                continue
            new_version_id = await self._insert_task_version_row(
                task_id=task_id, entry=entry, v=v,
            )
            if new_version_id is None:
                continue
            self._task_version_id_cache[(entry.name, v.version_label)] = new_version_id
            await self._write_version_wiring(
                entity_type="task",
                version_id=new_version_id,
                prompts=v.prompts,
                tools=v.tools,
                sources=v.sources,
                targets=v.targets,
            )
            result.versions_inserted.append(
                ("Task", entry.name, v.version_label)
            )

    async def _insert_task_version_row(
        self, *, task_id: str, entry: TaskEntry, v: TaskVersionEntry,
    ) -> Optional[str]:
        major, minor, patch = _parse_version_label(v.version_label)
        ic_id = (
            await self._resolve_inference_config_id(v.inference_config)
            if v.inference_config else None
        )
        params = {
            "task_id": task_id,
            "major_version": major,
            "minor_version": minor,
            "patch_version": patch,
            "lifecycle_state": "draft",        # always draft on import
            "channel": "development",          # matches draft per STATE_TO_CHANNEL
            "inference_config_id": ic_id,
            "output_schema": (
                json.dumps(v.output_schema)
                if v.output_schema is not None else None
            ),
            "mock_mode_enabled": v.mock_mode_enabled or False,
            "decision_log_detail": v.decision_log_detail or "standard",
            "developer_name": v.developer_name,
            "change_summary": v.change_summary or "Imported via YAML.",
            "change_type": v.change_type or "imported",
            "cloned_from_version_id": None,
        }
        row = await self.registry.db.execute_returning(
            "insert_task_version", params,
        )
        return str(row["id"]) if row else None

    async def _write_agent_header(
        self, entry: AgentEntry, result: ImportResult,
    ) -> None:
        agent_id = await self._resolve_agent_id(entry.name)
        if agent_id is not None:
            result.headers_skipped.append(("Agent", entry.name))
            return
        params = {
            "name": entry.name,
            "display_name": entry.display_name,
            "description": entry.description or "",
            "purpose": entry.purpose or "",
            "domain": entry.domain or "underwriting",
            "materiality_tier": entry.materiality_tier or "low",
            "owner_name": entry.owner_name or "Unknown",
            "owner_email": None,
            "business_context": entry.business_context,
            "known_limitations": entry.known_limitations,
            "regulatory_notes": entry.regulatory_notes,
        }
        row = await self.registry.db.execute_returning("insert_agent", params)
        if row is not None:
            self._agent_id_cache[entry.name] = str(row["id"])
            result.headers_inserted.append(("Agent", entry.name))

    async def _write_agent_versions_without_delegations(
        self, entry: AgentEntry, result: ImportResult,
    ) -> None:
        agent_id = await self._resolve_agent_id(entry.name)
        if agent_id is None:
            return  # header insert failed earlier; skip versions

        for v in entry.versions:
            existing = await self._resolve_agent_version_id(entry.name, v.version_label)
            if existing is not None:
                result.versions_skipped.append(
                    ("Agent", entry.name, v.version_label)
                )
                continue
            new_version_id = await self._insert_agent_version_row(
                agent_id=agent_id, entry=entry, v=v,
            )
            if new_version_id is None:
                continue
            self._agent_version_id_cache[(entry.name, v.version_label)] = new_version_id
            await self._write_version_wiring(
                entity_type="agent",
                version_id=new_version_id,
                prompts=v.prompts,
                tools=v.tools,
                sources=v.sources,
                targets=v.targets,
            )
            result.versions_inserted.append(
                ("Agent", entry.name, v.version_label)
            )

    async def _insert_agent_version_row(
        self, *, agent_id: str, entry: AgentEntry, v: AgentVersionEntry,
    ) -> Optional[str]:
        major, minor, patch = _parse_version_label(v.version_label)
        ic_id = (
            await self._resolve_inference_config_id(v.inference_config)
            if v.inference_config else None
        )
        params = {
            "agent_id": agent_id,
            "major_version": major,
            "minor_version": minor,
            "patch_version": patch,
            "lifecycle_state": "draft",
            "channel": "development",
            "inference_config_id": ic_id,
            "output_schema": (
                json.dumps(v.output_schema)
                if v.output_schema is not None else None
            ),
            "authority_thresholds": (
                json.dumps(v.authority_thresholds)
                if v.authority_thresholds is not None else "{}"
            ),
            "mock_mode_enabled": v.mock_mode_enabled or False,
            "decision_log_detail": v.decision_log_detail or "standard",
            "developer_name": v.developer_name,
            "change_summary": v.change_summary or "Imported via YAML.",
            "change_type": v.change_type or "imported",
            "cloned_from_version_id": None,
        }
        row = await self.registry.db.execute_returning(
            "insert_agent_version", params,
        )
        return str(row["id"]) if row else None

    async def _write_agent_delegations(self, entry: AgentEntry) -> None:
        """Second pass: every agent_version exists by now, so we can
        resolve both parent and child IDs."""
        for v in entry.versions:
            parent_id = await self._resolve_agent_version_id(entry.name, v.version_label)
            if parent_id is None:
                continue  # parent was skipped (already existed); skip delegations
            for d in v.delegations:
                # Resolve child to either an agent_version_id (if pinned)
                # or an agent name (if champion-tracking).
                child_version_id = None
                if d.child_version:
                    child_version_id = await self._resolve_agent_version_id(
                        d.child_agent, d.child_version,
                    )
                params = {
                    "parent_agent_version_id": parent_id,
                    "child_agent_name": d.child_agent if not d.child_version else None,
                    "child_agent_version_id": child_version_id,
                    "scope": json.dumps(d.scope or {}),
                    "authorized": d.authorized,
                    "rationale": d.rationale,
                    "notes": d.notes,
                }
                await self.registry.db.execute_returning(
                    "insert_agent_version_delegation", params,
                )

    # ── Wiring writers (called after a fresh version row is inserted) ─

    async def _write_version_wiring(
        self, *, entity_type: str, version_id: str,
        prompts: list[PromptAssignment],
        tools: list[ToolAuthorization],
        sources: list[SourceBindingEntry],
        targets: list[WriteTargetEntry],
    ) -> None:
        # Prompt assignments
        for pa in prompts:
            pv_id = await self._resolve_prompt_version_id(pa.prompt, pa.version)
            if pv_id is None:
                continue  # validation should have caught this
            params = {
                "entity_type": entity_type,
                "entity_version_id": version_id,
                "prompt_version_id": pv_id,
                "api_role": pa.api_role,
                "governance_tier": pa.governance_tier,
                "execution_order": pa.execution_order or 1,
                "is_required": pa.is_required if pa.is_required is not None else True,
                "condition_logic": (
                    json.dumps(pa.condition_logic)
                    if pa.condition_logic is not None else None
                ),
            }
            await self.registry.db.execute_returning(
                "insert_entity_prompt_assignment", params,
            )

        # Tool authorizations
        insert_query = (
            "insert_agent_version_tool" if entity_type == "agent"
            else "insert_task_version_tool"
        )
        version_id_param = (
            "agent_version_id" if entity_type == "agent"
            else "task_version_id"
        )
        for ta in tools:
            tool_id = await self._resolve_tool_id(ta.tool)
            if tool_id is None:
                continue  # validation should have caught
            params = {
                version_id_param: version_id,
                "tool_id": tool_id,
                "authorized": ta.authorized,
                "notes": ta.notes,
            }
            await self.registry.db.execute_returning(insert_query, params)

        # Source bindings (unified table, owner_kind discriminator)
        owner_kind = "agent_version" if entity_type == "agent" else "task_version"
        for sb in sources:
            params = {
                "owner_kind": owner_kind,
                "owner_id": version_id,
                "template_var": sb.template_var,
                "reference": sb.reference,
                "required": sb.required if sb.required is not None else True,
                "execution_order": sb.execution_order or 1,
                "description": sb.description,
            }
            await self.registry.db.execute_returning("insert_source_binding", params)

        # Write targets + their payload fields
        for wt in targets:
            connector_id = await self._resolve_data_connector_id(wt.connector)
            if connector_id is None:
                continue
            params = {
                "owner_kind": owner_kind,
                "owner_id": version_id,
                "name": wt.name,
                "connector_id": connector_id,
                "write_method": wt.write_method,
                "container": wt.container,
                "required": wt.required if wt.required is not None else False,
                "execution_order": wt.execution_order or 1,
                "description": wt.description,
            }
            wt_row = await self.registry.db.execute_returning("insert_write_target", params)
            if wt_row is None:
                continue
            wt_id = str(wt_row["id"])
            for pf in wt.payload_fields:
                pf_params = {
                    "write_target_id": wt_id,
                    "payload_field": pf.payload_field,
                    "reference": pf.reference,
                    "required": pf.required if pf.required is not None else True,
                    "execution_order": pf.execution_order or 1,
                    "description": pf.description,
                }
                await self.registry.db.execute_returning(
                    "insert_target_payload_field", pf_params,
                )

    # ── Name → ID resolvers (cached) ─────────────────────────────

    async def _resolve_inference_config_id(self, name: str) -> Optional[str]:
        if name in self._inference_config_id_cache:
            return self._inference_config_id_cache[name]
        row = await self.registry.db.fetch_one_raw(
            "SELECT id FROM governance.inference_config WHERE name = %(name)s",
            {"name": name},
        )
        if row:
            self._inference_config_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_tool_id(self, name: str) -> Optional[str]:
        if name in self._tool_id_cache:
            return self._tool_id_cache[name]
        row = await self.registry.db.fetch_one(
            "get_tool_by_name", {"tool_name": name},
        )
        if row:
            self._tool_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_data_connector_id(self, name: str) -> Optional[str]:
        if name in self._data_connector_id_cache:
            return self._data_connector_id_cache[name]
        row = await self.registry.db.fetch_one(
            "get_data_connector_by_name", {"name": name},
        )
        if row:
            self._data_connector_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_prompt_id(self, name: str) -> Optional[str]:
        if name in self._prompt_id_cache:
            return self._prompt_id_cache[name]
        row = await self.registry.get_prompt_by_name(name)
        if row:
            self._prompt_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_prompt_version_id(
        self, prompt_name: str, version_label: str,
    ) -> Optional[str]:
        key = (prompt_name, version_label)
        if key in self._prompt_version_id_cache:
            return self._prompt_version_id_cache[key]
        # Need both prompt_id AND version_label to query; fall back to
        # a raw lookup since there's no named query for this.
        row = await self.registry.db.fetch_one_raw(
            """
            SELECT pv.id
            FROM governance.prompt_version pv
            JOIN governance.prompt p ON p.id = pv.prompt_id
            WHERE p.name = %(prompt_name)s
              AND pv.version_label = %(version_label)s
            """,
            {"prompt_name": prompt_name, "version_label": version_label},
        )
        if row:
            self._prompt_version_id_cache[key] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_task_id(self, name: str) -> Optional[str]:
        if name in self._task_id_cache:
            return self._task_id_cache[name]
        row = await self.registry.get_task_by_name(name)
        if row:
            self._task_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_task_version_id(
        self, task_name: str, version_label: str,
    ) -> Optional[str]:
        key = (task_name, version_label)
        if key in self._task_version_id_cache:
            return self._task_version_id_cache[key]
        row = await self.registry.db.fetch_one_raw(
            """
            SELECT tv.id
            FROM governance.task_version tv
            JOIN governance.task t ON t.id = tv.task_id
            WHERE t.name = %(task_name)s
              AND tv.version_label = %(version_label)s
            """,
            {"task_name": task_name, "version_label": version_label},
        )
        if row:
            self._task_version_id_cache[key] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_agent_id(self, name: str) -> Optional[str]:
        if name in self._agent_id_cache:
            return self._agent_id_cache[name]
        row = await self.registry.get_agent_by_name(name)
        if row:
            self._agent_id_cache[name] = str(row["id"])
            return str(row["id"])
        return None

    async def _resolve_agent_version_id(
        self, agent_name: str, version_label: str,
    ) -> Optional[str]:
        key = (agent_name, version_label)
        if key in self._agent_version_id_cache:
            return self._agent_version_id_cache[key]
        row = await self.registry.db.fetch_one_raw(
            """
            SELECT av.id
            FROM governance.agent_version av
            JOIN governance.agent a ON a.id = av.agent_id
            WHERE a.name = %(agent_name)s
              AND av.version_label = %(version_label)s
            """,
            {"agent_name": agent_name, "version_label": version_label},
        )
        if row:
            self._agent_version_id_cache[key] = str(row["id"])
            return str(row["id"])
        return None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_version_label(label: str) -> tuple[int, int, int]:
    """Split 'major.minor.patch' into (major, minor, patch)."""
    parts = label.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"version_label must have exactly three dot-separated parts; "
            f"got {label!r}."
        )
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as e:
        raise ValueError(
            f"version_label parts must all be integers; got {label!r}."
        ) from e
