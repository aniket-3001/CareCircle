# Backups and recovery

**What runs, from the most recent copy to the oldest**
- The database keeps a snapshot on its own disk: after 60 seconds with any change, or 300 seconds with 100 changes. It has no append-only log (see the section below).
- **Before every deploy** the pipeline runs `deploy/backup.sh`: a snapshot of FalkorDB copied to S3. A deploy that goes wrong therefore has a copy from minutes ago.
- **Every 6 hours** the same script runs from cron (`/etc/cron.d/cc-backup`), copying `dump.rdb` to the private bucket `carecircle-backups-<account>/falkordb/<UTC time>.rdb`, deleted after 14 days.
- **Every day at 21:30 UTC** AWS Data Lifecycle Manager snapshots the whole disk (policy "carecircle daily EBS snapshot keep 7"; the volume carries the tag `Backup=carecircle`), 7 kept.
- **Watching:** Route 53 checks `https://3-228-70-117.sslip.io/healthz` from outside AWS every 30 seconds; the CloudWatch alarm `carecircle-site-down` fires after two failed minutes and publishes to the SNS topic `carecircle-alerts` (add an email subscription to it to be told). Two more alarms reboot the instance if its OS stops answering and recover it onto new hardware if the AWS host fails. A scheduled GitHub workflow (`uptime.yml`) also checks `/healthz` every 15 minutes. Docker restarts the containers on boot (`restart: unless-stopped`).
- **Settings and secrets** are in Parameter Store under `/carecircle/prod/` (secrets encrypted); each deploy writes `deploy/.env` from there (`deploy/render_env.sh`).

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

**What to expect (recovery numbers).** A crash or reboot: back in about a minute from the database's own snapshot, losing the last minute of writes at most. A bad deploy: restore the pre-deploy copy from S3, losing minutes. A lost disk or host: restore the newest S3 copy (up to 6 hours old unless a deploy ran since) or the newest EBS snapshot (up to a day), and it takes minutes. There is no replica, so a restore is manual.

**Restore from an EBS snapshot** (not rehearsed; the oldest of the three copies, for when the disk itself is gone): create a volume from the snapshot (`aws ec2 create-volume --snapshot-id <snap> --availability-zone us-east-1a`), attach it to any instance, mount it, and copy `var/lib/docker/volumes/deploy_falkor-data/_data/dump.rdb` off it; then restore that file as in "Restore a snapshot" above. The simpler route is a new instance from `deploy/infra/carecircle.yaml` and the newest S3 file.

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

The cause, a one-command reproduction and a draft report are in [`docs/FALKORDB_CRASH.md`](../docs/FALKORDB_CRASH.md). Since then the database no longer keeps an append-only log (snapshots every 60 seconds with a change), so this particular failure has no log to replay; to restore from the latest copy instead, use the S3 file or the EBS snapshot below.
