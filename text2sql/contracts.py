"""Small immutable boundaries shared by validation and the pipeline."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    code: str
    sql: str = ""
    physical_tables: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryResult:
    status: str
    sql: str = ""
    tables: tuple[str, ...] = ()
    code: str = ""
