"""Scope-aware T-SQL validation adapted from the project validator.

Validation codes intentionally omit sqlglot/ODBC exception messages. Parameter
names are case-sensitive contract keys. SQL Server system variables and positional
placeholders are disallowed; named values are bound only at the execution boundary.
"""
import re
import sqlglot
from sqlglot import ErrorLevel, exp
from sqlglot.tokens import TokenType
from text2sql.validation import policy as baseline
from text2sql.contracts import ValidationResult
from text2sql.validation.guard import check_column_scopes, check_dialect


def parameter_spans(sql):
    tokens = sqlglot.tokenize(sql, read="tsql")
    spans = []
    for i, token in enumerate(tokens):
        if token.token_type == TokenType.PLACEHOLDER:
            raise ValueError("PARAMETER_BINDING_ERROR")
        if token.token_type != TokenType.PARAMETER:
            continue
        if i + 1 >= len(tokens):
            raise ValueError("PARAMETER_BINDING_ERROR")
        name = tokens[i + 1]
        if name.start != token.end + 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.text):
            raise ValueError("PARAMETER_BINDING_ERROR")
        if i and tokens[i - 1].token_type == TokenType.PARAMETER:
            raise ValueError("PARAMETER_BINDING_ERROR")
        spans.append((token.start, name.end + 1, name.text))
    return spans


def bind_parameters(sql, bindings):
    """Return DB-API SQL/values; never interpolate values into SQL or trace them."""
    spans = parameter_spans(sql)
    if any(name not in bindings for _, _, name in spans):
        raise ValueError("PARAMETER_BINDING_ERROR")
    values = tuple(bindings[name] for _, _, name in spans)
    for start, end, _ in reversed(spans):
        sql = sql[:start] + "?" + sql[end:]
    return sql, values


def validate_sql(sql, schema, allowed_tables, *, parameter_types=None, bindings=None,
                 require_bindings=False):
    def reject(code):
        return ValidationResult(False, code)
    if not isinstance(sql, str) or not sql.strip():
        return reject("PARSE_FAILURE")
    try:
        trees = sqlglot.parse(sql, read="tsql", error_level=ErrorLevel.RAISE)
    except Exception:
        return reject("PARSE_FAILURE")
    if len(trees) != 1 or not isinstance(trees[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return reject("UNSAFE_SQL")
    try:
        check_dialect(sql, trees[0])
    except Exception:
        return reject("UNSUPPORTED_DIALECT")
    try:
        names = tuple(dict.fromkeys(name for _, _, name in parameter_spans(sql)))
        declared = parameter_types if parameter_types is not None else (bindings or {})
        if not set(names) <= set(declared):
            return reject("PARAMETER_BINDING_ERROR")
        if require_bindings and not set(names) <= set(bindings or {}):
            return reject("PARAMETER_BINDING_ERROR")
    except Exception:
        return reject("PARAMETER_BINDING_ERROR")
    try:
        result = baseline.validate_query(sql, schema, allowed_tables)
        # sqlglot can leave SELECT * against an unknown table unexpanded without
        # raising. An allowlisted name is not proof of its presence in the schema.
        normalized = baseline.normalize_schema(schema)
        physical = {f"{s}.{t}".casefold() for s, tables in normalized.items() for t in tables}
        if not set(result["physical_tables"]) <= physical:
            return reject("SCHEMA_REFERENCE_ERROR")
        check_column_scopes(trees[0], normalized)
    except baseline.PolicyError as exc:
        code = str(exc)
        if code == "PARSE_ERROR":
            return reject("PARSE_FAILURE")
        if code == "TABLE_OUTSIDE_ALLOWED_SCHEMA":
            return reject("TABLE_OUTSIDE_SCHEMA")
        if code == "SCHEMA_VALIDATION_FAILED":
            return reject("SCHEMA_REFERENCE_ERROR")
        if code in baseline.SCHEMA_CONTRACT_ERROR_CODES:
            return reject("SCHEMA_CONTRACT_ERROR")
        return reject("UNSAFE_SQL")
    except Exception:
        return reject("SCHEMA_REFERENCE_ERROR")
    return ValidationResult(True, "VALID", sql.strip(), tuple(result["physical_tables"]), names)


def parse_output(output):
    """Reuse baseline extraction, including exact INSUFFICIENT_SCHEMA abstention."""
    try:
        parsed = baseline.extract_output(output)
        if parsed["status"] != "ABSTAINED":
            trees = sqlglot.parse(parsed["sql"], read="tsql", error_level=ErrorLevel.RAISE)
            if len(trees) != 1 or not isinstance(trees[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
                return "OUTPUT_REJECTED", None
    except Exception:
        return "OUTPUT_REJECTED", None
    return ("INSUFFICIENT_SCHEMA", None) if parsed["status"] == "ABSTAINED" else ("SQL", parsed["sql"])
