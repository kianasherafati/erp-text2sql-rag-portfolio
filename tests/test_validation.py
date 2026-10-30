import unittest
from text2sql.validation.validator import bind_parameters, parse_output, validate_sql

SCHEMA = {"dbo": {"A": {"ID": "int", "Value": "decimal"}, "B": {"ID": "int", "AID": "int"}}}


class ValidationTests(unittest.TestCase):
    def test_valid_scoped_cte_and_derived_table(self):
        for sql in ("WITH c AS (SELECT ID FROM dbo.A) SELECT c.ID FROM c",
                    "SELECT x.ID FROM (SELECT ID FROM dbo.A) AS x",
                    "SELECT a.ID FROM dbo.A AS a JOIN dbo.B AS b ON b.AID=a.ID"):
            with self.subTest(sql=sql):
                self.assertTrue(validate_sql(sql, SCHEMA, ("dbo.A", "dbo.B")).valid)

    def test_read_only_enforced(self):
        queries = ("DELETE FROM dbo.A", "UPDATE dbo.A SET ID=1", "SELECT * INTO dbo.C FROM dbo.A",
                   "SELECT 1; SELECT 2", "EXEC procname", "DROP TABLE dbo.A", "SELECT NEWID()",
                   "SELECT * FROM remote.dbo.A", "SELECT dbo.custom_fn(1)", "SELECT * FROM dbo.A WITH (NOLOCK)")
        for sql in queries:
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql, SCHEMA, ("dbo.A",)).code, "UNSAFE_SQL")

    def test_allowlist_is_separate_from_global_schema(self):
        self.assertEqual(validate_sql("SELECT ID FROM dbo.B", SCHEMA, ("dbo.A",)).code, "TABLE_OUTSIDE_SCHEMA")

    def test_unknown_and_ambiguous_references(self):
        for sql in ("SELECT Missing FROM dbo.A", "SELECT ID FROM dbo.A a JOIN dbo.B b ON a.ID=b.ID",
                    "SELECT c.Missing FROM (SELECT ID FROM dbo.A) c"):
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql, SCHEMA, ("dbo.A", "dbo.B")).code, "SCHEMA_REFERENCE_ERROR")

    def test_parse_failure_distinct(self):
        self.assertEqual(validate_sql("SELECT (", SCHEMA, ()).code, "PARSE_FAILURE")

    def test_allowlisted_unknown_table_with_star_still_rejected(self):
        self.assertEqual(validate_sql("SELECT * FROM dbo.Unknown", SCHEMA, ("dbo.Unknown",)).code, "SCHEMA_REFERENCE_ERROR")

    def test_parameter_problems_distinct(self):
        for sql in ("SELECT @Missing", "SELECT @@VERSION", "SELECT ?"):
            with self.subTest(sql=sql):
                self.assertEqual(validate_sql(sql, SCHEMA, (), parameter_types={}).code, "PARAMETER_BINDING_ERROR")
        self.assertTrue(validate_sql("SELECT @ID", SCHEMA, (), parameter_types={"ID": "int"}).valid)
        self.assertEqual(validate_sql("SELECT @ID", SCHEMA, (), parameter_types={"ID": "int"}, require_bindings=True).code, "PARAMETER_BINDING_ERROR")

    def test_binding_ignores_strings_and_comments(self):
        sql, values = bind_parameters("SELECT @ID, '@ID' AS literal, @ID -- @ID", {"ID": 7})
        self.assertEqual(sql, "SELECT ?, '@ID' AS literal, ? -- @ID")
        self.assertEqual(values, (7, 7))
        with self.assertRaises(ValueError):
            bind_parameters("SELECT @ID", {})

    def test_raw_schema_contract(self):
        raw = {"database": "fixture", "tables": [{"schema": "dbo", "name": "A", "columns": [{"name": "ID", "data_type": "int"}]}]}
        self.assertTrue(validate_sql("SELECT ID FROM dbo.A", raw, ("dbo.A",)).valid)
        raw["tables"][0]["columns"].append({"name": "id", "data_type": "int"})
        self.assertEqual(validate_sql("SELECT ID FROM dbo.A", raw, ("dbo.A",)).code, "SCHEMA_CONTRACT_ERROR")

    def test_output_parsing_preserves_baseline_contract(self):
        self.assertEqual(parse_output("INSUFFICIENT_SCHEMA"), ("INSUFFICIENT_SCHEMA", None))
        self.assertEqual(parse_output("```sql\nSELECT 1\n```"), ("SQL", "SELECT 1"))
        for output in ("Here is SQL: SELECT 1", "SELECT (", "SELECT 1; SELECT 2"):
            self.assertEqual(parse_output(output), ("OUTPUT_REJECTED", None))
