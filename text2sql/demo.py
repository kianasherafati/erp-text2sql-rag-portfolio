"""Deterministic synthetic fixtures exercising the real validation boundary."""
import json
from pathlib import Path
from text2sql.pipeline import TextToSQL
from text2sql.schema import schema_documents
from text2sql.retrieval.lexical import build_lexical_record, lexical_score

EXAMPLES = {
    "Customer order totals": "Show total order amount for each customer.",
    "Missing schema": "Predict supplier risk next year.",
    "Unsafe request": "Delete all customer records.",
}
SQL = """SELECT c.CustomerID, c.Name, SUM(o.TotalAmount) AS OrderTotal
FROM demo.Customer AS c
JOIN demo.SalesOrder AS o ON o.CustomerID = c.CustomerID
GROUP BY c.CustomerID, c.Name"""
ROWS = [[1, "Example customer A", 120.0], [2, "Example customer B", 80.0]]


class DemoRetriever:
    def __init__(self, documents):
        self.documents = documents

    def retrieve(self, question):
        return sorted(self.documents, key=lambda d: (
            -lexical_score(question, build_lexical_record(d)), d["full_name"]))


class DemoGenerator:
    def generate(self, question, documents):
        if question == EXAMPLES["Customer order totals"]:
            return SQL
        if question == EXAMPLES["Unsafe request"]:
            return "DELETE FROM demo.Customer"
        return "INSUFFICIENT_SCHEMA"


def demo_service():
    schema = json.loads((Path(__file__).resolve().parents[1] / "examples/schema.json").read_text())
    return TextToSQL(schema, DemoRetriever(schema_documents(schema)), DemoGenerator())


def main():
    result = demo_service().run(EXAMPLES["Customer order totals"])
    print("Synthetic fixture demo: no Qwen inference or database connection.")
    print(result.status)
    print(result.sql)
    print("Synthetic preview:", ROWS)


if __name__ == "__main__":
    main()
