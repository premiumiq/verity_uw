"""Governance plane internal facade.

Wires the five governance-side modules together over one Database
connection. Instantiated by the consumer client (verity.client.inprocess)
and by the governance REST API (Phase 4) — both pass in a shared Database.

This is a thin wiring class, not a replacement for the flat Verity facade
that consuming apps use. Its purpose is to give the runtime plane and the
HTTP API a single typed entry point into governance.
"""

from verity.db.connection import Database
from verity.governance.decisions import DecisionsReader
from verity.governance.lifecycle import Lifecycle
from verity.governance.models import Models
from verity.governance.quotas import Quotas
from verity.governance.registry import Registry
from verity.governance.reporting import Reporting
from verity.governance.testing_meta import Testing


class GovernanceCoordinator:
    """Holds one instance each of the governance modules, sharing a DB pool.

    Governance-plane capabilities exposed via its attributes:
      - registry          : agent/task/prompt/tool/pipeline/inference_config reads + writes
      - lifecycle         : 7-state promotion, rollback, approval records
      - decisions_reader  : audit trail reads + human override record
      - reporting         : dashboard counts, model inventory, override analysis
      - testing           : test suite + ground truth metadata reads (NOT execution)
      - models            : model catalog, SCD-2 price history, invocation log + usage rollups
    """

    def __init__(self, db: Database, application: str = "default"):
        self.db = db
        self.application = application
        self.registry = Registry(db)
        self.lifecycle = Lifecycle(db)
        self.decisions_reader = DecisionsReader(db)
        self.reporting = Reporting(db)
        self.testing = Testing(db)
        self.models = Models(db)
        self.quotas = Quotas(db)


__all__ = ["GovernanceCoordinator"]
