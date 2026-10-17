#!/bin/bash
# Build deploy/.env from AWS Systems Manager Parameter Store (/carecircle/prod/*). Runs on the instance, as root, with the instance role (no keys).
#
#   the store of record is Parameter Store: secrets are SecureString (encrypted with the AWS-managed key), the rest are plain String; nothing is in the repository.
#   to rotate a value:  aws ssm put-parameter --name /carecircle/prod/GRAPHMEM_ADMIN_KEY --type SecureString --overwrite --value '...'   then deploy (or run this script and
#                       `docker compose ... up -d`).
#   safety: the new file replaces the old one only if the store answered and the file has every setting the stack needs; otherwise the file already on disk is kept and the
#           deploy carries on with it (a store outage must not stop a deploy).
#   what this does not do: the values are still in the container environment while it runs, and in the 0600 file on the instance. The gain is one place to rotate and audit,
#           and a rebuilt instance that gets its settings from the store instead of from someone's memory.
set -uo pipefail
PREFIX="${SSM_PREFIX:-/carecircle/prod}"
TARGET="${ENV_FILE:-/opt/cc/deploy/.env}"
REGION="${AWS_REGION:-us-east-1}"
REQUIRED="DOMAIN GRAPHMEM_ADMIN_KEY GRAPHMEM_RO_PASSWORD"

TMP="$(mktemp)"; OUT="$(mktemp)"
trap 'rm -f "$TMP" "$OUT"' EXIT

if ! docker run --rm --network host -e AWS_DEFAULT_REGION="$REGION" amazon/aws-cli ssm get-parameters-by-path --path "$PREFIX" --with-decryption \
      --query "Parameters[].[Name,Value]" --output text > "$OUT" 2>/dev/null || [ ! -s "$OUT" ]; then
  echo "render_env: Parameter Store did not answer; keeping $TARGET as it is" >&2
  exit 0
fi

# one KEY=value line per parameter (the value is everything after the first tab)
awk -F'\t' -v p="$PREFIX/" '{k=$1; sub("^" p, "", k); v=$0; sub(/^[^\t]*\t/, "", v); print k "=" v}' "$OUT" | sort > "$TMP"

for k in $REQUIRED; do
  grep -q "^$k=." "$TMP" || { echo "render_env: $k missing in the store; keeping $TARGET as it is" >&2; exit 0; }
done

install -m 600 -o root -g root "$TMP" "$TARGET.new" && mv "$TARGET.new" "$TARGET"
echo "render_env: wrote $(wc -l < "$TARGET") settings to $TARGET from $PREFIX"
