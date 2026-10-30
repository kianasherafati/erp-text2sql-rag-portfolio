"""Conservative source-syntax checks supplement sqlglot's permissive T-SQL reader.

No SQL is rewritten. Token checks ignore quoted identifiers, strings and comments.
This is not a full SQL Server compiler.
"""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope
from sqlglot.tokens import TokenType


def check_dialect(sql, tree):
    tokens = sqlglot.tokenize(sql, read='tsql')
    ignored = {TokenType.STRING, TokenType.NATIONAL_STRING, TokenType.IDENTIFIER}
    for token in tokens:
        if token.token_type in ignored:
            continue
        raw = sql[token.start:token.end + 1]
        if token.text.upper() in {'LIMIT', 'ILIKE'} or raw == '::' or '`' in raw:
            raise ValueError('UNSUPPORTED_DIALECT')
    # sqlglot also accepts incomplete/non-T-SQL pagination clauses.
    for i, token in enumerate(tokens):
        if token.token_type != TokenType.OFFSET:
            continue
        tail = tokens[i + 1:]
        boundary = next((j for j, t in enumerate(tail)
                         if t.token_type in {TokenType.FETCH, TokenType.SEMICOLON, TokenType.R_PAREN}), len(tail))
        if not any(t.text.upper() in {'ROW', 'ROWS'} and t.token_type not in ignored
                   for t in tail[:boundary]):
            raise ValueError('UNSUPPORTED_DIALECT')
    for query in tree.find_all(exp.Select, exp.Union, exp.Intersect, exp.Except):
        if isinstance(query.args.get('limit'), exp.Fetch) and query.args.get('offset') is None:
            raise ValueError('UNSUPPORTED_DIALECT')
        if query.args.get('offset') is not None:
            if query.args.get('order') is None or isinstance(query.args.get('limit'), exp.Limit):
                raise ValueError('UNSUPPORTED_DIALECT')


def check_column_scopes(tree, schema):
    # Default qualification expands SELECT aliases into WHERE/GROUP BY, accepting
    # SQL that SQL Server rejects. Do not use that repair as validation evidence.
    qualify(tree.copy(), dialect='tsql', schema=schema, expand_alias_refs=False,
            validate_qualify_columns=True, quote_identifiers=False, identify=False, infer_schema=False)
    normalized = {s.casefold(): {t.casefold(): {c.casefold() for c in cols}
                                for t, cols in tables.items()} for s, tables in schema.items()}
    for scope in traverse_scope(tree):
        for col in scope.columns:
            if col.catalog:
                raise ValueError('NONLOCAL_COLUMN_REFERENCE')
            if col.db:
                source = next((source for name, source in scope.sources.items()
                               if name.casefold() == col.table.casefold()), None)
                if (not isinstance(source, exp.Table) or source.alias
                        or col.db.casefold() != source.db.casefold()
                        or col.table.casefold() != source.name.casefold()):
                    raise ValueError('UNVERIFIED_COLUMN_OWNER')
        aliases = {e.alias.casefold() for e in scope.expression.selects if e.alias}
        having = scope.expression.args.get('having')
        if not having or not aliases:
            continue
        source_columns = set()
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                source_columns.update(normalized.get(source.db.casefold(), {}).get(source.name.casefold(), set()))
            elif isinstance(source, Scope):
                source_columns.update(n.casefold() for n in source.expression.named_selects)
        for col in having.find_all(exp.Column):
            if (col.find_ancestor(exp.Select) is scope.expression and not col.table
                    and col.name.casefold() in aliases - source_columns):
                raise ValueError('SELECT_ALIAS_NOT_VISIBLE_IN_HAVING')
