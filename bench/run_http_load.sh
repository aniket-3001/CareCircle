#!/usr/bin/env bash
# usage: bench/run_http_load.sh <api_processes> <tenants> <agents> <seconds> <load_procs>
# Starts N API processes (ports 8801..), runs bench/http_load.py against them, stops them, removes test data.
set -u
N=${1:-1}; TEN=${2:-16}; AG=${3:-4}; SEC=${4:-20}; LP=${5:-4}
cd "$(dirname "$0")/.."
PY=./.venv/Scripts/python
export GRAPHMEM_ADMIN_KEY=loadtest-admin GRAPHMEM_RATE_PER_MIN=0 PYTHONPATH=.
PORTS=""
for i in $(seq 1 "$N"); do
  P=$((8800 + i)); PORTS="$PORTS${PORTS:+,}$P"
  PORT=$P nohup $PY -m graphmem.api > "bench/.api_$P.log" 2>&1 &
done
for i in $(seq 1 "$N"); do
  P=$((8800 + i))
  for _ in $(seq 1 30); do curl -s -m 2 localhost:$P/healthz >/dev/null && break; sleep 1; done
done
$PY bench/http_load.py --ports "$PORTS" --tenants "$TEN" --agents "$AG" --seconds "$SEC" --procs "$LP" --admin loadtest-admin
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*graphmem.api*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }"
$PY - <<'EOF'
import asyncio
from graphmem import Db
async def main():
    db = Db()
    for t in [g[5:] for g in await db.client.list_graphs() if g.startswith("mem__hl-")]:
        await db.drop_tenant(t)
    c = db.client.select_graph("ctl")
    await c.query("MATCH (n) WHERE n.id STARTS WITH 'hl-' DETACH DELETE n")
    await c.query("MATCH (k:ApiKey) WHERE NOT ()-[:HAS_KEY]->(k) DELETE k")
asyncio.run(main())
EOF
rm -f bench/.last_run_*.json
