#!/bin/bash
# Rehearse deploy/rollback.sh on a throwaway copy, with no connection to the live site: a small stack of the same shape (a git checkout, a compose file, a
# saved previous commit), a good version, a deliberately broken update, then the rollback. Needs docker and git. Prints PASS or FAIL.
#   bash deploy/test_rollback.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
W="$(mktemp -d)"
PORT="${PORT:-18081}"
export COMPOSE_PROJECT="ccrollbackdrill"
cleanup() { docker compose -p "$COMPOSE_PROJECT" -f "$W/deploy/docker-compose.prod.yml" --env-file "$W/deploy/.env" down -v >/dev/null 2>&1; rm -rf "$W"; }
trap cleanup EXIT
mkdir -p "$W/deploy" && cd "$W" && git init -q && git config user.email drill@example.invalid && git config user.name drill
cp "$HERE/rollback.sh" deploy/rollback.sh
echo "PORT=$PORT" > deploy/.env
cat > deploy/docker-compose.prod.yml <<YML
services:
  web:
    image: python:3.12-slim
    command: ["sh", "-c", "echo version-1 > index.html && exec python -m http.server 8000"]
    ports: ["\${PORT}:8000"]
YML
git add -A && git commit -qm good
GOOD_SHA="$(git rev-parse HEAD)"
up() { docker compose -p "$COMPOSE_PROJECT" -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build >/dev/null 2>&1; }
answers() { for _ in $(seq 1 20); do curl -sf -m 2 "localhost:$PORT/index.html" 2>/dev/null && return 0; sleep 1; done; return 1; }
up; got="$(answers | tr -d "
 ")"; [ "$got" = "version-1" ] || { echo "FAIL: the good version did not start (got: $got)"; docker compose -p "$COMPOSE_PROJECT" -f deploy/docker-compose.prod.yml --env-file deploy/.env ps -a 2>&1 | tail -3; docker compose -p "$COMPOSE_PROJECT" -f deploy/docker-compose.prod.yml --env-file deploy/.env logs 2>&1 | tail -5; exit 1; }
echo "$GOOD_SHA" > .prev_deploy                                                # what the pipeline saves before an update
sed -i 's#command: .*#command: ["sh", "-c", "echo version-2 > index.html; exit 3"]#' deploy/docker-compose.prod.yml
git add -A && git commit -qm broken       # the bad update
up
if answers >/dev/null; then echo "FAIL: the broken update was still answering, so the drill proves nothing"; exit 1; fi
echo "the broken update is down, as intended; rolling back"
CC_DIR="$W" bash deploy/rollback.sh
GOT="$(answers || true)"
if [ "$GOT" = "version-1" ] && [ "$(git rev-parse HEAD)" = "$GOOD_SHA" ]; then echo "PASS: rolled back to $(git rev-parse --short HEAD) and the old version answers"; else echo "FAIL: after the rollback the site said '${GOT}'"; exit 1; fi
