"""Container entrypoint: make sure the reference graph exists (download public data and load it once), then start the API.
The reference graph lives in FalkorDB; without it Care Circle has nothing to check against."""
import os
import subprocess
import sys
import time

from falkordb import FalkorDB

HOST, PORT = os.getenv("FALKORDB_HOST", "localhost"), int(os.getenv("FALKORDB_PORT", "6379"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ref_ready() -> bool:
    try:
        g = FalkorDB(host=HOST, port=PORT, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None).select_graph("cc_ref")
        return g.ro_query("MATCH (d:Drug) RETURN count(d)").result_set[0][0] > 1000
    except Exception:
        return False


for _ in range(60):                                   # wait for FalkorDB
    try:
        FalkorDB(host=HOST, port=PORT, password=os.getenv("GRAPHMEM_DB_PASSWORD") or None).list_graphs()
        break
    except Exception:
        time.sleep(1)

if not ref_ready():
    print("loading reference graph ...", flush=True)
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "fetch_reference.py")], check=True)
    from carecircle import reference
    print(reference.load(HOST, PORT), flush=True)

os.execvp(sys.executable, [sys.executable, "-m", "graphmem.api"])
