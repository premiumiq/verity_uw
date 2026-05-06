"""DB → Bundle export.

Two-phase BFS over the dependency graph. Phase 1 (discovery) walks
``(kind, name, version)`` triples and collects which versions of which
entities the bundle needs. Phase 2 (materialization) builds Pydantic
entries with only those versions.

**Default scoping (Mode B — "Lineage"):**

  - The starting entity (the one explicitly exported) → all versions.
    The user asked for it; they want the lineage.
  - Every other entity reached transitively → only the specific
    versions actually referenced in the bundle.
  - Prompts attached via ``entity_prompt_assignment`` → only the
    referenced ``prompt_version`` rows.
  - Tools / inference_configs / data_connectors → not versioned;
    referenced ones come along.
  - Sub-agent delegations:
      * version-pinned (``child_agent_version_id`` set) →
        include exactly that pinned child version.
      * champion-tracking (``child_agent_version_id`` NULL) →
        include the most-advanced version of the child, ranked
        ``champion > challenger > shadow > staging > candidate >
        draft > deprecated`` and tie-broken by (major, minor, patch)
        descending.

**Single-version export (Mode A — "Pinned"):**

When ``export_*(name, version=...)`` is called with a specific
version_label, only that version of the starting entity is included.
Transitive deps follow the same rules as above.

A bundle is therefore self-contained: importing it into a fresh DB
reconstructs every dependency the included versions need to run,
without dragging in unrelated history.

Slice 4A ships export. Slice 4B will add the matching Importer.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
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
    TargetPayloadFieldEntry,
    TaskEntry,
    TaskVersionEntry,
    ToolAuthorization,
    ToolEntry,
    WriteTargetEntry,
)


# Internal kind tags used in the BFS frontier. These are the same as
# the YAML ``kind`` discriminator values but we use module-private
# constants so a typo at the call site is a NameError, not a silent
# string mismatch.
_AGENT = "Agent"
_TASK = "Task"
_PROMPT = "Prompt"
_TOOL = "Tool"
_INFERENCE_CONFIG = "InferenceConfig"
_DATA_CONNECTOR = "DataConnector"

# Sentinel used in the BFS frontier for "all versions of this header"
# — only meaningful for the versioned entities (Agent / Task / Prompt).
# Header-only entities (Tool / InferenceConfig / DataConnector) carry
# this sentinel too, but for them it just means "the single row".
_ALL = "*"

# Lifecycle ranking for "most-advanced version" selection. Used when
# resolving champion-tracking delegations against an agent that has
# no row in 'champion' state — fall back to the next-best stage.
# 'deprecated' is intentionally lowest because a deprecated version
# is a retired one, not the latest in active development.
_STATE_RANK: dict[str, int] = {
    "champion":   6,
    "challenger": 5,
    "shadow":     4,
    "staging":    3,
    "candidate":  2,
    "draft":      1,
    "deprecated": 0,
}


class Exporter:
    """Read entities from the registry and produce a Bundle.

    The exporter is stateful only for the duration of one ``export_*``
    call — it carries BFS state and small per-call caches as locals on
    ``self``. Multiple concurrent exports against the same registry
    must use separate Exporter instances.
    """

    def __init__(self, registry):
        """Args:
            registry: Initialized verity.governance.registry.Registry.
                The exporter calls registry methods only — no direct
                DB access except via ``registry.db``.
        """
        self.registry = registry

        # Per-instance cache of inference_config_id → name. Populated
        # lazily; an agent with 5 versions all using the same config
        # makes one query, not five.
        self._inference_config_name_cache: dict[str, str] = {}

        # Per-instance caches of header → list of versions. Used to
        # avoid re-querying ``list_*_versions`` during discovery and
        # again during materialization.
        self._agent_versions_cache: dict[str, list[dict]] = {}
        self._task_versions_cache: dict[str, list[dict]] = {}
        self._prompt_versions_cache: dict[str, list[dict]] = {}

    # ── Public entry points ────────────────────────────────────────

    async def export_agent(
        self, name: str, *, version: Optional[str] = None,
    ) -> Bundle:
        return await self._export_starting_from(_AGENT, name, version=version)

    async def export_task(
        self, name: str, *, version: Optional[str] = None,
    ) -> Bundle:
        return await self._export_starting_from(_TASK, name, version=version)

    async def export_prompt(
        self, name: str, *, version: Optional[str] = None,
    ) -> Bundle:
        return await self._export_starting_from(_PROMPT, name, version=version)

    async def export_tool(self, name: str) -> Bundle:
        return await self._export_starting_from(_TOOL, name)

    async def export_inference_config(self, name: str) -> Bundle:
        return await self._export_starting_from(_INFERENCE_CONFIG, name)

    async def export_data_connector(self, name: str) -> Bundle:
        return await self._export_starting_from(_DATA_CONNECTOR, name)

    # ── BFS driver ─────────────────────────────────────────────────

    async def _export_starting_from(
        self, kind: str, name: str, *, version: Optional[str] = None,
    ) -> Bundle:
        """Two-phase BFS — see module docstring for the scoping rules."""
        # ── Phase 1: Discovery ─────────────────────────────────
        # Track which versions of each (kind, name) end up in the
        # bundle. ``_ALL`` is the sentinel for "all available
        # versions"; it's expanded to specific labels before being
        # marked as "needed".
        needed: dict[tuple[str, str], set[str]] = {}
        processed: set[tuple[str, str, str]] = set()
        queue: deque[tuple[str, str, str]] = deque()

        # Initial enqueue. A specific version overrides the default
        # "all versions" rule for the starting entity. Header-only
        # kinds (Tool / InferenceConfig / DataConnector) ignore the
        # version field — they're not versioned.
        if version is not None and kind in (_AGENT, _TASK, _PROMPT):
            queue.append((kind, name, version))
        else:
            queue.append((kind, name, _ALL))

        while queue:
            cur_kind, cur_name, cur_version = queue.popleft()

            # Expand "all versions" for versioned entities into
            # one frontier entry per specific version label.
            if cur_version == _ALL and cur_kind in (_AGENT, _TASK, _PROMPT):
                labels = await self._list_version_labels(cur_kind, cur_name)
                for label in labels:
                    queue.append((cur_kind, cur_name, label))
                continue

            triple = (cur_kind, cur_name, cur_version)
            if triple in processed:
                continue
            processed.add(triple)

            # Record what this triple contributes to the bundle.
            needed.setdefault((cur_kind, cur_name), set()).add(cur_version)

            # Discover deps for this specific (kind, name, version).
            deps = await self._discover_version_deps(
                cur_kind, cur_name, cur_version,
            )
            for dep in deps:
                queue.append(dep)

        # ── Phase 2: Materialization ────────────────────────────
        entities = await self._materialize(needed)

        return Bundle(
            apiVersion="studio.verity.ai/v1",
            kind="Bundle",
            exported_at=datetime.now(timezone.utc),
            exported_from=None,
            entities=entities,
        )

    # ── Discovery helpers ──────────────────────────────────────────

    async def _discover_version_deps(
        self, kind: str, name: str, version: str,
    ) -> list[tuple[str, str, str]]:
        """Return the (dep_kind, dep_name, dep_version) triples that
        this specific (kind, name, version) entry depends on.

        For non-versioned entities the dep_version is ``_ALL`` (the
        target is unique per name).
        """
        if kind == _AGENT:
            return await self._discover_agent_version_deps(name, version)
        if kind == _TASK:
            return await self._discover_task_version_deps(name, version)
        # Prompt / Tool / InferenceConfig / DataConnector have no
        # nested deps in the FK graph (yet).
        return []

    async def _discover_agent_version_deps(
        self, agent_name: str, version_label: str,
    ) -> list[tuple[str, str, str]]:
        v_row = await self._get_version_row(_AGENT, agent_name, version_label)
        if v_row is None:
            return []
        return await self._discover_version_deps_for_row(
            entity_type="agent",
            v_row=v_row,
            include_delegations=True,
        )

    async def _discover_task_version_deps(
        self, task_name: str, version_label: str,
    ) -> list[tuple[str, str, str]]:
        v_row = await self._get_version_row(_TASK, task_name, version_label)
        if v_row is None:
            return []
        return await self._discover_version_deps_for_row(
            entity_type="task",
            v_row=v_row,
            include_delegations=False,
        )

    async def _discover_version_deps_for_row(
        self, *, entity_type: str, v_row: dict, include_delegations: bool,
    ) -> list[tuple[str, str, str]]:
        """Shared discovery for agent and task versions.

        ``entity_type`` is the lowercase tag used in
        ``entity_prompt_assignment.entity_type`` ('agent' or 'task').
        ``include_delegations`` is True only for agents.
        """
        deps: list[tuple[str, str, str]] = []

        # 1. inference_config — referenced by ID, name resolved.
        ic_name = await self._resolve_inference_config_name(
            v_row.get("inference_config_id")
        )
        if ic_name:
            deps.append((_INFERENCE_CONFIG, ic_name, _ALL))

        # 2. prompts — each assignment names a specific prompt_version.
        prompt_rows = await self.registry.db.fetch_all(
            "get_entity_prompts",
            {"entity_type": entity_type, "entity_version_id": str(v_row["id"])},
        )
        for r in prompt_rows:
            pname = r.get("prompt_name")
            plabel = r.get("prompt_version_label")
            if pname and plabel:
                deps.append((_PROMPT, pname, str(plabel)))

        # 3. tools — agent vs task tables differ; same column shape.
        tool_query = "get_entity_tools" if entity_type == "agent" else "get_task_tools"
        tool_rows = await self.registry.db.fetch_all(
            tool_query,
            {"entity_version_id": str(v_row["id"])},
        )
        for r in tool_rows:
            tname = r.get("name") or r.get("tool_name")
            if tname:
                deps.append((_TOOL, tname, _ALL))

        # 4. data_connectors via write_target rows.
        owner_kind = "agent_version" if entity_type == "agent" else "task_version"
        wt_rows = await self.registry.db.fetch_all(
            "list_write_targets",
            {"owner_kind": owner_kind, "owner_id": str(v_row["id"])},
        )
        for r in wt_rows:
            cname = r.get("connector_name")
            if cname:
                deps.append((_DATA_CONNECTOR, cname, _ALL))

        # 5. delegations — only for agents.
        if include_delegations:
            del_rows = await self.registry.list_delegations_for_parent(
                parent_agent_version_id=v_row["id"],
            )
            for d in del_rows:
                child_name = d.get("effective_child_name") or d.get("child_agent_name")
                if not child_name:
                    continue

                if d.get("is_version_pinned"):
                    # Specific child version is pinned — pull just it.
                    child_label = d.get("child_version_label")
                    if child_label:
                        deps.append((_AGENT, child_name, str(child_label)))
                else:
                    # Champion-tracking — resolve to most-advanced version.
                    resolved = await self._resolve_most_advanced_version(
                        _AGENT, child_name,
                    )
                    if resolved:
                        deps.append((_AGENT, child_name, resolved))

        return deps

    # ── Cached version-list helpers ────────────────────────────────

    async def _get_agent_versions(self, name: str) -> list[dict]:
        if name in self._agent_versions_cache:
            return self._agent_versions_cache[name]
        header = await self.registry.get_agent_by_name(name)
        rows = (
            await self.registry.list_agent_versions(header["id"])
            if header else []
        )
        self._agent_versions_cache[name] = rows
        return rows

    async def _get_task_versions(self, name: str) -> list[dict]:
        if name in self._task_versions_cache:
            return self._task_versions_cache[name]
        header = await self.registry.get_task_by_name(name)
        rows = (
            await self.registry.list_task_versions(header["id"])
            if header else []
        )
        self._task_versions_cache[name] = rows
        return rows

    async def _get_prompt_versions(self, name: str) -> list[dict]:
        if name in self._prompt_versions_cache:
            return self._prompt_versions_cache[name]
        header = await self.registry.get_prompt_by_name(name)
        rows = (
            await self.registry.list_prompt_versions(header["id"])
            if header else []
        )
        self._prompt_versions_cache[name] = rows
        return rows

    async def _list_version_labels(self, kind: str, name: str) -> list[str]:
        if kind == _AGENT:
            rows = await self._get_agent_versions(name)
        elif kind == _TASK:
            rows = await self._get_task_versions(name)
        elif kind == _PROMPT:
            rows = await self._get_prompt_versions(name)
        else:
            return []
        return [str(r["version_label"]) for r in rows]

    async def _get_version_row(
        self, kind: str, name: str, label: str,
    ) -> Optional[dict]:
        """Look up a single version row by name + version_label."""
        if kind == _AGENT:
            rows = await self._get_agent_versions(name)
        elif kind == _TASK:
            rows = await self._get_task_versions(name)
        elif kind == _PROMPT:
            rows = await self._get_prompt_versions(name)
        else:
            return None
        for r in rows:
            if str(r.get("version_label")) == label:
                return r
        return None

    async def _resolve_most_advanced_version(
        self, kind: str, name: str,
    ) -> Optional[str]:
        """Pick the most-advanced version of an agent/task header.

        Order: ``champion > challenger > shadow > staging > candidate
        > draft > deprecated``. Tie-break by (major, minor, patch)
        descending.

        Used for champion-tracking sub-agent delegations when the
        target has no row in 'champion' state — the bundle still needs
        a concrete version to include, so we pick the closest thing
        the human will likely promote next.
        """
        if kind == _AGENT:
            rows = await self._get_agent_versions(name)
        elif kind == _TASK:
            rows = await self._get_task_versions(name)
        else:
            return None
        if not rows:
            return None

        ranked = sorted(
            rows,
            key=lambda r: (
                _STATE_RANK.get(_as_str(r.get("lifecycle_state")) or "", -1),
                r.get("major_version") or 0,
                r.get("minor_version") or 0,
                r.get("patch_version") or 0,
            ),
            reverse=True,
        )
        return str(ranked[0]["version_label"])

    async def _resolve_inference_config_name(self, config_id) -> Optional[str]:
        """Return the inference_config row's ``name`` (not display_name)
        given its UUID, or None if the id is missing/unknown."""
        if config_id is None:
            return None
        key = str(config_id)
        if key in self._inference_config_name_cache:
            return self._inference_config_name_cache[key]
        row = await self.registry.db.fetch_one_raw(
            "SELECT name FROM governance.inference_config WHERE id = %(id)s",
            {"id": key},
        )
        ic_name = row["name"] if row else None
        if ic_name:
            self._inference_config_name_cache[key] = ic_name
        return ic_name

    # ── Materialization ────────────────────────────────────────────

    async def _materialize(
        self, needed: dict[tuple[str, str], set[str]],
    ) -> list[Any]:
        """Build Pydantic entries from the discovery output.

        Returns entries ordered leaves-first → consumers-last so YAML
        readers see deps before the things that reference them.
        """
        bucket_inference_configs: list[InferenceConfigEntry] = []
        bucket_tools: list[ToolEntry] = []
        bucket_connectors: list[DataConnectorEntry] = []
        bucket_prompts: list[PromptEntry] = []
        bucket_tasks: list[TaskEntry] = []
        bucket_agents: list[AgentEntry] = []

        for (kind, name), version_set in needed.items():
            if kind == _INFERENCE_CONFIG:
                entry = await self._fetch_inference_config(name)
                if entry is not None:
                    bucket_inference_configs.append(entry)
            elif kind == _TOOL:
                entry = await self._fetch_tool(name)
                if entry is not None:
                    bucket_tools.append(entry)
            elif kind == _DATA_CONNECTOR:
                entry = await self._fetch_data_connector(name)
                if entry is not None:
                    bucket_connectors.append(entry)
            elif kind == _PROMPT:
                entry = await self._fetch_prompt(name, version_filter=version_set)
                if entry is not None:
                    bucket_prompts.append(entry)
            elif kind == _TASK:
                entry = await self._fetch_task(name, version_filter=version_set)
                if entry is not None:
                    bucket_tasks.append(entry)
            elif kind == _AGENT:
                entry = await self._fetch_agent(name, version_filter=version_set)
                if entry is not None:
                    bucket_agents.append(entry)

        for bucket in (
            bucket_inference_configs,
            bucket_tools,
            bucket_connectors,
            bucket_prompts,
            bucket_tasks,
            bucket_agents,
        ):
            bucket.sort(key=lambda e: e.name)

        entities: list[Any] = []
        entities.extend(bucket_inference_configs)
        entities.extend(bucket_tools)
        entities.extend(bucket_connectors)
        entities.extend(bucket_prompts)
        entities.extend(bucket_tasks)
        entities.extend(bucket_agents)
        return entities

    # ── Per-entity fetchers ────────────────────────────────────────

    async def _fetch_inference_config(self, name: str) -> Optional[InferenceConfigEntry]:
        rows = await self.registry.list_inference_configs()
        row = next((r for r in rows if r.get("name") == name), None)
        if row is None:
            return None
        return InferenceConfigEntry(
            kind="InferenceConfig",
            name=row["name"],
            display_name=row["display_name"],
            description=row.get("description"),
            model_name=row["model_name"],
            temperature=_as_float(row.get("temperature")),
            max_tokens=row.get("max_tokens"),
            top_p=_as_float(row.get("top_p")),
            top_k=row.get("top_k"),
            stop_sequences=row.get("stop_sequences"),
            extended_params=row.get("extended_params") or None,
        )

    async def _fetch_tool(self, name: str) -> Optional[ToolEntry]:
        row = await self.registry.db.fetch_one(
            "get_tool_by_name", {"tool_name": name},
        )
        if row is None:
            return None
        return ToolEntry(
            kind="Tool",
            name=row["name"],
            display_name=row["display_name"],
            description=row.get("description"),
            transport=str(row["transport"]),
            mcp_server_name=row.get("mcp_server_name"),
            mcp_tool_name=row.get("mcp_tool_name"),
            implementation_path=row.get("implementation_path"),
            input_schema=row.get("input_schema") or {},
            output_schema=row.get("output_schema") or {},
            is_write_operation=row.get("is_write_operation"),
            requires_confirmation=row.get("requires_confirmation"),
            mock_mode_enabled=row.get("mock_mode_enabled"),
            mock_responses=row.get("mock_responses"),
        )

    async def _fetch_data_connector(self, name: str) -> Optional[DataConnectorEntry]:
        row = await self.registry.db.fetch_one(
            "get_data_connector_by_name", {"name": name},
        )
        if row is None:
            return None
        return DataConnectorEntry(
            kind="DataConnector",
            name=row["name"],
            display_name=row["display_name"],
            description=row.get("description"),
            connector_type=row["connector_type"],
            config=row.get("config") or {},
            owner_name=row.get("owner_name"),
        )

    async def _fetch_prompt(
        self, name: str, *, version_filter: Optional[set[str]] = None,
    ) -> Optional[PromptEntry]:
        header = await self.registry.get_prompt_by_name(name)
        if header is None:
            return None

        version_rows = await self._get_prompt_versions(name)
        if version_filter is not None:
            version_rows = [
                v for v in version_rows
                if str(v.get("version_label")) in version_filter
            ]

        versions = [
            PromptVersionEntry(
                version_label=str(v["version_label"]),
                lifecycle_state=_as_str(v.get("lifecycle_state")),
                api_role=str(v["api_role"]),
                governance_tier=str(v["governance_tier"]),
                change_summary=v.get("change_summary") or "",
                sensitivity_level=v.get("sensitivity_level"),
                author_name=v.get("author_name"),
                content=v["content"],
            )
            for v in version_rows
        ]
        versions.sort(key=lambda v: _version_sort_key(v.version_label))

        return PromptEntry(
            kind="Prompt",
            name=header["name"],
            display_name=header["display_name"],
            description=header["description"],
            primary_entity_type=_as_str(header.get("primary_entity_type")),
            versions=versions,
        )

    async def _fetch_task(
        self, name: str, *, version_filter: Optional[set[str]] = None,
    ) -> Optional[TaskEntry]:
        header = await self.registry.get_task_by_name(name)
        if header is None:
            return None

        version_rows = await self._get_task_versions(name)
        if version_filter is not None:
            version_rows = [
                v for v in version_rows
                if str(v.get("version_label")) in version_filter
            ]

        version_entries: list[TaskVersionEntry] = []
        for v in version_rows:
            ic_name = await self._resolve_inference_config_name(
                v.get("inference_config_id")
            )
            prompts = await self._build_prompt_assignments(
                entity_type="task", version_id=v["id"],
            )
            tools = await self._build_task_tool_authorizations(v["id"])
            sources = await self._build_source_bindings("task_version", v["id"])
            targets = await self._build_write_targets("task_version", v["id"])
            version_entries.append(
                TaskVersionEntry(
                    version_label=str(v["version_label"]),
                    lifecycle_state=_as_str(v.get("lifecycle_state")),
                    change_summary=v.get("change_summary"),
                    change_type=v.get("change_type"),
                    developer_name=v.get("developer_name"),
                    inference_config=ic_name,
                    output_schema=v.get("output_schema"),
                    mock_mode_enabled=v.get("mock_mode_enabled"),
                    decision_log_detail=v.get("decision_log_detail"),
                    prompts=prompts,
                    tools=tools,
                    sources=sources,
                    targets=targets,
                )
            )
        version_entries.sort(key=lambda v: _version_sort_key(v.version_label))

        return TaskEntry(
            kind="Task",
            name=header["name"],
            display_name=header["display_name"],
            description=header.get("description"),
            capability_type=str(header["capability_type"]),
            purpose=header.get("purpose"),
            domain=header.get("domain"),
            materiality_tier=_as_str(header.get("materiality_tier")),
            owner_name=header.get("owner_name"),
            business_context=header.get("business_context"),
            known_limitations=header.get("known_limitations"),
            regulatory_notes=header.get("regulatory_notes"),
            input_schema=header.get("input_schema"),
            output_schema=header.get("output_schema"),
            versions=version_entries,
        )

    async def _fetch_agent(
        self, name: str, *, version_filter: Optional[set[str]] = None,
    ) -> Optional[AgentEntry]:
        header = await self.registry.get_agent_by_name(name)
        if header is None:
            return None

        version_rows = await self._get_agent_versions(name)
        if version_filter is not None:
            version_rows = [
                v for v in version_rows
                if str(v.get("version_label")) in version_filter
            ]

        version_entries: list[AgentVersionEntry] = []
        for v in version_rows:
            ic_name = await self._resolve_inference_config_name(
                v.get("inference_config_id")
            )
            prompts = await self._build_prompt_assignments(
                entity_type="agent", version_id=v["id"],
            )
            tools = await self._build_agent_tool_authorizations(v["id"])
            sources = await self._build_source_bindings("agent_version", v["id"])
            targets = await self._build_write_targets("agent_version", v["id"])
            delegations = await self._build_delegations(v["id"])
            version_entries.append(
                AgentVersionEntry(
                    version_label=str(v["version_label"]),
                    lifecycle_state=_as_str(v.get("lifecycle_state")),
                    change_summary=v.get("change_summary"),
                    change_type=v.get("change_type"),
                    developer_name=v.get("developer_name"),
                    inference_config=ic_name,
                    output_schema=v.get("output_schema"),
                    authority_thresholds=v.get("authority_thresholds") or None,
                    mock_mode_enabled=v.get("mock_mode_enabled"),
                    decision_log_detail=v.get("decision_log_detail"),
                    limitations_this_version=v.get("limitations_this_version"),
                    prompts=prompts,
                    tools=tools,
                    sources=sources,
                    targets=targets,
                    delegations=delegations,
                )
            )
        version_entries.sort(key=lambda v: _version_sort_key(v.version_label))

        return AgentEntry(
            kind="Agent",
            name=header["name"],
            display_name=header["display_name"],
            description=header.get("description"),
            purpose=header.get("purpose"),
            domain=header.get("domain"),
            materiality_tier=_as_str(header.get("materiality_tier")),
            owner_name=header.get("owner_name"),
            business_context=header.get("business_context"),
            known_limitations=header.get("known_limitations"),
            regulatory_notes=header.get("regulatory_notes"),
            versions=version_entries,
        )

    # ── Per-version wiring builders (no dep tracking — that's done
    #    in the discovery phase) ─────────────────────────────────────

    async def _build_prompt_assignments(
        self, *, entity_type: str, version_id,
    ) -> list[PromptAssignment]:
        rows = await self.registry.db.fetch_all(
            "get_entity_prompts",
            {"entity_type": entity_type, "entity_version_id": str(version_id)},
        )
        assignments: list[PromptAssignment] = []
        for r in rows:
            prompt_name = r.get("prompt_name")
            version_label = r.get("prompt_version_label")
            if not prompt_name or not version_label:
                continue
            assignments.append(
                PromptAssignment(
                    prompt=prompt_name,
                    version=str(version_label),
                    api_role=_as_str(r.get("api_role")),
                    governance_tier=_as_str(r.get("governance_tier")),
                    execution_order=r.get("execution_order"),
                    is_required=r.get("is_required"),
                    condition_logic=r.get("condition_logic") or None,
                )
            )
        assignments.sort(
            key=lambda a: ((a.execution_order or 0), a.prompt, a.version)
        )
        return assignments

    async def _build_agent_tool_authorizations(
        self, version_id,
    ) -> list[ToolAuthorization]:
        rows = await self.registry.db.fetch_all(
            "get_entity_tools",
            {"entity_version_id": str(version_id)},
        )
        return self._build_tool_authorizations_from_rows(rows)

    async def _build_task_tool_authorizations(
        self, version_id,
    ) -> list[ToolAuthorization]:
        rows = await self.registry.db.fetch_all(
            "get_task_tools",
            {"entity_version_id": str(version_id)},
        )
        return self._build_tool_authorizations_from_rows(rows)

    @staticmethod
    def _build_tool_authorizations_from_rows(
        rows: list[dict],
    ) -> list[ToolAuthorization]:
        authorizations: list[ToolAuthorization] = []
        for r in rows:
            tool_name = r.get("name") or r.get("tool_name")
            if not tool_name:
                continue
            authorizations.append(
                ToolAuthorization(
                    tool=tool_name,
                    authorized=bool(r.get("authorized", True)),
                    notes=r.get("notes"),
                )
            )
        authorizations.sort(key=lambda a: a.tool)
        return authorizations

    async def _build_source_bindings(
        self, owner_kind: str, owner_id,
    ) -> list[SourceBindingEntry]:
        rows = await self.registry.db.fetch_all(
            "list_source_bindings",
            {"owner_kind": owner_kind, "owner_id": str(owner_id)},
        )
        bindings = [
            SourceBindingEntry(
                template_var=r["template_var"],
                reference=r["reference"],
                required=r.get("required"),
                execution_order=r.get("execution_order"),
                description=r.get("description"),
            )
            for r in rows
        ]
        bindings.sort(
            key=lambda b: ((b.execution_order or 0), b.template_var)
        )
        # Reference strings can mention connector names via the
        # ``fetch:<connector>/<method>(...)`` pattern. We don't parse
        # those here — connector deps are picked up via the
        # write_target FK path during discovery. (Future work: parse
        # fetch:* in discovery and enqueue the connector.)
        return bindings

    async def _build_write_targets(
        self, owner_kind: str, owner_id,
    ) -> list[WriteTargetEntry]:
        rows = await self.registry.db.fetch_all(
            "list_write_targets",
            {"owner_kind": owner_kind, "owner_id": str(owner_id)},
        )
        targets: list[WriteTargetEntry] = []
        for r in rows:
            payload_field_rows = await self.registry.db.fetch_all(
                "list_target_payload_fields",
                {"write_target_id": str(r["id"])},
            )
            payload_fields = [
                TargetPayloadFieldEntry(
                    payload_field=p["payload_field"],
                    reference=p["reference"],
                    required=p.get("required"),
                    execution_order=p.get("execution_order"),
                    description=p.get("description"),
                )
                for p in payload_field_rows
            ]
            payload_fields.sort(
                key=lambda p: ((p.execution_order or 0), p.payload_field)
            )

            targets.append(
                WriteTargetEntry(
                    name=r["name"],
                    connector=r.get("connector_name") or "",
                    write_method=r["write_method"],
                    container=r.get("container"),
                    required=r.get("required"),
                    execution_order=r.get("execution_order"),
                    description=r.get("description"),
                    payload_fields=payload_fields,
                )
            )

        targets.sort(key=lambda t: ((t.execution_order or 0), t.name))
        return targets

    async def _build_delegations(
        self, agent_version_id,
    ) -> list[DelegationEntry]:
        rows = await self.registry.list_delegations_for_parent(
            parent_agent_version_id=agent_version_id,
        )
        delegations: list[DelegationEntry] = []
        for r in rows:
            child_name = r.get("effective_child_name") or r.get("child_agent_name")
            if not child_name:
                continue
            child_version = (
                r.get("child_version_label")
                if r.get("is_version_pinned")
                else None
            )
            delegations.append(
                DelegationEntry(
                    child_agent=child_name,
                    child_version=str(child_version) if child_version else None,
                    scope=r.get("scope") or {},
                    authorized=bool(r.get("authorized", True)),
                    rationale=r.get("rationale"),
                    notes=r.get("notes"),
                )
            )
        delegations.sort(key=lambda d: (d.child_agent, d.child_version or ""))
        return delegations


# ── Module-level coercion helpers ───────────────────────────────────


def _as_str(value: Any) -> Optional[str]:
    """Coerce enums (and similar) to their string value for YAML."""
    if value is None:
        return None
    raw = getattr(value, "value", None)
    if isinstance(raw, str):
        return raw
    return str(value)


def _as_float(value: Any) -> Optional[float]:
    """Decimal / numeric columns come back as Decimal — coerce to float."""
    if value is None:
        return None
    return float(value)


def _version_sort_key(label: str) -> tuple[int, ...]:
    """Sort versions by (major, minor, patch) — not lexically — so
    "10.0.0" sorts after "9.0.0", as humans expect."""
    parts: list[int] = []
    for chunk in label.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            # Non-numeric segment → sort it as 0; better than crashing.
            parts.append(0)
    return tuple(parts)
