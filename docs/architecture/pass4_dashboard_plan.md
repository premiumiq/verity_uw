# Pass 4: Dashboard Redesign with ECharts

## Design

The dashboard has 3 horizontal zones, top to bottom:

### Zone 1: Overview Cards (3 groups)

Three groups of compact, clickable stat cards:

**Registry:** Applications, Pipelines, Agents, Tasks, Prompts, Configs, Tools
**Observability:** Decisions, Pipeline Runs, Overrides
**Governance:** Open Incidents, Pending Approvals, Entities in Review

### Zone 2: Registry Explorer (Slicers + Charts)

**Left side — Asset Slicers (scrollable lists, cross-filterable):**
Five side-by-side narrow columns:
- Pipelines (list of pipeline display names)
- Agents (list of agent display names)
- Tasks (list of task display names)
- Tools (list of tool display names)
- Prompts (list of prompt display names)

Clicking an item in any list filters the other lists to show only related assets. For example: click "Triage Agent" → Tools list filters to show only tools authorized for that agent, Prompts list filters to show only prompts assigned to it.

An Application dropdown above the slicers filters everything by application.

**Right side — Asset Counts by Type (bar chart):**
Horizontal bar chart showing count of each asset type. Reacts to slicer selections — when filtered, shows only the filtered counts.

**Future Enhancement (documented, not built now):**
Network diagram where assets and applications are shape/color-coded nodes. Dense when unfiltered, meaningful when sliced. Deferred to Pass 5 — requires graph layout algorithm (ECharts has a `graph` chart type that supports this).

### Zone 3: Observability (Charts + Mini Table)

**Left — Decisions Over Time (stacked bar):**
- X: date, Y: count, stacked by status (complete/failed)
- Reacts to slicer selections from Zone 2

**Right — Decisions by Entity (horizontal bar):**
- Shows which agents/tasks are most active
- Clickable — clicking a bar filters the mini table below

**Bottom — Latest Decisions (mini table):**
- Last 10 decisions, compact
- Filtered by slicer selections and entity bar chart clicks
- Columns: Entity, Type, Step, Status, Duration, When

All charts and the mini table react to the same filter state. Clicking an agent in the slicer, or clicking a bar in the entity chart, or selecting an application — all update the same filtered view.

### Zone 4: Governance Summary

**Stats row:** Versions promoted, Override rate, Test pass rate
**Version Activity chart:** Approvals over time (shows governance cadence)

---

## Implementation Approach

### Client-Side Filtering with ECharts

All data is loaded once on page load (passed as JSON from the route). ECharts charts and the mini table are rendered client-side. A small JavaScript controller manages filter state:

```javascript
// Filter state — updated by slicers, application dropdown, and chart clicks
let filterState = {
    application: null,     // Selected application name or null (all)
    selectedAssets: {       // Selected asset names by type
        pipeline: null,
        agent: null,
        task: null,
        tool: null,
        prompt: null,
    },
    selectedEntity: null,   // Clicked entity from horizontal bar chart
};
```

When filter state changes, all charts and the mini table re-render with filtered data. This is fast because all data is already in the browser — no server round-trips.

### Data Passed from Python to Template

```python
# In dashboard route:
return _render(templates, request, "dashboard.html",
    # Cards
    counts=counts,
    governance_stats=governance_stats,
    # Slicer data (all assets with their relationships)
    registry_data=registry_data,  # JSON: {agents: [...], tasks: [...], tools: [...], prompts: [...], pipelines: [...]}
    # Chart data
    decisions_by_date=decisions_by_date,    # JSON: [{date, status, count}, ...]
    decisions_by_entity=decisions_by_entity, # JSON: [{entity_name, entity_type, count}, ...]
    recent_decisions=recent_decisions,       # JSON: last 10 decisions
    # Relationship map (for cross-filtering slicers)
    asset_relationships=asset_relationships, # JSON: {agent_id: {tools: [...], prompts: [...]}, ...}
)
```

### SQL Queries Needed

```sql
-- Decisions by date and status (stacked bar chart)
dashboard_decisions_by_date

-- Decisions by entity display name (horizontal bar)
dashboard_decisions_by_entity

-- Governance stats (approval count, pipeline runs, entities in review)
dashboard_governance_stats

-- Asset relationships (which agent uses which tools/prompts — for slicer cross-filtering)
-- Reuses existing: get_agent_prompts_and_tools_summary, get_task_prompts_summary, get_entity_applications
```

---

## Files Modified

| File | Change |
|---|---|
| `verity/src/verity/db/queries/reporting.sql` | Add dashboard chart queries |
| `verity/src/verity/web/routes.py` | Dashboard route loads chart data, passes as JSON |
| `verity/src/verity/web/templates/dashboard.html` | Full rewrite: 4 zones, ECharts, slicers, mini table |
| `verity/src/verity/models/reporting.py` | Add governance stats fields |

## ECharts Integration

- CDN in dashboard.html only: `https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`
- Each chart in a clearly commented `<script>` block
- Data passed via `{{ data | tojson }}` in a `<script>` tag
- Responsive: `window.addEventListener('resize', ...)`
- Small font sizes for chart labels to maximize real estate

## Future: Network Diagram (Pass 5)

**Deferred requirement:** Interactive network diagram showing assets and applications as nodes.
- Nodes: shape-coded by type (agent=hexagon, task=square, tool=wrench, prompt=paragraph, pipeline=arrow, application=rectangle)
- Color-coded by type
- Labels: short machine name on node, display name on mouse-over tooltip
- Edges: relationships (agent→tool authorization, agent→prompt assignment, application→entity mapping)
- Dense when unfiltered — meaningful when filtered by application or slicer
- ECharts `graph` chart type supports force-directed and circular layouts
- Requires building a relationship adjacency list from existing data

---

## Verification

1. Dashboard loads with all 3 card groups showing correct counts
2. Application dropdown filters all slicers
3. Clicking an agent in the slicer filters tools and prompts to show only related ones
4. Asset counts bar chart updates with slicer selections
5. Decisions over time chart shows stacked bars by status
6. Decisions by entity chart shows horizontal bars
7. Clicking a bar in entity chart filters the mini table
8. Mini table shows last 10 decisions, filtered by all active filters
9. All charts resize properly on window resize
