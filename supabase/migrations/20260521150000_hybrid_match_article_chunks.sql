-- Replace match_article_chunks with a hybrid (vector + FTS) version.
--
-- Old behaviour: pure vector cosine search against article_chunks.embedding.
--                query_text was accepted but ignored.
-- New behaviour: vector + FTS in parallel, ranks combined via Reciprocal
--                Rank Fusion (Cormack, Clarke & Buettcher 2009). k=60 is
--                the standard RRF constant — robust, no tuning needed.
--
-- FTS runs at the article level (body_tsv is on articles, not chunks); for
-- each FTS-matched article, ALL its chunks contribute the article's FTS
-- rank to the RRF score. A chunk hit by both retrievers gets both
-- contributions (summed). The output column order and types match the
-- original RPC so server/editorial/client.py:call_match_chunks is unchanged.

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
        select c.id            as chunk_id,
               c.article_id    as article_id,
               c.chunk_text    as chunk_text,
               c.chunk_index   as chunk_index,
               1.0 - (c.embedding <=> query_embedding) as similarity,
               row_number() over (order by c.embedding <=> query_embedding) as v_rank
        from article_chunks c
        join articles a on a.id = c.article_id
        where (min_published is null or a.published_at >= min_published)
        order by c.embedding <=> query_embedding
        limit match_count * 4
    ),
    fts_article_hits as (
        select a.id as article_id,
               row_number() over (order by ts_rank(a.body_tsv, websearch_to_tsquery('english', query_text)) desc) as f_rank
        from articles a
        where query_text is not null
          and length(trim(query_text)) > 0
          and a.body_tsv @@ websearch_to_tsquery('english', query_text)
          and (min_published is null or a.published_at >= min_published)
        order by ts_rank(a.body_tsv, websearch_to_tsquery('english', query_text)) desc
        limit match_count * 4
    ),
    fts_chunks as (
        select c.id          as chunk_id,
               c.article_id  as article_id,
               c.chunk_text  as chunk_text,
               c.chunk_index as chunk_index,
               0.0           as similarity,
               f.f_rank      as f_rank
        from fts_article_hits f
        join article_chunks c on c.article_id = f.article_id
    ),
    blended as (
        select chunk_id, article_id, chunk_text, chunk_index, similarity,
               sum(rrf_contribution) as rrf_score
        from (
            select chunk_id, article_id, chunk_text, chunk_index, similarity,
                   1.0 / (60 + v_rank) as rrf_contribution
            from vector_hits
            union all
            select chunk_id, article_id, chunk_text, chunk_index, similarity,
                   1.0 / (60 + f_rank) as rrf_contribution
            from fts_chunks
        ) all_hits
        group by chunk_id, article_id, chunk_text, chunk_index, similarity
    )
    select b.chunk_id,
           b.article_id,
           b.chunk_text,
           b.chunk_index,
           a.title,
           a.url,
           a.source,
           a.published_at,
           b.similarity
    from blended b
    join articles a on a.id = b.article_id
    order by b.rrf_score desc
    limit match_count;
$$;

comment on function match_article_chunks is
    'Hybrid retrieval: vector cosine + FTS via Reciprocal Rank Fusion (RRF, k=60).
     query_text=NULL falls back to pure vector. similarity column is the vector
     cosine for chunks that had a vector hit, 0.0 for FTS-only chunks.';
