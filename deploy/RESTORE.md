# Backups and recovery

**What runs:** every 6 hours the instance snapshots FalkorDB (`BGSAVE`) and copies `dump.rdb` to a private S3 bucket
(`carecircle-backups-<account>/falkordb/<UTC time>.rdb`, deleted after 14 days). CloudWatch alarms reboot the instance if its OS stops
answering and recover it onto new hardware if the AWS host fails; Docker restarts the containers on boot (`restart: unless-stopped`).
A scheduled GitHub workflow (`uptime.yml`) checks `/healthz` every 15 minutes and fails, which emails the repo owner, if the site is down.

**Restore a snapshot**
```bash
# on the instance (AWS Systems Manager Session Manager or send-command)
cd /opt/cc
aws s3 ls s3://carecircle-backups-<account>/falkordb/ | tail            # pick a file (use: docker run --rm --network host amazon/aws-cli ...)
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env stop api falkordb
docker run --rm -v deploy_falkor-data:/data -v /tmp:/b amazon/aws-cli s3 cp s3://<bucket>/falkordb/<file>.rdb /data/dump.rdb
docker run --rm -v deploy_falkor-data:/data alpine rm -f /data/appendonlydir -r      # let FalkorDB load the snapshot, not the newer append-only log
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d
```
The reference graph (`cc_ref`) can always be rebuilt from public data: `python -c "from carecircle import reference as r; r.load()"`.

**Tested:** `scripts/restore_drill.py` takes the newest snapshot from the production bucket, loads it into a throwaway FalkorDB and checks it through the real engine. On 2026-10-16 the 6:17 UTC snapshot (8.3 MB) restored into a fresh database in 3 seconds (the whole drill took 41 seconds, mostly the download from India) with `cc_ref` (1,831 drugs, 219,723 interactions), both demo accounts and the demo circle (10 medicines, 139 events, 37 readings) intact. Run it again whenever backups change. The drill proves the snapshot file is good and loads; the on-instance steps above are the same primitives, but were not rehearsed on the production volume (that would mean stopping the live site).

**What to expect (recovery numbers).** A crash or reboot: back in about a minute from the append-only file, losing at most the last second of writes. A lost disk or host: restore the newest snapshot, which loses up to 6 hours of writes (the backup interval) and takes minutes. There is no replica, so a restore is manual.

**Demo circles are synthetic**, so losing them costs nothing; the backup matters most for any circle created with real use.

## FalkorDB crash-loops on start while replaying its log (seen 17 Oct 2026)

Symptom: the site answers 502, `docker ps` shows `deploy-falkordb-1  Restarting (139)`, and `docker logs deploy-falkordb-1` shows the snapshot loading and then
`crashed by signal: 11` in `GraphContext_GetSchemaByID` while it replays `appendonlydir/appendonly.aof.1.incr.aof`. The snapshot (`dump.rdb`) itself loads.
It happened when a deploy changed FalkorDB's start arguments, so the container was recreated after 36 hours of writes. Rolling back the code does not help,
because the same log is replayed. What fixed it (keep the old files, delete nothing):

```
C="docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env"; V=/var/lib/docker/volumes/deploy_falkor-data/_data; TS=$(date +%Y%m%d-%H%M%S)
$C stop falkordb api
mkdir -p /opt/cc-backup && cp -a $V /opt/cc-backup/falkor-data-$TS && mv $V/appendonlydir /opt/cc-backup/appendonlydir-crashing-$TS
docker run -d --name dbfix -v deploy_falkor-data:/var/lib/falkordb/data -e REDIS_ARGS="--appendonly no" <the pinned falkordb image>
docker exec dbfix redis-cli graph.list | wc -l          # the graphs are there
docker exec dbfix redis-cli config set appendonly yes    # writes a fresh log from what was loaded; wait for aof_rewrite_in_progress:0
docker stop dbfix && docker rm dbfix && $C up -d falkordb && $C up -d api
```

Anything written after the snapshot and only in the crashing log is lost (that time, nothing: the log was older than the snapshot).
