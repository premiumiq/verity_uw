"""Runtime plane internal facade.

Wires the execution-side modules together over one Database connection.
Takes governance-side Registry and Testing instances as read-only
dependencies — this is the concrete manifestation of the version-pinning
invariant: the runtime reads resolved configs from governance and writes
decisions back through DecisionsWriter.

Why both this class and the existing ExecutionEngine/PipelineExecutor/etc.?
The existing classes handle specific execution responsibilities. This
class is a thin wiring layer that holds one of each and exposes them as
attributes. Consumer apps (UW) and the runtime REST API (Phase 5) both
use this single entry point.
"""

from verity.db.connection import Database
from verity.governance.registry import Registry
from verity.governance.testing_meta import Testing
from verity.runtime.decisions_writer import DecisionsWriter
from verity.runtime.engine import ExecutionEngine
from verity.runtime.mcp_client import MCPClient
from verity.runtime.pipeline import PipelineExecutor
from verity.runtime.test_runner import TestRunner
from verity.runtime.validation_runner import ValidationRunner


class Runtime:
    """Holds one instance each of the runtime modules, sharing a DB pool.

    Constructor takes:
      - db                : shared Database (for decisions writer + validation runner)
      - registry          : governance-side Registry (for config resolution at execution time)
      - testing           : governance-side Testing (for test suite + GT metadata reads)
      - anthropic_api_key : Claude API key (empty string for pure-mock mode)
      - application       : app identifier recorded in every decision

    Runtime-plane capabilities exposed via its attributes:
      - decisions_writer   : log_decision() — one write per execution
      - mcp_client         : MCPClient — shared pool of MCP server connections for
                             tools registered with transport='mcp_*' (Phase 4c)
      - execution          : ExecutionEngine (agentic loop; holds the mcp_client
                             so tool dispatch can route by transport)
      - pipeline_executor  : multi-step orchestrator with dependency resolution
      - test_runner        : execute test suites against entity versions
      - validation_runner  : run entity versions against ground truth datasets
    """

    def __init__(
        self,
        db: Database,
        registry: Registry,
        testing: Testing,
        anthropic_api_key: str = "",
        application: str = "default",
    ):
        self.db = db
        self.application = application
        self.decisions_writer = DecisionsWriter(db)
        # One MCP connection pool per Runtime. Empty until a tool with
        # transport='mcp_*' dispatches and the engine lazily opens the
        # referenced mcp_server. Closed via Runtime.close() on shutdown.
        self.mcp_client = MCPClient()
        # ExecutionEngine takes a decisions-shaped object — it only calls
        # `.log_decision(...)` on it, so DecisionsWriter is a drop-in replacement
        # for the legacy unified Decisions class.
        self.execution = ExecutionEngine(
            registry=registry,
            decisions=self.decisions_writer,
            anthropic_api_key=anthropic_api_key,
            application=application,
            mcp_client=self.mcp_client,
        )
        self.pipeline_executor = PipelineExecutor(
            registry=registry,
            execution_engine=self.execution,
        )
        self.test_runner = TestRunner(
            registry=registry,
            execution_engine=self.execution,
            testing=testing,
        )
        self.validation_runner = ValidationRunner(
            registry=registry,
            execution_engine=self.execution,
            testing=testing,
            db=db,
        )

    async def close(self) -> None:
        """Release runtime-owned resources. Called by Verity.close()."""
        await self.mcp_client.close_all()


__all__ = ["Runtime"]
