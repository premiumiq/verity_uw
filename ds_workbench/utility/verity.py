"""VerityAPI — sync HTTP client for the Verity /api/v1/* REST surface.

Single source of truth for "how does a notebook talk to Verity." Every
notebook does:

    from utility.verity import VerityAPI
    v = VerityAPI()              # reads VERITY_API_URL from env
    agents = v.list_agents()     # convenience wrapper
    config = v.call("get_agent_config", path_params={"name": "triage_agent"})

Why sync. Notebook cells run serially, so there's no concurrency win
from async, and VSCode's Jupyter integration sometimes fights with
top-level-await. Sync `httpx.Client` works identically in Docker
JupyterLab and VSCode.

Env-based URL routing. `VERITY_API_URL` is read at construction time:
    - VSCode on host:       http://localhost:8000   (default)
    - Docker JupyterLab:    http://verity:8000      (set via compose)

Errors. Every HTTP >= 400 raises `VerityAPIError`, carrying the status
code, the parsed JSON detail (if present), and the originating
endpoint name. Notebook cells that hit an expected 4xx (e.g. checking
if an app is registered via a 404) should catch this explicitly.
"""

import os
from typing import Any, Optional
from uuid import UUID

import httpx


DEFAULT_APPLICATION = "ds_workbench"
DEFAULT_TIMEOUT_SECONDS = 60


class VerityAPIError(Exception):
    """Raised when a Verity API call returns a non-2xx response.

    Carries the status code, the parsed JSON detail (FastAPI's
    `{"detail": "..."}` shape when possible), and the original
    endpoint name — all useful for readable error messages in
    notebook output cells.
    """

    def __init__(self, status: int, detail: Any, endpoint: str, url: str):
        self.status = status
        self.detail = detail
        self.endpoint = endpoint
        self.url = url
        super().__init__(
            f"[{status}] {endpoint} → {url}\n  detail: {detail!r}"
        )


# ── Endpoint registry ────────────────────────────────────────
# Logical name → (HTTP method, URL template). Templates use Python
# str.format placeholders (`{name}`, `{version_id}`) which `call()`
# substitutes. Not exhaustive — common operations are listed here,
# and the escape hatch `call_path(method, path, ...)` covers the
# long tail. Keep this dict alphabetized within each bucket.

ENDPOINTS: dict[str, tuple[str, str]] = {
    # Applications
    "register_application":  ("POST",   "/api/v1/applications"),
    "list_applications":     ("GET",    "/api/v1/applications"),
    "get_application":       ("GET",    "/api/v1/applications/{name}"),
    "unregister_application":("DELETE", "/api/v1/applications/{name}"),
    "list_app_entities":     ("GET",    "/api/v1/applications/{name}/entities"),
    "map_entity":            ("POST",   "/api/v1/applications/{name}/entities"),
    "unmap_entity":          ("DELETE", "/api/v1/applications/{name}/entities/{entity_type}/{entity_id}"),
    "get_app_activity":      ("GET",    "/api/v1/applications/{name}/activity"),
    "purge_app_activity":    ("DELETE", "/api/v1/applications/{name}/activity"),
    "create_execution_context": ("POST", "/api/v1/execution-contexts"),

    # Registry — catalog lists
    "list_agents":           ("GET",    "/api/v1/agents"),
    "list_tasks":            ("GET",    "/api/v1/tasks"),
    "list_prompts":          ("GET",    "/api/v1/prompts"),
    "list_tools":            ("GET",    "/api/v1/tools"),
    "list_pipelines":        ("GET",    "/api/v1/pipelines"),
    "list_inference_configs":("GET",    "/api/v1/inference-configs"),
    "list_mcp_servers":      ("GET",    "/api/v1/mcp-servers"),

    # Registry — resolve + version listings
    "get_agent_config":      ("GET",    "/api/v1/agents/{name}/config"),
    "get_task_config":       ("GET",    "/api/v1/tasks/{name}/config"),
    "list_agent_versions":   ("GET",    "/api/v1/agents/{name}/versions"),
    "list_task_versions":    ("GET",    "/api/v1/tasks/{name}/versions"),
    "list_prompt_versions":  ("GET",    "/api/v1/prompts/{name}/versions"),
    "list_pipeline_versions":("GET",    "/api/v1/pipelines/{name}/versions"),

    # Authoring — headers
    "register_agent":        ("POST",   "/api/v1/agents"),
    "register_task":         ("POST",   "/api/v1/tasks"),
    "register_prompt":       ("POST",   "/api/v1/prompts"),
    "register_tool":         ("POST",   "/api/v1/tools"),
    "register_pipeline":     ("POST",   "/api/v1/pipelines"),
    "register_inference_config": ("POST", "/api/v1/inference-configs"),
    "register_mcp_server":   ("POST",   "/api/v1/mcp-servers"),

    # Authoring — versions + associations
    "register_agent_version":    ("POST", "/api/v1/agents/{name}/versions"),
    "register_task_version":     ("POST", "/api/v1/tasks/{name}/versions"),
    "register_prompt_version":   ("POST", "/api/v1/prompts/{name}/versions"),
    "register_pipeline_version": ("POST", "/api/v1/pipelines/{name}/versions"),
    "assign_prompt_to_agent":    ("POST", "/api/v1/agents/{name}/versions/{version_id}/prompts"),
    "assign_prompt_to_task":     ("POST", "/api/v1/tasks/{name}/versions/{version_id}/prompts"),
    "authorize_agent_tool":      ("POST", "/api/v1/agents/{name}/versions/{version_id}/tools"),
    "authorize_task_tool":       ("POST", "/api/v1/tasks/{name}/versions/{version_id}/tools"),
    "register_delegation":       ("POST", "/api/v1/agents/{name}/versions/{version_id}/delegations"),

    # Draft-edit + clone
    "update_agent_version":    ("PATCH",  "/api/v1/agents/{name}/versions/{version_id}"),
    "update_task_version":     ("PATCH",  "/api/v1/tasks/{name}/versions/{version_id}"),
    "update_prompt_version":   ("PATCH",  "/api/v1/prompts/{name}/versions/{version_id}"),
    "update_pipeline_version": ("PATCH",  "/api/v1/pipelines/{name}/versions/{version_id}"),
    "delete_agent_version":    ("DELETE", "/api/v1/agents/{name}/versions/{version_id}"),
    "delete_task_version":     ("DELETE", "/api/v1/tasks/{name}/versions/{version_id}"),
    "delete_prompt_version":   ("DELETE", "/api/v1/prompts/{name}/versions/{version_id}"),
    "delete_pipeline_version": ("DELETE", "/api/v1/pipelines/{name}/versions/{version_id}"),
    "replace_agent_prompts":   ("PUT",    "/api/v1/agents/{name}/versions/{version_id}/prompts"),
    "replace_agent_tools":     ("PUT",    "/api/v1/agents/{name}/versions/{version_id}/tools"),
    "replace_agent_delegations":("PUT",   "/api/v1/agents/{name}/versions/{version_id}/delegations"),
    "replace_task_prompts":    ("PUT",    "/api/v1/tasks/{name}/versions/{version_id}/prompts"),
    "replace_task_tools":      ("PUT",    "/api/v1/tasks/{name}/versions/{version_id}/tools"),
    "clone_agent_version":     ("POST",   "/api/v1/agents/{name}/versions/{source_version_id}/clone"),
    "clone_task_version":      ("POST",   "/api/v1/tasks/{name}/versions/{source_version_id}/clone"),
    "clone_prompt_version":    ("POST",   "/api/v1/prompts/{name}/versions/{source_version_id}/clone"),
    "clone_pipeline_version":  ("POST",   "/api/v1/pipelines/{name}/versions/{source_version_id}/clone"),

    # Lifecycle
    "promote":               ("POST",   "/api/v1/lifecycle/promote"),
    "rollback":              ("POST",   "/api/v1/lifecycle/rollback"),
    "list_approvals":        ("GET",    "/api/v1/lifecycle/approvals"),

    # Runtime
    "run_agent":             ("POST",   "/api/v1/runtime/agents/{name}/run"),
    "run_task":              ("POST",   "/api/v1/runtime/tasks/{name}/run"),
    "run_pipeline":          ("POST",   "/api/v1/runtime/pipelines/{name}/run"),

    # Decisions + audit
    "list_decisions":        ("GET",    "/api/v1/decisions"),
    "get_decision":          ("GET",    "/api/v1/decisions/{decision_id}"),
    "audit_trail_by_context":("GET",    "/api/v1/audit-trail/context/{execution_context_id}"),
    "audit_trail_by_run":    ("GET",    "/api/v1/audit-trail/run/{workflow_run_id}"),
    "record_override":       ("POST",   "/api/v1/overrides"),

    # Reporting
    "dashboard_counts":      ("GET",    "/api/v1/reporting/dashboard-counts"),
    "inventory_agents":      ("GET",    "/api/v1/reporting/agents"),
    "inventory_tasks":       ("GET",    "/api/v1/reporting/tasks"),
}


class VerityAPI:
    """Sync HTTP client for the Verity REST API.

    Constructed without arguments uses `VERITY_API_URL` from the
    environment, defaulting to `http://localhost:8000`. Explicit
    `base_url=` overrides both.

    Use `with VerityAPI() as v:` to auto-close the httpx pool, or call
    `.close()` explicitly. Notebook cells typically just create one
    instance at the top and reuse it everywhere.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        application: str = DEFAULT_APPLICATION,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        verbose: bool = False,
    ):
        self.base_url = (
            base_url or os.environ.get("VERITY_API_URL", "http://localhost:8000")
        ).rstrip("/")
        self.application = application
        self.verbose = verbose
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ── Lifecycle ─────────────────────────────────────────────

    def __enter__(self) -> "VerityAPI":
        return self

    def __exit__(self, *exc_info):
        self.close()

    def close(self) -> None:
        self._client.close()

    # ── Core dispatch ─────────────────────────────────────────

    def call(
        self,
        endpoint: str,
        path_params: Optional[dict[str, Any]] = None,
        query: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Invoke a registered endpoint by logical name.

        - path_params: fills the `{placeholder}`s in the URL template.
        - query: translates to the URL query string (None values stripped).
        - json: the JSON body for POST / PUT / PATCH.

        Returns the parsed JSON response (dict or list). Raises
        VerityAPIError on any non-2xx status.
        """
        if endpoint not in ENDPOINTS:
            raise KeyError(
                f"Unknown endpoint {endpoint!r}. Add it to ENDPOINTS "
                "or use call_path(method, path, ...) for one-off calls."
            )
        method, template = ENDPOINTS[endpoint]
        path = template.format(**(path_params or {}))
        return self.call_path(method, path, endpoint=endpoint, query=query, json=json)

    def call_path(
        self,
        method: str,
        path: str,
        endpoint: str = "(adhoc)",
        query: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Escape hatch for endpoints not in ENDPOINTS. Takes an
        already-formatted path (e.g. `/api/v1/foo/bar`)."""
        clean_query = {k: v for k, v in (query or {}).items() if v is not None}
        if self.verbose:
            print(f"→ {method} {path}  query={clean_query or ''}  body={'yes' if json else 'no'}")
        resp = self._client.request(
            method=method,
            url=path,
            params=clean_query or None,
            json=json,
        )
        if self.verbose:
            print(f"← {resp.status_code}  {resp.headers.get('content-type', '?')}")
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise VerityAPIError(
                status=resp.status_code,
                detail=detail,
                endpoint=endpoint,
                url=str(resp.request.url),
            )
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ── Convenience wrappers ──────────────────────────────────
    # Thin sugar over `call()` for the operations notebooks exercise
    # most. Keeps notebook cells readable; the generic `call` is
    # always available for anything else.

    # Applications
    def register_application(self, name: str, display_name: str, description: str = "") -> dict:
        return self.call(
            "register_application",
            json={"name": name, "display_name": display_name, "description": description},
        )

    def list_applications(self) -> list[dict]:
        return self.call("list_applications")

    def get_application(self, name: str) -> dict:
        return self.call("get_application", path_params={"name": name})

    def ensure_application_registered(
        self, name: Optional[str] = None, display_name: Optional[str] = None,
        description: str = "",
    ) -> dict:
        """Idempotent — if the app already exists, return it; else register.

        Always returns the full application row (id, name, display_name,
        description, created_at). The POST response itself only carries
        `id` and `created_at` (from the SQL RETURNING clause), so after
        a fresh register we re-fetch via GET so callers see a uniform
        shape regardless of which branch ran.

        Default name is the VerityAPI's configured application
        (`ds_workbench` unless overridden at construction).
        """
        name = name or self.application
        display_name = display_name or name.replace("_", " ").title()
        try:
            return self.get_application(name)
        except VerityAPIError as exc:
            if exc.status != 404:
                raise
            self.register_application(name, display_name, description)
            return self.get_application(name)

    def unregister_application(self, name: Optional[str] = None) -> dict:
        name = name or self.application
        return self.call("unregister_application", path_params={"name": name})

    def get_app_activity(self, name: Optional[str] = None) -> dict:
        name = name or self.application
        return self.call("get_app_activity", path_params={"name": name})

    def purge_app_activity(self, name: Optional[str] = None) -> dict:
        name = name or self.application
        return self.call("purge_app_activity", path_params={"name": name})

    def list_app_entities(
        self, name: Optional[str] = None, entity_type: Optional[str] = None,
    ) -> list[dict]:
        name = name or self.application
        return self.call(
            "list_app_entities",
            path_params={"name": name},
            query={"entity_type": entity_type},
        )

    def map_entity(
        self, entity_type: str, entity_id: str, app_name: Optional[str] = None,
    ) -> dict:
        app_name = app_name or self.application
        return self.call(
            "map_entity",
            path_params={"name": app_name},
            json={"entity_type": entity_type, "entity_id": entity_id},
        )

    # Registry
    def list_agents(self) -> list[dict]:
        return self.call("list_agents")

    def list_tasks(self) -> list[dict]:
        return self.call("list_tasks")

    def list_pipelines(self) -> list[dict]:
        return self.call("list_pipelines")

    def get_agent_config(
        self, name: str, version_id: Optional[UUID] = None,
        effective_date: Optional[str] = None,
    ) -> dict:
        return self.call(
            "get_agent_config",
            path_params={"name": name},
            query={
                "version_id": str(version_id) if version_id else None,
                "effective_date": effective_date,
            },
        )

    def list_agent_versions(self, name: str) -> list[dict]:
        return self.call("list_agent_versions", path_params={"name": name})

    # Runtime
    # Each convenience wrapper defaults `application=self.application`, so
    # every run launched from the workbench attributes its decision log to
    # our app rather than the Verity server's default identity. Pass
    # `application=None` explicitly to opt out.
    def run_agent(
        self, name: str, context: dict, channel: str = "production",
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = ...,
    ) -> dict:
        body = {"context": context, "channel": channel}
        if execution_context_id:
            body["execution_context_id"] = str(execution_context_id)
        body["application"] = self.application if application is ... else application
        return self.call("run_agent", path_params={"name": name}, json=body)

    def run_task(
        self, name: str, input_data: dict, channel: str = "production",
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = ...,
    ) -> dict:
        body = {"input_data": input_data, "channel": channel}
        if execution_context_id:
            body["execution_context_id"] = str(execution_context_id)
        body["application"] = self.application if application is ... else application
        return self.call("run_task", path_params={"name": name}, json=body)

    def run_pipeline(
        self, name: str, context: dict, channel: str = "production",
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = ...,
    ) -> dict:
        body = {"context": context, "channel": channel}
        if execution_context_id:
            body["execution_context_id"] = str(execution_context_id)
        body["application"] = self.application if application is ... else application
        return self.call("run_pipeline", path_params={"name": name}, json=body)

    # Decisions + audit
    def get_decision(self, decision_id: str) -> dict:
        return self.call("get_decision", path_params={"decision_id": str(decision_id)})

    def list_decisions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self.call("list_decisions", query={"limit": limit, "offset": offset})

    def audit_trail_by_context(self, execution_context_id: str) -> list[dict]:
        return self.call(
            "audit_trail_by_context",
            path_params={"execution_context_id": str(execution_context_id)},
        )

    def audit_trail_by_run(self, workflow_run_id: str) -> list[dict]:
        return self.call(
            "audit_trail_by_run",
            path_params={"workflow_run_id": str(workflow_run_id)},
        )

    # Lifecycle
    def promote(
        self, entity_type: str, entity_version_id: str,
        target_state: str, approver_name: str, rationale: str,
        **evidence_flags,
    ) -> dict:
        body = {
            "entity_type": entity_type,
            "entity_version_id": str(entity_version_id),
            "target_state": target_state,
            "approver_name": approver_name,
            "rationale": rationale,
            **evidence_flags,
        }
        return self.call("promote", json=body)

    # Clone-and-edit shortcut
    def clone_agent_version(
        self, name: str, source_version_id: str,
        new_version_label: str, change_summary: str = "Cloned",
        developer_name: Optional[str] = None,
    ) -> dict:
        body = {"new_version_label": new_version_label, "change_summary": change_summary}
        if developer_name:
            body["developer_name"] = developer_name
        return self.call(
            "clone_agent_version",
            path_params={"name": name, "source_version_id": str(source_version_id)},
            json=body,
        )

    # Reporting
    def dashboard_counts(self) -> dict:
        return self.call("dashboard_counts")

    def inventory_agents(self) -> list[dict]:
        return self.call("inventory_agents")
