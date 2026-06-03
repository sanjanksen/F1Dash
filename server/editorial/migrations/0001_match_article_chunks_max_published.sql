-- B5a: add a symmetric max_published upper bound to the hybrid retrieval RPC.
--
-- match_article_chunks already filtered on min_published; multi-year season
-- scoping needs an upper bound too (e.g. exclude 2026 articles from a 2024
-- query). Sending an unknown RPC arg makes PostgREST return [], so the bound
-- MUST exist server-side — the client-side overfetch+post-filter is only a
-- best-effort belt-and-suspenders, not a substitute.
--
-- Adding a parameter changes the function signature, which would create an
-- overload (ambiguous for 4-arg named calls). Drop the old signature first,
-- then recreate with max_published appended (defaults NULL → unchanged
-- behaviour for callers that don't pass it).

DROP FUNCTION IF EXISTS public.match_article_chunks(vector, text, integer, timestamptz);

CREATE OR REPLACE FUNCTION public.match_article_chunks(
    query_embedding vector,
    query_text text DEFAULT NULL::text,
    match_count integer DEFAULT 5,
    min_published timestamp with time zone DEFAULT NULL::timestamp with time zone,
    max_published timestamp with time zone DEFAULT NULL::timestamp with time zone
)
 RETURNS TABLE(chunk_id bigint, article_id bigint, chunk_text text, chunk_index integer, title text, url text, source text, published_at timestamp with time zone, similarity double precision)
 LANGUAGE sql
 STABLE
AS $function$
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
          and (max_published is null or a.published_at <= max_published)
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
          and (max_published is null or a.published_at <= max_published)
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
$function$;
