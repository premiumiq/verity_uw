#!/bin/bash
# Stop the Verity development stack. Data volumes are preserved so a
# subsequent `./scripts/start.sh` resumes with the same data.
#
# To wipe data (postgres + minio): docker compose down -v

set -euo pipefail

cd "$(dirname "$0")/.."

docker compose down

echo ""
echo "stopped. data volumes preserved."
echo "to wipe data: docker compose down -v"
