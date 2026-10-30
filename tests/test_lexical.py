import unittest

from text2sql.retrieval.lexical import (
    build_lexical_record,
    extract_own_column_names,
    lexical_score,
    normalize_tokens,
)


class HybridLexicalTests(unittest.TestCase):
    def test_normalizes_camel_case_punctuation_prefix_and_abbreviation(self):
        self.assertEqual(
            normalize_tokens("tblPurchase_Order-QTY", is_identifier=True),
            ["purchase", "order", "quantity"],
        )

    def test_natural_language_normalization_is_compatible(self):
        self.assertEqual(
            normalize_tokens("Show purchase orders and quantities"),
            ["purchase", "order", "quantity"],
        )

    def test_extracts_only_own_columns(self):
        text = (
            "Table: own.tblOrder\nColumns:\n- OwnCode (Own Code) INT\n\n"
            "Relationships:\n- other.tblSecret references own.tblOrder"
        )
        self.assertEqual(extract_own_column_names(text), ["OwnCode"])
        record = build_lexical_record({
            "schema": "own",
            "table_name": "tblOrder",
            "text": text,
        })
        self.assertNotIn("secret", record["table_tokens"])
        self.assertNotIn("secret", record["schema_tokens"])
        self.assertTrue(all("secret" not in tokens for tokens in record["column_tokens"]))

    def test_table_match_outweighs_single_generic_column(self):
        table_record = {
            "table_tokens": ["purchase", "order"],
            "schema_tokens": [],
            "column_tokens": [],
        }
        generic_column_record = {
            "table_tokens": ["unrelated"],
            "schema_tokens": [],
            "column_tokens": [["code"]],
        }
        question = "purchase order code"
        self.assertGreater(
            lexical_score(question, table_record),
            lexical_score(question, generic_column_record),
        )

    def test_id_does_not_contribute(self):
        record = {
            "table_tokens": ["unrelated"],
            "schema_tokens": [],
            "column_tokens": [["id"]],
        }
        self.assertEqual(lexical_score("find the id", record), 0.0)


if __name__ == "__main__":
    unittest.main()
