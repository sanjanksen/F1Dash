"""F1Dash editorial RAG pipeline.

Modules:
- client: Supabase singleton + low-level inserts
- chunker: text splitter
- embed: OpenAI embeddings caller
- extract: HTML + FIA PDF extraction
- subjects: regex driver/team/circuit tagger
- ingest: high-level pipeline (URL/PDF -> rows)
- rss: RSS feed poller
- fia_poller: FIA scrutineering document poller
- search: search_editorial_content RPC wrapper
"""


class EditorialUnavailable(RuntimeError):
    """Raised when Supabase env vars are missing or the editorial DB is unreachable."""
