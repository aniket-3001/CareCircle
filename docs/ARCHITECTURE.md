# Architecture

```mermaid
flowchart LR
  subgraph Front doors
    WEB[Web app /]:::f
    TG[Telegram bot]:::f
    MCPC[MCP client / agent]:::f
  end
  WEB -- HTTP bearer key --> API[graphmem/api.py FastAPI]
  TG --> CC
  MCPC -- stdio --> MCP[mcp_server.py] --> OPS
  API -- /intake --> INT[carecircle/intake.py<br/>OCR, ASR, PDF, DOCX, Bedrock]
  INT --> VER[quote verified against source text]
  API --> OPS[ops.py whitelisted operations]
  OPS --> POL[policy.py grants checked on every query]
  POL --> CARE[care.py record / confirm / regimen / check / ack / divergence / nudges / give]
  CARE --> CHK[checks.py + risk.py + safety.py]
  CARE --> DB[(FalkorDB)]
  CHK --> DB
  CC[carecircle/telegram.py] --> CARE
  subgraph FalkorDB graphs
    REF[cc_ref: Drug, INTERACTS, HAZARD, Enzyme, INHIBITS, SUBSTRATE_OF]
    CIRCLE[mem__circle: Person, Dose, ACKED, Give, Nudge]
    CTL[ctl: agents, grants, keys, Telegram links]
  end
  DB --- REF & CIRCLE & CTL
```

Request path: key -> `ctl` lookup (agent) -> op whitelist -> grant check (`read`/`write`/`admin`) -> parameterised Cypher on the
circle's graph (retried only on FalkorDB's "queue full" error, 503 if it persists). Interaction checks read the shared `cc_ref` graph, which no request can write.

## Intake path
```mermaid
sequenceDiagram
  participant C as carer
  participant A as API
  participant S as source reader
  participant M as Bedrock model (optional)
  participant G as circle graph
  C->>A: photo / voice / PDF / text
  A->>S: OCR / Whisper / pypdf -> source text
  A->>M: structure it (JSON only)
  A->>A: keep a proposal only if its quote occurs in the source text
  A-->>C: proposals with quote + top-3 drug candidates (nothing saved)
  C->>G: confirm -> care_record (supersedes the previous entry)
  G-->>C: other carers show as "not seen" until they acknowledge
```

## Why one graph per circle
Hard isolation (no tenant filter to forget in a query) and FalkorDB serializes writes per graph, so circles write in parallel.
Reference knowledge is shared once in `cc_ref` instead of copied into every circle.
