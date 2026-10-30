"""Tiny numeric fixtures exercise the real FAISS union/reranking path."""
import importlib.util
import unittest
from text2sql.retrieval.pipeline import SchemaRetriever


class Encoder:
    def encode(self, texts):
        return [[1.0, 0.0] if "Customer" in t else [0.0, 1.0] for t in texts]


class Reranker:
    def score(self, question, documents):
        return [2.0 if d["full_name"] == "demo.Customer" else 1.0 for d in documents]


@unittest.skipUnless(importlib.util.find_spec("faiss"), "Install requirements-models.txt for numeric retrieval checks")
class RetrievalTests(unittest.TestCase):
    def documents(self):
        return [dict(schema="demo", table_name="Customer", full_name="demo.Customer",
                     text="Table: demo.Customer\nColumns:\n- CustomerID INT"),
                dict(schema="demo", table_name="SalesOrder", full_name="demo.SalesOrder",
                     text="Table: demo.SalesOrder\nColumns:\n- OrderID INT\n\nRelationships:\n"
                          "- FOREIGN KEY (CustomerID) REFERENCES demo.Customer (CustomerID).")]

    def test_union_deduplication_final_ranking_and_cap(self):
        retriever = SchemaRetriever(self.documents(), Encoder(), Encoder(), Reranker(), context_size=1)
        result = retriever.retrieve("Show Customer")
        self.assertEqual([r["full_name"] for r in result], ["demo.Customer"])
        self.assertEqual(result[0]["reranker_score"], 2.0)

    def test_nonfinite_reranker_scores_fail_closed(self):
        class Broken(Reranker):
            def score(self, question, documents):
                return [float("nan")] * len(documents)
        retriever = SchemaRetriever(self.documents(), Encoder(), Encoder(), Broken())
        with self.assertRaisesRegex(ValueError, "INVALID_RERANKER"):
            retriever.retrieve("Show Customer")

    def test_invalid_or_duplicate_schema_rejected(self):
        docs = self.documents()
        with self.assertRaises(ValueError):
            SchemaRetriever([docs[0], docs[0]], None, None, None)
        with self.assertRaises(ValueError):
            SchemaRetriever(docs, None, None, None, context_size=0)

    def test_encoder_row_count_must_match_schema(self):
        class Broken(Encoder):
            def encode(self, texts):
                return [[1.0, 0.0]]
        with self.assertRaisesRegex(ValueError, "SCHEMA_EMBEDDING_COUNT_MISMATCH"):
            SchemaRetriever(self.documents(), Broken(), Encoder(), Reranker())
