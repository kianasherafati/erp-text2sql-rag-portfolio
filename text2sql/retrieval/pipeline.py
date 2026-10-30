"""Dense50 + MiniLM hybrid/FK50 union, BGE reranking, bounded context.

Embedding and reranking runtimes are injected. Importing this module never loads
models, downloads weights, or opens a private index.
"""
import math
from text2sql.retrieval.lexical import build_lexical_record, lexical_score
from text2sql.retrieval.graph import build_outgoing_adjacency, rank_expanded_candidates


class SchemaRetriever:
    def __init__(self, documents, bge_encoder, minilm_encoder, reranker, *, context_size=10):
        if type(context_size) is not int or not 1 <= context_size <= 50:
            raise ValueError("INVALID_CONTEXT_SIZE")
        if not documents or len({d["full_name"] for d in documents}) != len(documents):
            raise ValueError("SCHEMA_IDENTITIES_MUST_BE_UNIQUE")
        self.documents = list(documents)
        self.bge, self.minilm, self.reranker = bge_encoder, minilm_encoder, reranker
        self.context_size = context_size
        self.lexical = [build_lexical_record(d) for d in self.documents]
        self.adjacency = build_outgoing_adjacency(self.documents)
        self.bge_index = self._index(self.bge)
        self.minilm_index = self._index(self.minilm)

    def _index(self, encoder):
        import faiss
        vectors = self._vectors(encoder.encode([d["text"] for d in self.documents]))
        if vectors.shape[0] != len(self.documents):
            raise ValueError("SCHEMA_EMBEDDING_COUNT_MISMATCH")
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        return index

    @staticmethod
    def _vectors(values):
        import numpy as np
        values = np.asarray(values, dtype="float32")
        if values.ndim != 2 or not values.shape[1] or not np.isfinite(values).all():
            raise ValueError("INVALID_EMBEDDINGS")
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if (norms == 0).any():
            raise ValueError("ZERO_EMBEDDING")
        return values / norms

    def _dense(self, question, encoder, index):
        vector = self._vectors(encoder.encode([question]))
        if vector.shape != (1, index.d):
            raise ValueError("INVALID_QUERY_EMBEDDING")
        scores, positions = index.search(vector, len(self.documents))
        return [dict(self.documents[int(i)], dense_score=max(0.0, min(1.0, (float(s) + 1) / 2)))
                for s, i in zip(scores[0], positions[0]) if i >= 0]

    def retrieve(self, question):
        dense = self._dense(question, self.bge, self.bge_index)[:50]
        hybrid = self._dense(question, self.minilm, self.minilm_index)
        lexical_by_name = {d["full_name"]: r for d, r in zip(self.documents, self.lexical)}
        for row in hybrid:
            row["combined_score"] = (0.7 * row["dense_score"]
                                     + 0.3 * lexical_score(question, lexical_by_name[row["full_name"]]))
        hybrid.sort(key=lambda r: (-r["combined_score"], r["full_name"]))
        graph, _ = rank_expanded_candidates(hybrid, hybrid[:10], self.adjacency, 50)
        candidates = {r["full_name"]: r for r in dense + graph}
        ordered = [candidates[k] for k in sorted(candidates)]
        scores = list(self.reranker.score(question, ordered))
        if len(scores) != len(ordered) or not all(math.isfinite(float(s)) for s in scores):
            raise ValueError("INVALID_RERANKER_SCORES")
        for row, score in zip(ordered, scores):
            row["reranker_score"] = float(score)
        ordered.sort(key=lambda r: (-r["reranker_score"], r["full_name"]))
        return ordered[:self.context_size]
