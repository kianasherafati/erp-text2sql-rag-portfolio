import os
import unittest
from unittest.mock import patch
from text2sql.execution import execute_preview, ExecutionBlocked, connection_string

SCHEMA = {"demo": {"Customer": {"CustomerID": "int"}}}
# Deliberately invented settings for an injected driver; no network is used.
SETTINGS = {"ERP_SAFE_SQL_ENABLED": "true", "DB_SERVER": "synthetic-host",
            "DB_DATABASE": "synthetic_demo", "DB_USERNAME": "synthetic_reader",
            "DB_PASSWORD": "synthetic-fixture-only"}


class FakeCursor:
    description = [("CustomerID",)]
    def execute(self, sql, *values):
        self.statement, self.values = sql, values
    def fetchmany(self, count):
        return [(1,), (2,)]
    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self):
        self.handle = FakeCursor()
        self.rolled_back = self.closed = False
    def cursor(self):
        return self.handle
    def rollback(self):
        self.rolled_back = True
    def close(self):
        self.closed = True


class ExecutionTests(unittest.TestCase):
    def test_disabled_and_unapproved_never_connect(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ExecutionBlocked, "AUTHORIZATION"):
                execute_preview("SELECT 1", {}, (), authorized=True)
        with patch.dict(os.environ, SETTINGS, clear=True):
            with self.assertRaisesRegex(ExecutionBlocked, "AUTHORIZATION"):
                execute_preview("SELECT 1", {}, ())

    def test_unsafe_query_never_connects(self):
        with patch.dict(os.environ, SETTINGS, clear=True):
            with self.assertRaises(ExecutionBlocked):
                execute_preview("DELETE FROM demo.Customer", SCHEMA, ("demo.Customer",), authorized=True,
                                connect=lambda *a, **k: self.fail("driver called"))

    def test_bound_parameters_preview_cap_and_cleanup(self):
        connection = FakeConnection()
        def connect(connstr, **kwargs):
            self.assertIn("Encrypt=yes;TrustServerCertificate=no", connstr)
            self.assertEqual(kwargs["attrs_before"], {101: 1})
            self.assertFalse(kwargs["autocommit"])
            return connection
        with patch.dict(os.environ, SETTINGS, clear=True):
            result = execute_preview("SELECT CustomerID FROM demo.Customer WHERE CustomerID=@ID", SCHEMA,
                                     ("demo.Customer",), authorized=True, bindings={"ID": 1},
                                     max_rows=1, connect=connect)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["rows"], [[1]])
        self.assertIn("CustomerID=?", connection.handle.statement)
        self.assertEqual(connection.handle.values, (1,))
        self.assertTrue(connection.rolled_back and connection.closed and connection.handle.closed)

    def test_driver_errors_are_redacted(self):
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic confidential driver diagnostic")
        with patch.dict(os.environ, SETTINGS, clear=True):
            with self.assertRaisesRegex(ExecutionBlocked, "^DATABASE_PREVIEW_FAILED$"):
                execute_preview("SELECT CustomerID FROM demo.Customer", SCHEMA,
                                ("demo.Customer",), authorized=True, connect=fail)

    def test_odbc_values_are_escaped(self):
        with patch.dict(os.environ, dict(SETTINGS, DB_DATABASE="synthetic};Encrypt=no"), clear=True):
            self.assertIn("DATABASE={synthetic}};Encrypt=no}", connection_string())

    def test_cleanup_failure_is_reported(self):
        connection = FakeConnection()
        connection.rollback = lambda: (_ for _ in ()).throw(RuntimeError())
        with patch.dict(os.environ, SETTINGS, clear=True):
            with self.assertRaisesRegex(ExecutionBlocked, "RESOURCE_CLEANUP_FAILED"):
                execute_preview("SELECT CustomerID FROM demo.Customer", SCHEMA, ("demo.Customer",),
                                authorized=True, connect=lambda *a, **k: connection)
        self.assertTrue(connection.closed)
