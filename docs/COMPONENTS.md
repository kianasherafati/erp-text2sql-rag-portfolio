# Working with the components

The Streamlit interface and `python -m text2sql.demo` are synthetic-only. There is
no switch that turns the demo into an authenticated company reporting system.

## Optional model pipeline

Install `requirements-models.txt` before using the adapters below. Construction
loads model weights and may download them from Hugging Face. CPU embeddings and
reranking can be slow; Qwen requires substantial memory. No weights are bundled.
Pass pinned model revisions and `local_files_only=True` when using provisioned
snapshots. Local-only mode fails when a required snapshot is missing.

```python
import json
from pathlib import Path
from text2sql.schema import schema_documents
from text2sql.models import EmbeddingEncoder, BGEReranker, LocalQwen
from text2sql.retrieval.pipeline import SchemaRetriever
from text2sql.pipeline import TextToSQL

schema = json.loads(Path("examples/schema.json").read_text())
retriever = SchemaRetriever(
    schema_documents(schema),
    EmbeddingEncoder("BAAI/bge-m3"),
    EmbeddingEncoder("sentence-transformers/all-MiniLM-L6-v2"),
    BGEReranker(),
    context_size=10,
)
pipeline = TextToSQL(schema, retriever, LocalQwen())
result = pipeline.run("Show total order amount for each customer.")
print(result.status, result.sql)
```

This is optional integration code, not a claim that model inference was run for
the public release. Quantized Qwen loading is opt-in through `LocalQwen(quantize=True)`
and requires a compatible separately installed bitsandbytes runtime. The default
uses ordinary model weights. Model adapters are lazy at module import; tests use
injected tiny numeric fixtures, not downloaded models.

The retrieval code adapts the project's identifier tokenization, lexical weighting
and one-hop FK scoring. It builds in-memory FAISS indexes from caller-supplied
documents instead of using private pickle files or machine-specific manifests.
The grounding prompt and scope-aware SQL validator are retained with package
imports adjusted for this edition. Do not treat this as the historical frozen
evaluation runtime.

## SQL Server boundary

Install `requirements-sqlserver.txt` and Microsoft ODBC Driver 18 for SQL Server.
Provision your own authorized schema and a database principal restricted to
SELECT on approved objects. Configure `DB_SERVER`, `DB_DATABASE`, `DB_USERNAME`,
`DB_PASSWORD` and optionally `DB_DRIVER` in the process environment. Local `.env`
files are ignored but are not automatically loaded. Never add real connection
values to source code. The adapter requires a valid trusted TLS certificate.

Call `text2sql.execution.execute_preview` separately with the same trusted schema
and selected-table allowlist, `authorized=True`, and `ERP_SAFE_SQL_ENABLED=true`.
The function revalidates the SQL immediately before connection, binds named
parameters, applies connection/query timeouts, requests read-only access, caps
the returned preview, and closes the cursor and connection after rollback.
Driver diagnostics are replaced with fixed error codes.

Authorization must come from the caller, never from generated text. SQL Server
permissions enforce the actual access boundary; the ODBC read-only request and
`ApplicationIntent` do not replace permissions. Preview truncation is explicitly
reported. A rollback does not undo CPU or I/O cost. Static validation is a
conservative filter, not a full SQL Server compiler or a semantic verifier.

## Local checks

```powershell
.\.venv\Scripts\python.exe -m text2sql.demo
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/check_publication.py
```

The basic test suite runs without model or database access. Numeric FAISS tests
are skipped unless the optional FAISS dependency is installed. SQL execution
tests inject a fake driver and invented connection settings; they open no network
connections. Live database and full model inference are intentionally outside
the release checks.
