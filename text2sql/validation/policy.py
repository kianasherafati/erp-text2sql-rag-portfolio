"""Output parsing and SELECT/schema validation. No connection or model imports."""
import re
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope

class PolicyError(ValueError):
    pass


SCHEMA_CONTRACT_ERROR_CODES = frozenset({
    'SCHEMA_CONTRACT_INVALID_TOP_LEVEL',
    'SCHEMA_CONTRACT_INVALID_DATABASE',
    'SCHEMA_CONTRACT_INVALID_NORMALIZED_SCHEMA',
    'SCHEMA_CONTRACT_INVALID_TABLES',
    'SCHEMA_CONTRACT_INVALID_TABLE',
    'SCHEMA_CONTRACT_INVALID_IDENTIFIER',
    'SCHEMA_CONTRACT_INVALID_COLUMNS',
    'SCHEMA_CONTRACT_INVALID_COLUMN',
    'SCHEMA_CONTRACT_INVALID_TYPE',
    'SCHEMA_CONTRACT_DUPLICATE_TABLE',
    'SCHEMA_CONTRACT_DUPLICATE_COLUMN',
})

_RAW_SCHEMA_KEYS = frozenset({'database', 'tables'})
_TYPE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(?:\((?:MAX|[0-9]+)(?:,[0-9]+)?\))?$', re.I)


def _valid_identifier(value):
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and '.' not in value and not any(ord(character) < 32 for character in value))


def _valid_type(value):
    return (isinstance(value, str) and value == value.strip()
            and _TYPE.fullmatch(value) is not None)


def _validate_normalized_schema(schema):
    if not isinstance(schema, dict):
        raise PolicyError('SCHEMA_CONTRACT_INVALID_TOP_LEVEL')
    seen_schemas = set()
    for schema_name, tables in schema.items():
        if not _valid_identifier(schema_name):
            raise PolicyError('SCHEMA_CONTRACT_INVALID_IDENTIFIER')
        schema_key = schema_name.casefold()
        if schema_key in seen_schemas:
            raise PolicyError('SCHEMA_CONTRACT_INVALID_NORMALIZED_SCHEMA')
        seen_schemas.add(schema_key)
        if not isinstance(tables, dict) or not tables:
            raise PolicyError('SCHEMA_CONTRACT_INVALID_NORMALIZED_SCHEMA')
        seen_tables = set()
        for table_name, columns in tables.items():
            if not _valid_identifier(table_name):
                raise PolicyError('SCHEMA_CONTRACT_INVALID_IDENTIFIER')
            table_key = table_name.casefold()
            if table_key in seen_tables:
                raise PolicyError('SCHEMA_CONTRACT_DUPLICATE_TABLE')
            seen_tables.add(table_key)
            if not isinstance(columns, dict) or not columns:
                raise PolicyError('SCHEMA_CONTRACT_INVALID_COLUMNS')
            seen_columns = set()
            for column_name, data_type in columns.items():
                if not _valid_identifier(column_name):
                    raise PolicyError('SCHEMA_CONTRACT_INVALID_IDENTIFIER')
                column_key = column_name.casefold()
                if column_key in seen_columns:
                    raise PolicyError('SCHEMA_CONTRACT_DUPLICATE_COLUMN')
                seen_columns.add(column_key)
                if not _valid_type(data_type):
                    raise PolicyError('SCHEMA_CONTRACT_INVALID_TYPE')
    # Preserve the documented representation rather than rewriting an already
    # normalized caller-owned mapping.
    return schema


def normalize_schema(schema):
    """Validate and adapt the frozen raw schema artifact for sqlglot.

    Accepted inputs are either the documented nested mapping or the exact raw
    top-level ``database``/``tables`` representation.  Duplicate detection is
    case-insensitive to match SQL Server identifier behavior.  Error messages
    are fixed policy codes and never contain artifact values.
    """
    if not isinstance(schema, dict):
        raise PolicyError('SCHEMA_CONTRACT_INVALID_TOP_LEVEL')
    if not schema:
        return schema
    keys = set(schema)
    if keys != _RAW_SCHEMA_KEYS:
        if 'database' in keys and 'tables' in keys:
            raise PolicyError('SCHEMA_CONTRACT_INVALID_TOP_LEVEL')
        return _validate_normalized_schema(schema)
    if not _valid_identifier(schema.get('database')):
        raise PolicyError('SCHEMA_CONTRACT_INVALID_DATABASE')
    tables = schema.get('tables')
    if not isinstance(tables, list) or not tables:
        raise PolicyError('SCHEMA_CONTRACT_INVALID_TABLES')

    normalized = {}
    seen_tables = set()
    for table in tables:
        if (not isinstance(table, dict)
                or not {'schema', 'name', 'columns'} <= set(table)):
            raise PolicyError('SCHEMA_CONTRACT_INVALID_TABLE')
        schema_name, table_name = table.get('schema'), table.get('name')
        if not _valid_identifier(schema_name) or not _valid_identifier(table_name):
            raise PolicyError('SCHEMA_CONTRACT_INVALID_IDENTIFIER')
        table_key = (schema_name.casefold(), table_name.casefold())
        if table_key in seen_tables:
            raise PolicyError('SCHEMA_CONTRACT_DUPLICATE_TABLE')
        seen_tables.add(table_key)
        columns = table.get('columns')
        if not isinstance(columns, list) or not columns:
            raise PolicyError('SCHEMA_CONTRACT_INVALID_COLUMNS')
        normalized_columns = {}
        seen_columns = set()
        for column in columns:
            if (not isinstance(column, dict)
                    or not {'name', 'data_type'} <= set(column)):
                raise PolicyError('SCHEMA_CONTRACT_INVALID_COLUMN')
            column_name, data_type = column.get('name'), column.get('data_type')
            if not _valid_identifier(column_name):
                raise PolicyError('SCHEMA_CONTRACT_INVALID_IDENTIFIER')
            column_key = column_name.casefold()
            if column_key in seen_columns:
                raise PolicyError('SCHEMA_CONTRACT_DUPLICATE_COLUMN')
            seen_columns.add(column_key)
            if not _valid_type(data_type):
                raise PolicyError('SCHEMA_CONTRACT_INVALID_TYPE')
            normalized_columns[column_name] = data_type
        normalized.setdefault(schema_name, {})[table_name] = normalized_columns
    return normalized


def extract_output(text):
    text = text.strip()
    if text == 'INSUFFICIENT_SCHEMA':
        return {'status': 'ABSTAINED', 'sql': None}
    if text.startswith('```'):
        match = re.fullmatch(r'```(?:sql|tsql)?[ \t]*\r?\n([\s\S]*?)\r?\n```', text, re.I)
        if not match:
            raise PolicyError('MALFORMED_OUTPUT')
        text = match.group(1).strip()
    if not re.match(r'^(SELECT|WITH)\b', text, re.I):
        raise PolicyError('MALFORMED_OUTPUT')
    return {'status': 'SQL', 'sql': text}


def parse_select(sql):
    try:
        statements = sqlglot.parse(sql, read='tsql')
    except Exception as e:
        raise PolicyError('PARSE_ERROR') from e
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise PolicyError('EXACTLY_ONE_SELECT_REQUIRED')
    tree = statements[0]
    forbidden = {'insert','update','delete','merge','create','drop','alter','truncate','truncatetable','command','execute','grant','revoke','use','into','transaction','commit','rollback','lock','tablehint','withtablehint','nextvaluefor'}
    for node in tree.walk():
        if node.key.lower() in forbidden or isinstance(node, (exp.DDL, exp.DML, exp.Into, exp.Command)):
            raise PolicyError('FORBIDDEN_SQL')
        if isinstance(node, exp.Func):
            if isinstance(node, exp.Anonymous):
                raise PolicyError('UNVERIFIED_FUNCTION')
            if node.sql_name().upper() in {'CURRENT_TIMESTAMP','CURRENT_DATE','CURRENT_TIME','RAND','UUID','NEWID','NEXT_VALUE_FOR','READ_CSV','READ_PARQUET'}:
                raise PolicyError('NONDETERMINISTIC_OR_EXTERNAL_FUNCTION')
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            raise PolicyError('USER_FUNCTION_REQUIRES_SEPARATE_AUDIT')
    return tree


def validate_query(sql, schema, allowed_tables):
    """Accept normalized or frozen-artifact schema; allowed physical names explicit."""
    tree = parse_select(sql)
    allowed = {s.casefold() for s in allowed_tables}
    physical = set()
    for scope in traverse_scope(tree):
        for source in scope.sources.values():
            if not isinstance(source, exp.Table):
                continue
            if not source.db or source.catalog or not isinstance(source.this, exp.Identifier):
                raise PolicyError('PHYSICAL_TABLE_MUST_BE_LOCAL_TWO_PART_NAME')
            name = source.db + '.' + source.name
            if name.casefold() not in allowed:
                raise PolicyError('TABLE_OUTSIDE_ALLOWED_SCHEMA')
            physical.add(name.casefold())
    normalized_schema = normalize_schema(schema)
    try:
        qualify(tree.copy(), dialect='tsql', schema=normalized_schema, validate_qualify_columns=True,
                quote_identifiers=False, identify=False, infer_schema=False)
    except Exception as e:
        raise PolicyError('SCHEMA_VALIDATION_FAILED') from e
    return {'physical_tables': sorted(physical)}
