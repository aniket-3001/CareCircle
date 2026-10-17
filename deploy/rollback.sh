#!/bin/bash
# Put the previous version of the code back and restart the stack. Used by the deploy pipeline when the site does not answer after an update.
# It restores CODE only (the commit saved in .prev_deploy before the update). It does not restore data: that is the backups, see deploy/RESTORE.md.
# Settings can be overridden so the same script can be rehearsed on a throwaway copy (deploy/test_rollback.sh).
set -euo pipefail
DIR="${CC_DIR:-/opt/cc}"
COMPOSE_FILE="${COMPOSE_FILE:-deploy/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-deploy/.env}"
cd "$DIR"
test -s .prev_deploy || { echo "no .prev_deploy: nothing to go back to"; exit 1; }
git reset -q --hard "$(cat .prev_deploy)"
echo "code is back at $(git rev-parse --short HEAD)"
docker compose ${COMPOSE_PROJECT:+-p "$COMPOSE_PROJECT"} -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build 2>&1 | tail -5
