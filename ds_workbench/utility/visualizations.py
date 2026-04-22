"""Visualization helpers for DS Workbench notebooks.

Every helper takes a plain dict / list-of-dicts shape (the raw JSON
the API returns) and produces a displayable object:

    - DataFrame / Styler    for tables
    - plotly.graph_objects.Figure for interactive charts
    - graphviz.Digraph      for flow and relationship diagrams

Notebooks can pass these directly to `display()` or let the last
cell's return value auto-render.

Design principles:
    - Never reach into the API client here. Helpers receive already-
      fetched data; they don't make network calls.
    - Be defensive about missing keys — production decision logs have
      slightly different shapes depending on run_purpose / channel.
"""

from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from graphviz import Digraph


# ── Tables ───────────────────────────────────────────────────

def as_dataframe(records: list[dict]) -> pd.DataFrame:
    """Normalize a list of dicts to a DataFrame. Returns an empty
    frame (rather than raising) when `records` is empty or None —
    notebooks often pass results straight from the API which may
    legitimately be empty on a fresh install."""
    return pd.DataFrame(records or [])


def catalog_table(
    records: list[dict],
    columns: Optional[list[str]] = None,
    max_rows: int = 50,
) -> pd.DataFrame:
    """Styled pandas DataFrame for list-of-entity views (agents,
    tasks, prompts, decisions, ...).

    `columns` optionally narrows to a subset in display order;
    missing columns are filled with None rather than KeyError so
    the helper stays forgiving when schemas evolve.
    """
    df = as_dataframe(records)
    if df.empty:
        return df
    if columns:
        present = [c for c in columns if c in df.columns]
        df = df[present]
    return df.head(max_rows)


# ── Charts ───────────────────────────────────────────────────

def dashboard_counts_bar(counts: dict) -> go.Figure:
    """Horizontal bar chart of Verity dashboard counts (agents,
    tasks, prompts, configs, tools, pipelines, decisions, overrides,
    open incidents). Fed directly from `VerityAPI.dashboard_counts()`.
    """
    # Preserve a stable, human-friendly ordering instead of dict order.
    order = [
        "agent_count", "task_count", "pipeline_count",
        "prompt_count", "tool_count", "config_count",
        "total_decisions", "total_overrides", "open_incidents",
    ]
    rows = [(k.replace("_", " "), counts.get(k, 0)) for k in order if k in counts]
    labels, values = zip(*rows) if rows else ([], [])
    fig = go.Figure(go.Bar(
        x=list(values), y=list(labels), orientation="h",
        text=list(values), textposition="outside",
    ))
    fig.update_layout(
        title="Verity — registry + activity",
        xaxis_title="count",
        yaxis=dict(autorange="reversed"),  # most-important first
        height=max(320, 40 * len(labels)),
        margin=dict(l=160, r=80, t=60, b=40),
    )
    return fig


def decision_timeline(audit_trail: list[dict]) -> go.Figure:
    """Plotly timeline of decisions within an execution_context.

    Expects AuditTrailEntry rows (each with `decision_id`,
    `entity_name`, `status`, and a timestamp). Missing timestamps
    fall back to row order on the x-axis so a partial or still-
    running trail still renders.
    """
    if not audit_trail:
        return go.Figure().update_layout(
            title="No decisions in this context yet",
            height=200,
        )
    df = pd.DataFrame(audit_trail)
    # Pick a timestamp column, tolerating naming variation.
    time_col = next(
        (c for c in ("created_at", "start_time", "timestamp") if c in df.columns),
        None,
    )
    if time_col is None:
        df["__order__"] = range(len(df))
        time_col = "__order__"
    fig = px.scatter(
        df,
        x=time_col,
        y=df.get("entity_name", df.get("decision_id")),
        color=df.get("status", "status").fillna("unknown") if "status" in df.columns else None,
        hover_data=[c for c in df.columns if c != time_col],
        title="Audit trail — decisions over time",
    )
    fig.update_traces(marker=dict(size=12))
    fig.update_layout(height=max(240, 40 * len(df)), margin=dict(l=80, r=40, t=60, b=60))
    return fig


# ── Flow & relationship diagrams ─────────────────────────────

def decision_tree(audit_trail: list[dict], highlight_id: Optional[str] = None) -> Digraph:
    """Graphviz tree of a parent→sub decision chain — showcases
    sub-agent delegation (FC-1). Each decision becomes a node;
    `parent_decision_id` supplies the edges.

    Accepts AuditTrailEntry rows or DecisionLog rows (both carry
    `id` and `parent_decision_id`). Root nodes (no parent) are
    styled slightly bigger; the optional `highlight_id` gets a
    distinct colour so notebooks can flag the decision they just
    produced.
    """
    g = Digraph("decision_tree")
    g.attr(rankdir="TB", nodesep="0.3", ranksep="0.5")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="10")

    for d in audit_trail or []:
        did = str(d.get("decision_id") or d.get("id") or "?")
        label_parts = [d.get("entity_name") or d.get("step_name") or "?"]
        if d.get("status") and d["status"] != "complete":
            label_parts.append(f"[{d['status']}]")
        label = "\\n".join(label_parts)
        fill = (
            "#fde68a" if did == str(highlight_id) else
            "#fecaca" if d.get("status") == "failed" else
            "#dbeafe"
        )
        g.node(did, label=label, fillcolor=fill)

        parent = d.get("parent_decision_id")
        if parent:
            g.edge(str(parent), did)
    return g


def agent_composition_diagram(agent_config: dict) -> Digraph:
    """Block diagram of a resolved agent config: header + inference
    config + prompts + tools + delegations. Driven directly from
    `GET /api/v1/agents/{name}/config`.

    Reads keys defensively so it still renders on partial configs
    (drafts without tool authorizations, configs from older versions
    missing delegation arrays, etc.).
    """
    g = Digraph("agent_composition")
    g.attr(rankdir="LR", nodesep="0.3", ranksep="0.6")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="10")

    name = agent_config.get("agent_name") or agent_config.get("name", "agent")
    version = agent_config.get("version_label", "?")
    g.node("agent", label=f"{name}\\nv{version}", fillcolor="#dbeafe")

    # Inference config
    ic = agent_config.get("inference_config") or {}
    if ic:
        g.node(
            "cfg",
            label=f"config: {ic.get('name', '?')}\\n{ic.get('model_name', '')}\\n"
                  f"T={ic.get('temperature', '?')}  max_tok={ic.get('max_tokens', '?')}",
            fillcolor="#fef3c7",
        )
        g.edge("agent", "cfg", label="uses")

    # Prompts
    prompts = agent_config.get("prompts") or []
    if prompts:
        with g.subgraph(name="cluster_prompts") as c:
            c.attr(label="prompts", style="dashed", color="#94a3b8")
            for i, p in enumerate(prompts):
                nid = f"p{i}"
                c.node(
                    nid,
                    label=f"{p.get('prompt_name', '?')}\\nv{p.get('version_number', '?')}\\n"
                          f"{p.get('api_role', '?')}",
                    fillcolor="#e0e7ff",
                )
                g.edge("agent", nid, label=f"#{p.get('execution_order', '?')}")

    # Tools
    tools = agent_config.get("tools") or []
    if tools:
        with g.subgraph(name="cluster_tools") as c:
            c.attr(label="tools", style="dashed", color="#94a3b8")
            for i, t in enumerate(tools):
                nid = f"t{i}"
                transport = t.get("transport", "python_inprocess")
                c.node(
                    nid,
                    label=f"{t.get('tool_name', '?')}\\n[{transport}]",
                    fillcolor="#dcfce7" if t.get("authorized", True) else "#fee2e2",
                )
                g.edge("agent", nid, label="calls")

    return g


def application_relationship_graph(
    app_name: str, entities: list[dict],
    entity_names: Optional[dict[str, str]] = None,
) -> Digraph:
    """App → mapped-entities diagram. `entities` is the shape
    returned by GET /applications/{name}/entities. Optional
    `entity_names` maps `entity_id` → display name so nodes show
    "triage_agent" instead of a bare UUID (callers do the name
    lookup from list_agents/tasks/...)."""
    g = Digraph("application_relationships")
    g.attr(rankdir="LR", nodesep="0.3", ranksep="0.5")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="10")

    g.node("app", label=f"application\\n{app_name}", fillcolor="#fde68a")

    by_type: dict[str, list[dict]] = {}
    for e in entities or []:
        by_type.setdefault(e.get("entity_type", "?"), []).append(e)

    fill_by_type = {
        "agent":    "#dbeafe",
        "task":     "#dcfce7",
        "prompt":   "#e0e7ff",
        "tool":     "#fef3c7",
        "pipeline": "#fce7f3",
    }
    for etype, rows in sorted(by_type.items()):
        with g.subgraph(name=f"cluster_{etype}") as c:
            c.attr(label=etype, style="dashed", color="#94a3b8")
            for e in rows:
                eid = str(e.get("entity_id"))
                label = (entity_names or {}).get(eid, eid[:8])
                c.node(f"{etype}-{eid[:8]}", label=label, fillcolor=fill_by_type.get(etype, "#e2e8f0"))
                g.edge("app", f"{etype}-{eid[:8]}")
    return g


def version_lineage_graph(versions: list[dict]) -> Digraph:
    """Lineage graph of a named entity's versions (from list_*_versions).

    Edges follow `cloned_from_version_id`, so the graph shows both
    linear evolution and branching clones. Nodes are coloured by
    lifecycle_state so a quick glance distinguishes drafts from
    champions.
    """
    g = Digraph("version_lineage")
    g.attr(rankdir="TB", nodesep="0.25", ranksep="0.4")
    g.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="10")

    state_color = {
        "draft":       "#e2e8f0",
        "candidate":   "#fef3c7",
        "staging":     "#fde68a",
        "shadow":      "#bae6fd",
        "challenger":  "#fecaca",
        "champion":    "#bbf7d0",
        "deprecated":  "#d1d5db",
    }
    for v in versions or []:
        vid = str(v["id"])
        state = v.get("lifecycle_state", "?")
        g.node(
            vid,
            label=f"{v.get('version_label', v.get('version_number', '?'))}\\n[{state}]",
            fillcolor=state_color.get(state, "#e2e8f0"),
        )
        source = v.get("cloned_from_version_id")
        if source:
            g.edge(str(source), vid, label="clone", style="dashed", color="#6366f1")
    return g


# ── Cross-entity summary views ───────────────────────────────

def lifecycle_state_heatmap(entity_versions: list[dict]) -> go.Figure:
    """Entity (rows) × lifecycle_state (columns) count heatmap.

    Rows come from `entity_name` (or `name`); columns are the seven
    canonical lifecycle states. Empty cells show 0. Useful overview
    of "which agents have a champion already, and which are still
    in draft" at a glance.
    """
    states = ["draft", "candidate", "staging", "shadow", "challenger", "champion", "deprecated"]
    if not entity_versions:
        return go.Figure().update_layout(title="No entities", height=200)

    df = pd.DataFrame(entity_versions)
    name_col = next((c for c in ("agent_name", "task_name", "name") if c in df.columns), None)
    if name_col is None:
        return go.Figure().update_layout(title="No name column found", height=200)
    state_col = "lifecycle_state" if "lifecycle_state" in df.columns else "state"
    pivot = (
        df.groupby([name_col, state_col]).size().unstack(fill_value=0)
        .reindex(columns=states, fill_value=0)
    )
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values, x=pivot.columns, y=pivot.index,
        colorscale="Blues", showscale=True, text=pivot.values, texttemplate="%{text}",
    ))
    fig.update_layout(
        title="Lifecycle state distribution",
        xaxis_title="state", yaxis_title="entity",
        height=max(240, 32 * len(pivot)),
        margin=dict(l=140, r=40, t=60, b=40),
    )
    return fig
