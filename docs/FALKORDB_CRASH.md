# A FalkorDB 4.22.1 crash found on 17 October 2026, what was done about it, and a draft report

## What happened

At 08:13 UTC the live site began answering 502. The database container was restarting in a loop (exit 139): it loaded its snapshot, then crashed about a second and a half later while replaying its append-only file (`appendonly.aof.1.incr.aof`, 35 MB, 17,770 commands). The site was restored from the snapshot (`deploy/RESTORE.md`). Nothing was lost.

## What was found (all of it on copies, in throwaway containers)

1. **The replay crash is deterministic.** Replaying the saved log crashes every time. Bisecting by command count found the first crashing command: number 7,534, a `GRAPH.EFFECT` on the graph `mem__tt-stress-a-…`, a graph that had been written, then removed with `GRAPH.DELETE` (command 3,926), and written again under the same name.
2. **The smallest case is one command.** Reducing the 644 commands on that graph down kept going until a single `GRAPH.EFFECT` was left, and that alone is enough. Sent to a clean, empty FalkorDB 4.22.1 with no append-only file at all, a single `GRAPH.EFFECT <graph that does not exist> <payload>` aborts the server at once (`crashed by signal: 6`). The stack in the original crash is `GraphContext_GetSchemaByID` (a null graph context).
3. **So the log is only dangerous when it holds an effect addressed to a graph that does not exist at that point of the replay.** A plain delete-then-recreate through the application's own setup code did not do it in two attempts (locally and on the server), so the exact sequence that leaves such an effect in the log is not pinned down. The saved crashing log is kept on the instance (`/opt/cc-backup/appendonlydir-crashing-*`) and reproduces it.

What this does not say: that FalkorDB is unsafe in general. Snapshot loading worked every time it was tried, including after a hard kill.

## What was done

- **The database now persists by snapshots only** (`--appendonly no --save 60 1 --save 300 100`), so there is no log to replay (`deploy/docker-compose.prod.yml`). Tested in a throwaway container with the same write, delete, write-again pattern, a clean stop and a hard kill: no crash, all graphs back. The cost: after a hard crash up to the last minute of writes is lost (before, about a second).
- **Every deploy takes a backup first** (`deploy/backup.sh`: a snapshot copied to S3), and EBS snapshots run daily, so a bad start has a copy minutes old, not hours.
- The restore steps are in `deploy/RESTORE.md`.

## Draft report for FalkorDB (not sent)

> **FalkorDB 4.22.1: `GRAPH.EFFECT` for a graph key that does not exist aborts the server; the same happens when replaying an AOF**
>
> Image `falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a` (graph module 4.22.1, Redis 8.10.2).
>
> Minimal: on an empty server, send one `GRAPH.EFFECT nosuchgraph <effect payload>` (any effect that refers to existing schema; payload below). The server aborts (`crashed by signal: 6`); stack top `GraphContext_GetSchemaByID`.
> Real-world form: with `--appendonly yes`, an application that writes a graph, `GRAPH.DELETE`s it and writes the same name again produced an AOF whose replay segfaults on load (signal 11, `Accessing address: 0x10`, `GraphContext_GetSchemaByID+0x4b`); the container then restarts in a loop. The AOF base file was the empty one, so everything was in the 17,770 command incr file.
> Expected: a reply with an error (or the effect applied after creating the key), not a process abort.
> Payload (hex): `020300000001000300000004000200000800000700000000000000746f706963330016000008000008000000000000007365656e5f62790017000008000004000000000000007732300018`
> The full crashing AOF can be supplied (it holds synthetic data only).

Filing this upstream is left to the owner of the project.
