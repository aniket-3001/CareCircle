#!/bin/bash
# Snapshot FalkorDB and copy it to S3 (private bucket, 14-day expiry). Runs from cron on the instance; uses the instance role, no keys.
# Restore: see deploy/RESTORE.md
set -euo pipefail
BUCKET="${BACKUP_BUCKET:-carecircle-backups-536697259243}"
DB="${DB_CONTAINER:-deploy-falkordb-1}"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

before="$(docker exec "$DB" redis-cli LASTSAVE)"
docker exec "$DB" redis-cli BGSAVE >/dev/null
for _ in $(seq 1 60); do                        # wait for the snapshot to finish
  [ "$(docker exec "$DB" redis-cli LASTSAVE)" != "$before" ] && break
  sleep 2
done
docker cp "$DB:/var/lib/falkordb/data/dump.rdb" "$TMP/dump.rdb"
docker run --rm --network host -v "$TMP:/b" amazon/aws-cli s3 cp /b/dump.rdb "s3://$BUCKET/falkordb/$STAMP.rdb" --only-show-errors
echo "backup ok $STAMP $(stat -c %s "$TMP/dump.rdb") bytes"
