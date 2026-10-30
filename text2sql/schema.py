"""Render caller-supplied schema metadata; no database or filesystem access."""
from text2sql.validation.policy import normalize_schema


def schema_documents(schema):
    normalized = normalize_schema(schema)
    raw_tables = schema.get("tables", []) if isinstance(schema.get("tables"), list) else []
    relationships = {(t["schema"], t["name"]): t.get("foreign_keys", []) for t in raw_tables}
    documents = []
    for namespace, tables in normalized.items():
        for table, columns in tables.items():
            name = namespace + "." + table
            text = "Table: " + name + "\nColumns:\n"
            text += "\n".join("- " + c + " " + kind for c, kind in columns.items())
            lines = []
            for fk in relationships.get((namespace, table), []):
                target = fk["references"]
                lines.append("- FOREIGN KEY (" + ", ".join(fk["columns"]) + ") REFERENCES "
                             + target["schema"] + "." + target["table"] + " ("
                             + ", ".join(target["columns"]) + ").")
            text += "\n\nRelationships:\n" + "\n".join(lines)
            documents.append(dict(schema=namespace, table_name=table, full_name=name, text=text))
    if not documents:
        raise ValueError("EMPTY_SCHEMA")
    return documents
