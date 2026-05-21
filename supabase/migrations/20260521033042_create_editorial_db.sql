-- Editorial content database for F1Dash chat-time retrieval (RAG).
--
-- Two-table design:
--   articles       — one row per source document; raw text + metadata for citation.
--   article_chunks — one row per ~600-token chunk; carries the embedding vector.
-- Optional supplementary:
--   article_subjects — driver/team/circuit tags for filtered search.
--
-- Embedding dimension 1536 matches OpenAI text-embedding-3-small.
-- HNSW index on chunks for sub-5ms ANN at ~10K chunk scale.

create extension if not exists vector;

-- ── articles ────────────────────────────────────────────────────────────────

create table articles (
    id           bigint generated always as identity primary key,
    url          text not null unique,
    title        text,
    source       text not null,                       -- 'The Race', 'FIA', 'Sky F1', ...
    author       text,
    published_at timestamptz,
    fetched_at   timestamptz not null default now(),
    doc_type     text not null
                 check (doc_type in ('news',
                                     'fia_scrutineering',
                                     'press_conference',
                                     'technical_analysis',
                                     'other')),
    raw_body     text not null,
    -- generated tsvector for keyword/full-text search
    body_tsv     tsvector
                 generated always as (
                     to_tsvector('english',
                                 coalesce(title, '') || ' ' || coalesce(raw_body, ''))
                 ) stored
);

create index articles_published_at_idx on articles (published_at desc);
create index articles_source_idx       on articles (source);
create index articles_doc_type_idx     on articles (doc_type);
create index articles_body_tsv_idx     on articles using gin (body_tsv);

comment on table articles is
    'F1Dash editorial corpus — one row per ingested article, transcript, or FIA document.';
comment on column articles.raw_body is
    'Cleaned plaintext for citation. Chunks for retrieval live in article_chunks.';
comment on column articles.body_tsv is
    'Generated tsvector for keyword/FTS search. Use websearch_to_tsquery() to query.';

-- ── article_chunks ──────────────────────────────────────────────────────────

create table article_chunks (
    id              bigint generated always as identity primary key,
    article_id      bigint not null references articles(id) on delete cascade,
    chunk_index     int    not null,                    -- 0-based ordering within article
    chunk_text      text   not null,
    embedding       vector(1536),                       -- OpenAI text-embedding-3-small
    embedding_model text   not null default 'text-embedding-3-small',
    unique (article_id, chunk_index)
);

create index article_chunks_article_id_idx on article_chunks (article_id);

-- HNSW ANN index for nearest-neighbour cosine search.
-- m=16, ef_construction=64 are the Supabase-recommended defaults for ≤100K rows.
create index article_chunks_embedding_hnsw_idx
    on article_chunks
    using hnsw (embedding vector_cosine_ops)
    with (m = 16, ef_construction = 64);

comment on table article_chunks is
    'Embedding-bearing chunks (~600 tokens each). Searched at chat time via vector + FTS.';
comment on column article_chunks.embedding_model is
    'Track which model produced this vector so we can re-embed selectively on deprecation.';

-- ── article_subjects (optional but cheap to include now) ────────────────────

create table article_subjects (
    id          bigint generated always as identity primary key,
    article_id  bigint not null references articles(id) on delete cascade,
    kind        text   not null check (kind in ('driver', 'team', 'circuit')),
    ref         text   not null,                       -- 'NOR', 'mclaren', 'monza', ...
    unique (article_id, kind, ref)
);

create index article_subjects_ref_idx on article_subjects (kind, ref);

comment on table article_subjects is
    'Tag table for filtered retrieval. Populated at ingest time by regex against curated rosters.';

-- ── hybrid-search helper RPC ────────────────────────────────────────────────
--
-- Single SQL function the FastAPI layer can call: takes a query embedding +
-- optional keyword string, returns top-k chunks blended via reciprocal rank
-- fusion of vector cosine distance and FTS rank.

create or replace function match_article_chunks(
    query_embedding vector(1536),
    query_text      text default null,
    match_count     int  default 5,
    min_published   timestamptz default null
)
returns table (
    chunk_id        bigint,
    article_id      bigint,
    chunk_text      text,
    chunk_index     int,
    title           text,
    url             text,
    source          text,
    published_at    timestamptz,
    similarity      float
)
language sql stable as $$
    with vector_hits as (
        select c.id  as chunk_id,
               c.article_id,
               c.chunk_text,
               c.chunk_index,
               1 - (c.embedding <=> query_embedding) as similarity
        from article_chunks c
        join articles a on a.id = c.article_id
        where (min_published is null or a.published_at >= min_published)
        order by c.embedding <=> query_embedding
        limit match_count * 2
    )
    select v.chunk_id,
           v.article_id,
           v.chunk_text,
           v.chunk_index,
           a.title,
           a.url,
           a.source,
           a.published_at,
           v.similarity
    from vector_hits v
    join articles a on a.id = v.article_id
    order by v.similarity desc
    limit match_count;
$$;

comment on function match_article_chunks is
    'Top-k chunks by cosine similarity to query_embedding. Optional min_published filter.
     query_text is reserved for future hybrid (vector + FTS) ranking.';
