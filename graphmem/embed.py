"""Optional embeddings for semantic recall. Off by default; enable with GRAPHMEM_EMBEDDINGS=1 and `pip install fastembed`.

The model (default BAAI/bge-small-en-v1.5, 384 dims, runs on CPU via ONNX) is loaded once per process and run in a worker thread so
it never blocks the event loop. Vectors live in the graph as `Fact.embedding` behind a FalkorDB vector index (cosine).
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384


class Embedder:
    def __init__(self, model: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding   # imported lazily so the core never needs it
        self.model_name, self._m, self._lock = model, TextEmbedding(model), asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: [[float(x) for x in v] for v in self._m.embed(texts)])


_instance: Optional[Embedder] = None


def get_embedder() -> Optional[Embedder]:
    global _instance
    if os.getenv("GRAPHMEM_EMBEDDINGS", "") not in ("1", "true", "yes"):
        return None
    if _instance is None:
        _instance = Embedder(os.getenv("GRAPHMEM_EMBED_MODEL", DEFAULT_MODEL))
    return _instance
