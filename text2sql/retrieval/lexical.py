"""Hybrid dense and identifier-lexical retrieval over the existing index."""

import re



DENSE_WEIGHT = 0.70
LEXICAL_WEIGHT = 0.30

ABBREVIATIONS = {
    "amt": "amount",
    "desc": "description",
    "num": "number",
    "no": "number",
    "qty": "quantity",
}

# These tokens are structural rather than descriptive identifiers.
STRUCTURAL_TOKENS = {"tbl", "table", "id", "ig", "l"}

# Common identifiers can contribute, but cannot outweigh domain-specific words.
TOKEN_WEIGHTS = {
    "code": 0.20,
    "date": 0.20,
    "description": 0.35,
    "name": 0.25,
    "number": 0.25,
    "sequence": 0.35,
    "type": 0.25,
}

QUERY_STOP_WORDS = {
    "a", "all", "an", "and", "at", "by", "each", "for", "from",
    "in", "is", "it", "of", "on", "or", "report", "show", "summarize",
    "the", "their", "to", "whether", "with",
}


def _singularize(token):
    """Apply a deliberately small, deterministic English plural reduction."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("ses"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalize_tokens(value, *, is_identifier=False):
    """Normalize natural language or a schema identifier into lexical tokens."""
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    raw_tokens = re.sub(r"[^A-Za-z0-9]+", " ", value).lower().split()

    tokens = []
    for token in raw_tokens:
        token = ABBREVIATIONS.get(_singularize(token), _singularize(token))
        if token in STRUCTURAL_TOKENS:
            continue
        if not is_identifier and token in QUERY_STOP_WORDS:
            continue
        tokens.append(token)
    return tokens


def extract_own_column_names(document_text):
    """Extract identifiers only from the document's own Columns section."""
    match = re.search(
        r"(?:^|\n)Columns:\s*\n(?P<columns>.*?)(?:\n\nRelationships:|\Z)",
        document_text,
        flags=re.DOTALL,
    )
    if not match:
        return []

    names = []
    for line in match.group("columns").splitlines():
        column_match = re.match(r"\s*-\s+([^\s(]+)", line)
        if column_match:
            names.append(column_match.group(1))
    return names


def _token_weight(token):
    return TOKEN_WEIGHTS.get(token, 1.0)


def _identifier_match_score(query_tokens, identifier_tokens):
    identifier = set(identifier_tokens)
    if not identifier:
        return 0.0
    overlap = set(query_tokens) & identifier
    return min(1.0, sum(_token_weight(token) for token in overlap))


def build_lexical_record(document):
    """Precompute permitted lexical fields for one indexed table."""
    table_tokens = normalize_tokens(document["table_name"], is_identifier=True)
    schema_tokens = normalize_tokens(document["schema"], is_identifier=True)
    column_tokens = [
        normalize_tokens(name, is_identifier=True)
        for name in extract_own_column_names(document["text"])
    ]
    return {
        "table_tokens": table_tokens,
        "schema_tokens": schema_tokens,
        "column_tokens": column_tokens,
    }


def lexical_score(question, lexical_record):
    """Return a bounded table-heavy lexical score with column saturation."""
    query_tokens = normalize_tokens(question)

    table_score = _identifier_match_score(
        query_tokens,
        lexical_record["table_tokens"],
    )
    schema_score = _identifier_match_score(
        query_tokens,
        lexical_record["schema_tokens"],
    )

    column_matches = sorted(
        (
            _identifier_match_score(query_tokens, tokens)
            for tokens in lexical_record["column_tokens"]
        ),
        reverse=True,
    )
    # Diminishing returns prevent a wide table full of generic columns from
    # overwhelming a meaningful table-name match.
    column_weights = (0.50, 0.25, 0.15, 0.07, 0.03)
    column_score = sum(
        weight * score
        for weight, score in zip(column_weights, column_matches)
    )

    return min(
        1.0,
        0.65 * table_score + 0.30 * column_score + 0.05 * schema_score,
    )
