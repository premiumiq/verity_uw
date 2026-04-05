"""Verity Reporting — model inventory, dashboard, compliance reports.

These reports are what CIOs and regulators see. The model inventory
covers both agents and tasks as governed entities under SR 11-7.
"""

from verity.db.connection import Database
from verity.models.reporting import DashboardCounts, ModelInventoryAgent, ModelInventoryTask


class Reporting:
    """Model inventory, dashboard counts, override analysis."""

    def __init__(self, db: Database):
        self.db = db

    async def dashboard_counts(self) -> DashboardCounts:
        """Get counts for the Verity admin dashboard."""
        row = await self.db.fetch_one("dashboard_counts")
        if not row:
            return DashboardCounts()
        return DashboardCounts(**row)

    async def model_inventory_agents(self) -> list[ModelInventoryAgent]:
        """Get the model inventory report for all champion agents."""
        rows = await self.db.fetch_all("model_inventory_agents")
        return [ModelInventoryAgent(**_normalize_numeric(r)) for r in rows]

    async def model_inventory_tasks(self) -> list[ModelInventoryTask]:
        """Get the model inventory report for all champion tasks."""
        rows = await self.db.fetch_all("model_inventory_tasks")
        return [ModelInventoryTask(**_normalize_numeric(r)) for r in rows]

    async def override_analysis(self, days: int = 90) -> list[dict]:
        """Get override analysis grouped by reason code."""
        return await self.db.fetch_all("override_analysis", {"days": days})


def _normalize_numeric(row: dict) -> dict:
    """Convert Decimal values to float for Pydantic compatibility."""
    result = {}
    for k, v in row.items():
        if hasattr(v, "as_integer_ratio"):  # Decimal, float
            result[k] = float(v)
        else:
            result[k] = v
    return result
