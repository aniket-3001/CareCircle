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

**Tested:** a snapshot downloaded from the bucket and loaded into a fresh FalkorDB container came back with `cc_ref` (1,831 drugs, 219,723 interactions) and every demo circle (2026-10-15). Note: on Windows Docker Desktop use `docker cp` into the container, not a bind mount.

**Demo circles are synthetic**, so losing them costs nothing; the backup matters most for any circle created with real use.
