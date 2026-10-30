import unittest
from text2sql.demo import demo_service, EXAMPLES
from text2sql.pipeline import TextToSQL
from text2sql.prompt import messages


class PipelineTests(unittest.TestCase):
    def test_synthetic_success_is_validated_but_never_executed(self):
        result = demo_service().run(EXAMPLES["Customer order totals"])
        self.assertEqual(result.status, "SQL_VALID")
        self.assertEqual(set(result.tables), {"demo.Customer", "demo.SalesOrder"})

    def test_unsafe_generation_is_rejected(self):
        self.assertEqual(demo_service().run(EXAMPLES["Unsafe request"]).status, "OUTPUT_REJECTED")

    def test_missing_schema_abstains(self):
        self.assertEqual(demo_service().run(EXAMPLES["Missing schema"]).status, "INSUFFICIENT_SCHEMA")

    def test_empty_input_does_not_reach_retrieval(self):
        self.assertEqual(TextToSQL({}, None, None).run(" ").code, "INVALID_QUESTION")

    def test_empty_context_does_not_generate(self):
        class Empty:
            def retrieve(self, question):
                return []
        self.assertEqual(TextToSQL({}, Empty(), None).run("Show totals").status, "INSUFFICIENT_SCHEMA")

    def test_prompt_separates_columns_from_fk_endpoints(self):
        docs = demo_service().retriever.documents
        record = dict(question="Show customers", tables=[
            dict(fully_qualified_table=d["full_name"], document=d["text"]) for d in docs])
        rendered = messages(record)
        self.assertIn("INSUFFICIENT_SCHEMA", rendered[0]["content"])
        self.assertIn("EXACT PHYSICAL COLUMNS OF demo.Customer", rendered[1]["content"])
        self.assertIn("FOREIGN KEY (CustomerID) REFERENCES demo.Customer", rendered[1]["content"])
