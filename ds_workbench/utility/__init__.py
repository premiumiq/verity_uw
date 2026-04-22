"""Reusable helpers for the Data Science Workbench notebooks.

Notebooks import from here, never duplicate logic. Three modules:

    from utility.verity import VerityAPI                     # HTTP client
    from utility.html import (                               # Verity-UI-styled output
        inject_style, badge, render_list, render_detail, render_cards,
    )
    from utility.visualizations import (                     # charts + diagrams
        as_dataframe, dashboard_counts_bar, decision_tree,
        agent_composition_diagram, version_lineage_graph,
        application_relationship_graph, lifecycle_state_heatmap,
        decision_timeline,
    )

Everything is sync — httpx.Client (not AsyncClient) avoids event-loop
hassles in VSCode's Jupyter integration and gives identical behaviour
in the Docker JupyterLab kernel.
"""
