#!/bin/bash
# Run the Verity test suite from the repo root.
#
# Verifies postgres is reachable, activates .venv, then runs pytest.
# Extra arguments pass through to pytest:
#
#   ./scripts/test.sh                  # run everything
#   ./scripts/test.sh verity/tests/unit/   # subset by path
#   ./scripts/test.sh -k registry      # subset by name pattern
#   ./scripts/test.sh -m integration   # subset by marker
#   ./scripts/test.sh --preserve-test-db  # keep test DBs for inspection

set -euo pipefail

cd "$(dirname "$0")/.."

# 1. Postgres has to be up — the integration fixture needs it to clone
#    a per-test database from the template.
if ! docker exec verity_postgres pg_isready -U verityuser -d postgres -q 2>/dev/null; then
    echo "ERROR: verity_postgres is not running or not reachable."
    echo "Start the stack first: ./scripts/start.sh"
    exit 1
fi

# 2. The repo's .venv must exist. We don't auto-create it — the developer
#    should know what Python they're installing into.
if [ ! -f .venv/bin/activate ]; then
    echo "ERROR: .venv not found at repo root."
    echo "Create it with:"
    echo "  python3.12 -m venv .venv"
    echo "  source .venv/bin/activate"
    echo "  pip install -e verity/[dev,runtime]"
    exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# 3. Run pytest. Pass through any extra args from the command line.
pytest "$@"
