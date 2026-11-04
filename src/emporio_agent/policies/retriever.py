"""Semantic retrieval over policy chunks (OpenAI embeddings + cosine similarity in numpy).

The corpus is ~26 short chunks, so a vector database would be overkill: the whole
index fits in memory and is cached on disk, keyed by a hash of the chunk texts.
If embeddings are unavailable (no key / network), it degrades to keyword overlap.
"""
import hashlib
import logging

import numpy as np

from ..config import CACHE_DIR, POLICY_PDF
from ..data.catalog import _tokens
from .ingest import Chunk, load_chunks

log = logging.getLogger(__name__)


class PolicyRetriever:
    def __init__(self, client=None, chunks: list[Chunk] | None = None,
                 embedding_model: str | None = "text-embedding-3-small"):
        self.client = client
        self.embedding_model = embedding_model
        self._embeddings_failed = False
        self.chunks = chunks if chunks is not None else load_chunks(POLICY_PDF)
        self._matrix: np.ndarray | None = None
        self._chunk_tokens = [_tokens(c.content) for c in self.chunks]

    def _embed(self, texts: list[str]) -> np.ndarray:
        resp = self.client.embeddings.create(model=self.embedding_model, input=texts)
        vecs = np.array([d.embedding for d in resp.data], dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def _index(self) -> np.ndarray:
        if self._matrix is not None:
            return self._matrix
        digest = hashlib.sha256(
            ((self.embedding_model or "") + "\n".join(c.content for c in self.chunks)).encode("utf-8")
        ).hexdigest()[:16]
        cache = CACHE_DIR / f"policy_index_{digest}.npy"
        if cache.exists():
            self._matrix = np.load(cache)
        else:
            self._matrix = self._embed([c.content for c in self.chunks])
            CACHE_DIR.mkdir(exist_ok=True)
            np.save(cache, self._matrix)
        return self._matrix

    def _keyword_scores(self, query: str) -> np.ndarray:
        q = _tokens(query)
        return np.array([len(q & t) / (len(q) or 1) for t in self._chunk_tokens])

    def search(self, query: str, k: int = 3) -> list[dict]:
        method = "embeddings"
        if self.client is None or not self.embedding_model or self._embeddings_failed:
            scores, method = self._keyword_scores(query), "keyword"
        else:
            try:
                scores = self._index() @ self._embed([query])[0]
            except Exception as exc:  # degrade gracefully (and stop retrying), but never silently
                log.warning("Embedding search unavailable (%s); using keyword fallback", exc)
                self._embeddings_failed = True
                scores, method = self._keyword_scores(query), "keyword"
        order = np.argsort(-scores)[:k]
        return [
            {"section": self.chunks[i].section, "title": self.chunks[i].title,
             "text": self.chunks[i].text, "score": round(float(scores[i]), 3), "method": method}
            for i in order
        ]
