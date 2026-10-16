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
