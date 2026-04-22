"""Decisions — re-export shim with a combined reader+writer facade.

The Decisions module was split in Phase 2c of the registry/runtime split:
- Read methods + record_override   -> verity.governance.decisions.DecisionsReader
- log_decision (the runtime write) -> verity.runtime.decisions_writer.DecisionsWriter

During the transition, existing code that does `from verity.core.decisions
import Decisions` and then calls BOTH `log_decision` and reader methods on
the same object continues to work: this file defines `Decisions` as a
subclass that inherits both halves. Consumers are migrated to the two
split classes in Phase 2d (client.py split) and Phase 2e (external callers).
"""

from verity.governance.decisions import DecisionsReader
from verity.runtime.decisions_writer import DecisionsWriter


class Decisions(DecisionsReader, DecisionsWriter):
    """Legacy unified Decisions interface.

    Inherits:
      - Audit-trail reads, list/get/count, record_override (DecisionsReader)
      - log_decision (DecisionsWriter)

    Both parents define __init__(self, db) with the same semantics
    (just sets self.db), so multiple inheritance works without any custom
    __init__ here.
    """
    pass


__all__ = ["Decisions", "DecisionsReader", "DecisionsWriter"]
