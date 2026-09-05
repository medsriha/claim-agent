#!/bin/sh
set -e

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
    python -m tools.seed_precedents --if-empty ||
        echo "Demo data could not be written. Starting the service anyway."
fi

exec "$@"
