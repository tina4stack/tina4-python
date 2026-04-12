#!/usr/bin/env bash
# Build and push tina4stack/tina4-python Docker images after a release.
#
# Usage:
#   ./docker-build.sh          # builds :v3 and :v3.10.98 (reads version from source)
#   ./docker-build.sh 3.10.99  # override version tag
#
# Prerequisites:
#   docker login  (must be authenticated to tina4stack org on Docker Hub)

set -euo pipefail

REPO="tina4stack/tina4-python"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve version from argument or source
if [ -n "${1:-}" ]; then
    VERSION="$1"
else
    VERSION=$(grep '__version__' "$SCRIPT_DIR/tina4_python/__init__.py" | sed 's/.*"\(.*\)".*/\1/')
fi

if [ -z "$VERSION" ]; then
    echo "ERROR: Could not determine version. Pass it as an argument: ./docker-build.sh 3.10.98"
    exit 1
fi

echo "Building $REPO"
echo "  Tags: v3, v$VERSION"
echo ""

# Build with both tags
docker build \
    -t "$REPO:v3" \
    -t "$REPO:v$VERSION" \
    "$SCRIPT_DIR"

echo ""
echo "Pushing $REPO:v3 ..."
docker push "$REPO:v3"

echo "Pushing $REPO:v$VERSION ..."
docker push "$REPO:v$VERSION"

echo ""
echo "Done. Images pushed:"
echo "  $REPO:v3"
echo "  $REPO:v$VERSION"
