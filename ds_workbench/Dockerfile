# Data Science Workbench image.
#
# Extends the upstream `jupyter/scipy-notebook` (which already carries
# pandas / numpy / matplotlib / scikit-learn / scipy) with exactly the
# workbench-specific additions we need:
#   - the system `graphviz` binary that the Python `graphviz` wrapper
#     shells out to (dot/neato). Without this, graphviz.Digraph.render()
#     raises ExecutableNotFound.
#   - our requirements.txt (httpx, plotly, graphviz, networkx, ipycytoscape).
#
# Building this at image time keeps first-run container startup fast —
# no pip install at every `docker compose up`.

FROM jupyter/scipy-notebook:latest

# System packages — run as root, switch back to jovyan afterward.
# `graphviz` gives us the dot/neato executables. We also throw in
# `curl` so our health-check step in compose and the README's
# connectivity demo work without further installs.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends graphviz curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
USER ${NB_UID}

# Python deps — pip install is scoped to the jovyan user so no sudo
# hackery needed at runtime.
COPY --chown=${NB_UID}:${NB_GID} requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
