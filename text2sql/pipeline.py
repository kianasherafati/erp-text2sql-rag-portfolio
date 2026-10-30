"""Retrieval, generation and validation; execution is a separate explicit action."""
from text2sql.contracts import QueryResult
from text2sql.validation.validator import parse_output, validate_sql


class TextToSQL:
    def __init__(self, schema, retriever, generator):
        self.schema, self.retriever, self.generator = schema, retriever, generator

    def run(self, question):
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            return QueryResult("REJECTED", code="INVALID_QUESTION")
        documents = self.retriever.retrieve(question.strip())
        if not documents:
            return QueryResult("INSUFFICIENT_SCHEMA")
        tables = tuple(d["full_name"] for d in documents)
        status, sql = parse_output(self.generator.generate(question.strip(), documents))
        if status != "SQL":
            return QueryResult(status, tables=tables, code=status)
        checked = validate_sql(sql, self.schema, tables)
        return QueryResult("SQL_VALID" if checked.valid else "REJECTED", sql, tables, checked.code)
