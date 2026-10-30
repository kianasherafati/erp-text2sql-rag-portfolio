"""Explicit, read-only SQL Server preview. No connection or .env access on import."""
import os
from text2sql.validation.validator import validate_sql, bind_parameters


class ExecutionBlocked(ValueError):
    pass


def connection_string():
    required = ("DB_SERVER", "DB_DATABASE", "DB_USERNAME", "DB_PASSWORD")
    if not all(os.environ.get(k) for k in required):
        raise ExecutionBlocked("MISSING_DATABASE_CONFIGURATION")
    def escape(value):
        return "{" + value.replace("}", "}}") + "}"
    fields = dict(DRIVER=os.environ.get("DB_DRIVER", "ODBC Driver 18 for SQL Server"),
                  SERVER=os.environ["DB_SERVER"], DATABASE=os.environ["DB_DATABASE"],
                  UID=os.environ["DB_USERNAME"], PWD=os.environ["DB_PASSWORD"])
    return ";".join(k + "=" + escape(v) for k, v in fields.items()) + ";Encrypt=yes;TrustServerCertificate=no;ApplicationIntent=ReadOnly"


def execute_preview(sql, schema, allowed_tables, *, authorized=False, bindings=None,
                    max_rows=100, connect=None):
    if os.environ.get("ERP_SAFE_SQL_ENABLED") != "true" or authorized is not True:
        raise ExecutionBlocked("EXPLICIT_AUTHORIZATION_REQUIRED")
    if type(max_rows) is not int or not 1 <= max_rows <= 1000:
        raise ExecutionBlocked("INVALID_PREVIEW_LIMIT")
    bindings = dict(bindings or {})
    checked = validate_sql(sql, schema, allowed_tables, bindings=bindings, require_bindings=True)
    if not checked.valid:
        raise ExecutionBlocked(checked.code)
    statement, values = bind_parameters(checked.sql, bindings)
    connection = cursor = None
    try:
        if connect is None:
            import pyodbc
            connect = pyodbc.connect
        # SQL_ATTR_ACCESS_MODE=101, SQL_MODE_READ_ONLY=1. Permissions on the SQL
        # Server login remain essential; ApplicationIntent alone is not a grant.
        connection = connect(connection_string(), timeout=5, autocommit=False, attrs_before={101: 1})
        connection.timeout = 10
        cursor = connection.cursor()
        cursor.execute(statement, *values)
        if cursor.description is None:
            raise ExecutionBlocked("NO_RESULT_SET")
        rows = cursor.fetchmany(max_rows + 1)
        return dict(columns=[c[0] for c in cursor.description], rows=[list(r) for r in rows[:max_rows]],
                    truncated=len(rows) > max_rows)
    except ExecutionBlocked:
        raise
    except Exception:
        raise ExecutionBlocked("DATABASE_PREVIEW_FAILED") from None
    finally:
        failed = False
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                failed = True
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                failed = True
            try:
                connection.close()
            except Exception:
                failed = True
        if failed:
            raise ExecutionBlocked("RESOURCE_CLEANUP_FAILED") from None
