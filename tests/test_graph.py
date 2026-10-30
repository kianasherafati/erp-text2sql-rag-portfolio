import unittest

from text2sql.retrieval.graph import (
    FIXED_FK_BONUS,
    build_outgoing_adjacency,
    expand_one_hop,
    graph_signal,
    rank_expanded_candidates,
)


def _document(name, relationships=""):
    text = f"Table: {name}\nColumns:\n- ID (I D) INT"
    if relationships:
        text += f"\n\nRelationships:\n{relationships}"
    return {"full_name": name, "text": text}


def _result(name, score):
    return {"full_name": name, "combined_score": score}


class GraphExpansionTests(unittest.TestCase):
    def test_outgoing_adjacency_deduplicates_targets(self):
        documents = [
            _document(
                "s.A",
                "- FK1: FOREIGN KEY (B1) REFERENCES s.B (ID).\n"
                "- FK2: FOREIGN KEY (B2) REFERENCES s.B (ID).",
            ),
            _document("s.B"),
        ]
        self.assertEqual(build_outgoing_adjacency(documents)["s.A"], ("s.B",))

    def test_self_edges_are_excluded(self):
        documents = [
            _document("s.A", "- FK: FOREIGN KEY (ParentID) REFERENCES s.A (ID)."),
        ]
        self.assertEqual(build_outgoing_adjacency(documents)["s.A"], ())

    def test_nonindexed_targets_are_excluded(self):
        documents = [
            _document("s.A", "- FK: FOREIGN KEY (BID) REFERENCES other.B (ID)."),
        ]
        self.assertEqual(build_outgoing_adjacency(documents)["s.A"], ())

    def test_incoming_description_is_not_treated_as_outgoing(self):
        documents = [
            _document("s.A", "- FK: other.B (AID) references s.A (ID)."),
            _document("other.B"),
        ]
        self.assertEqual(build_outgoing_adjacency(documents)["s.A"], ())

    def test_expansion_is_exactly_one_hop(self):
        seeds = [_result("s.A", 0.8)]
        candidates, _ = expand_one_hop(
            seeds,
            {"s.A": ("s.B",), "s.B": ("s.C",)},
        )
        self.assertEqual(candidates, {"s.A", "s.B"})

    def test_graph_scoring_is_deterministic(self):
        first = graph_signal(3, 0.8)
        second = graph_signal(3, 0.8)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first, 0.4)

    def test_final_top_k_is_enforced(self):
        all_results = [
            _result("s.A", 0.9),
            _result("s.B", 0.8),
            _result("s.C", 0.7),
        ]
        ranked, pool_size = rank_expanded_candidates(
            all_results,
            all_results[:2],
            {"s.A": ("s.C",), "s.B": ()},
            top_k=2,
        )
        self.assertEqual(len(ranked), 2)
        self.assertEqual(pool_size, 3)
        self.assertAlmostEqual(
            next(item for item in ranked if item["full_name"] == "s.C")[
                "fk_bonus_contribution"
            ],
            FIXED_FK_BONUS * 0.9,
        )


if __name__ == "__main__":
    unittest.main()
