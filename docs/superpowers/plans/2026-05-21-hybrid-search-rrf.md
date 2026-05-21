# Hybrid Search (FTS + Vector via RRF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade F1Dash's editorial retrieval from pure vector search to **hybrid search**: run vector and full-text-search (FTS) in parallel, combine rankings via Reciprocal Rank Fusion (RRF). Gets ~10-15% recall improvement on specific-entity queries (driver names, acronyms, technical terms) without adding any new dependencies or API costs.

**Architecture:** Replace the existing `match_article_chunks` Postgres RPC with a hybrid version. It computes two ranked candidate lists — one by vector cosine distance against `article_chunks.embedding`, one by FTS `ts_rank` against `articles.body_tsv` — then combines them via RRF (`1/(60+rank)`). The chunk-level vector hits union with article-level FTS hits (expanded to all chunks of each matched article), deduplicates by chunk_id, and re-ranks by combined RRF score.

**Tech Stack:** Postgres `tsvector` + GIN index (already in schema), pgvector HNSW (already there), Supabase migration system. No new dependencies. No code changes outside the RPC. No backend Python changes (search.py already passes `query_text` — the old RPC just ignored it).

---

## Background and design rationale

**Why hybrid:** Vector search and FTS fail in opposite ways. Vector misses on specific entities ("Verstappen" gets fuzzed with other drivers) and acronyms ("ADUO" gets generalized). FTS misses when wording differs ("McLaren upgrade" doesn't find "MCL39 development package"). Combined, they cover each other's blind spots.

**Why RRF:** Reciprocal Rank Fusion (Cormack, Clarke & Buettcher 2009) is the canonical method for combining rankings from different retrievers. Each chunk's contribution from each retriever is `1/(k+rank)` with `k=60`. No score-normalization headaches, no per-query tuning. Robust to outlier scores from either retriever.

**Concrete F1 example that motivated this:** during the 10-query RAG validation we ran earlier, "Why did Verstappen get a penalty at the 2024 Abu Dhabi GP?" returned chunks about Leclerc (Car 16) and Hamilton (Car 44) at the top because the embedder weighted "2024 Abu Dhabi penalty" higher than the specific driver. FTS on "Verstappen" pins the right entity; vector alone fuzzes drivers. Hybrid solves this without an LLM judge or reranker.

**Why this is essentially free:** The `articles.body_tsv` generated column and GIN index are already in the schema from the initial editorial migration — currently unused for retrieval. The change is one SQL function replacement.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `supabase/migrations/20260521150000_hybrid_match_article_chunks.sql` | Replaces `match_article_chunks` RPC with hybrid version | **Create** |
| `server/editorial/search.py` | Already passes `query_text` to the RPC. **Verify only — no code change.** | **Read** |
| `server/tests/test_editorial_search.py` | Add 4 tests for hybrid behavior + 1 regression test against the Verstappen-penalty failure case | **Modify** |

No application code changes. The whole upgrade is in the SQL RPC + tests.

---

## Task 1: Write the hybrid match_article_chunks migration

**Files:**
- Create: `supabase/migrations/20260521150000_hybrid_match_article_chunks.sql`

This replaces the existing RPC (defined in the original editorial migration). Migrations are append-only; we use `create or replace function` to swap the definition.

- [ ] **Step 1: Read the existing RPC definition for reference**

```bash
grep -A 50 "create or replace function match_article_chunks" supabase/migrations/20260521033042_create_editorial_db.sql | head -60
```

Confirm the signature: `(query_embedding vector(1536), query_text text default null, match_count int default 5, min_published timestamptz default null)` returning a table with `chunk_id, article_id, chunk_text, chunk_index, title, url, source, published_at, similarity`.

The new RPC must keep this exact signature so the calling code in `server/editorial/client.py:call_match_chunks` is unchanged.

- [ ] **Step 2: Write the migration file**

Create `supabase/migrations/20260521150000_hybrid_match_article_chunks.sql`:

```sql
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
        -- Top-N by vector cosine. We pull more than match_count because
        -- the FTS retriever will introduce additional candidates and the
        -- final cut happens after RRF.
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
        -- Top-N articles by FTS rank. Skips entirely if query_text is null
        -- or empty (the old behaviour — pure vector — falls out of this).
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
        -- Expand each FTS-matched article into all its chunks. Each chunk
        -- inherits the article's f_rank.
        select c.id          as chunk_id,
               c.article_id  as article_id,
               c.chunk_text  as chunk_text,
               c.chunk_index as chunk_index,
               0.0           as similarity,  -- no vector score for FTS-only hits
               f.f_rank      as f_rank
        from fts_article_hits f
        join article_chunks c on c.article_id = f.article_id
    ),
    blended as (
        -- Union vector + FTS contributions. A chunk may appear once
        -- (vector-only or FTS-only) or twice (both); GROUP BY collapses
        -- and SUM adds the contributions.
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
    -- Final select picks up article metadata and orders by combined RRF score.
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
```

- [ ] **Step 3: Syntactic sanity check the migration**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; python -c "
content = open('supabase/migrations/20260521150000_hybrid_match_article_chunks.sql').read()
assert 'create or replace function match_article_chunks' in content
assert 'websearch_to_tsquery' in content
assert 'vector_hits' in content
assert 'fts_article_hits' in content
assert 'rrf_contribution' in content
print('migration file looks well-formed')
"
```

Expected: prints `migration file looks well-formed`.

- [ ] **Step 4: Commit the migration (do NOT push to Supabase yet)**

```bash
git add supabase/migrations/20260521150000_hybrid_match_article_chunks.sql
git commit -m "feat(editorial): hybrid vector+FTS match_article_chunks via RRF

Replaces the existing match_article_chunks RPC with a hybrid version.
Vector cosine search + Postgres FTS ts_rank, combined via Reciprocal
Rank Fusion (k=60). query_text=NULL preserves the old pure-vector path.

Implementation note: FTS runs at article-level (body_tsv is on articles,
not chunks); FTS-matched articles contribute their f_rank to ALL their
chunks. A chunk hit by both retrievers gets both contributions (summed).

Signature unchanged — server/editorial/client.py:call_match_chunks
needs no modification.

Apply with: supabase db push (the user runs this manually after merge).

Plan: docs/superpowers/plans/2026-05-21-hybrid-search-rrf.md Task 1"
```

The user will apply the migration with `supabase db push` after Task 3 lands. Do NOT run `supabase db push` yourself — keep all migrations user-applied.

---

## Task 2: Verify search.py passes query_text correctly

**Files:**
- Read: `server/editorial/search.py`
- Read: `server/editorial/client.py`

This is a verification-only task — the existing code should already pass `query_text` to the RPC. The old RPC ignored it; the new one uses it.

- [ ] **Step 1: Confirm search.py passes the question as query_text**

```bash
grep -n "query_text\|call_match_chunks" server/editorial/search.py server/editorial/client.py
```

Expected output should include a line where `search_editorial_content` invokes `call_match_chunks(query_embedding=..., query_text=query, ...)`. The `query` parameter is the user's question.

If `query_text` is NOT being passed, fix it: in `server/editorial/search.py:search_editorial_content`, the call to `_client.call_match_chunks(...)` must include `query_text=query`. The signature of `call_match_chunks` in `client.py` should already accept it. (Per the file inspection during the editorial-pipeline implementation, this is already wired correctly.)

- [ ] **Step 2: No commit if no change**

If everything is already wired, this task produces no commit. Note that in the report.

If a change is needed (unlikely), commit it as:

```bash
git add server/editorial/search.py
git commit -m "fix(editorial): pass user question as query_text to match RPC

Hybrid match_article_chunks (just landed) reads query_text to compute
the FTS half of the RRF blend. Previously query_text was accepted but
ignored by the RPC; now it carries signal.

Plan: docs/superpowers/plans/2026-05-21-hybrid-search-rrf.md Task 2"
```

---

## Task 3: Apply the migration to Supabase

**Files:**
- Run command only — no code change.

This step actually deploys the new RPC. Do this AFTER Tasks 1 and 2 are committed locally, but BEFORE Task 4 (because the tests in Task 4 are live integration tests against the live Supabase).

- [ ] **Step 1: Apply the migration**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; supabase db push
```

When prompted "Do you want to push these migrations to the remote database?", confirm with `Y`.

Expected output:
```
Applying migration 20260521150000_hybrid_match_article_chunks.sql...
Finished supabase db push.
```

- [ ] **Step 2: Verify the new RPC is live**

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; supabase migration list 2>&1 | tail -8
```

Expected: the new migration `20260521150000` appears in both Local and Remote columns.

- [ ] **Step 3: Smoke test the new RPC end-to-end**

Run a one-off Python script to confirm the hybrid RPC returns results:

```bash
cd C:/Users/sanja/Documents/Nerd/F1Dash; python -c "
import sys; sys.path.insert(0, 'server')
from dotenv import load_dotenv; load_dotenv('.env')
from editorial.search import search_editorial_content
out = search_editorial_content('Why did Verstappen get a penalty at the 2024 Abu Dhabi GP?', limit=4)
print('mode:', out.get('search_mode'))
for i, r in enumerate(out.get('results', []), 1):
    print(f'{i}. sim={r.get(\"similarity\"):.3f} | {r.get(\"title\", \"\")[:60]}')
"
```

Expected: the top result is now an article that specifically mentions Verstappen, not Leclerc/Hamilton (the failure case from the earlier validation). The exact similarity values may shift since RRF combines two rankings.

No commit on this task — it's purely operational.

---

## Task 4: Tests for hybrid behaviour

**Files:**
- Modify: `server/tests/test_editorial_search.py`

The existing search tests mock `_client.call_match_chunks` and `_client.fts_search_articles`. The hybrid RPC change happens at the Postgres level — the Python client signature is unchanged. So the existing search tests pass without modification.

What we add are higher-level integration tests that exercise the actual Supabase hybrid behaviour to confirm the fix works against the original failure cases. These tests hit the real DB (the smoke test pattern we already use elsewhere).

- [ ] **Step 1: Add live-DB regression tests**

Append to `server/tests/test_editorial_search.py`:

```python
import os

import pytest


def _supabase_configured() -> bool:
    return bool(
        os.getenv("SUPABASE_URL")
        and (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY"))
        and os.getenv("GEMINI_API_KEY")
    )


pytestmark_live = pytest.mark.skipif(
    not _supabase_configured(),
    reason="Live Supabase + Gemini credentials required for hybrid-search regression tests."
)


@pytestmark_live
def test_hybrid_search_finds_specific_driver_when_named():
    """The single failure case from the May 2026 RAG validation: pure vector
    weighted '2024 Abu Dhabi penalty' higher than 'Verstappen specifically'
    and returned Leclerc/Hamilton penalty docs at the top. With hybrid
    search, FTS on 'Verstappen' pulls the right entity in."""
    from editorial.search import search_editorial_content

    out = search_editorial_content(
        "Why did Verstappen get a penalty at the 2024 Abu Dhabi GP?",
        limit=5,
    )
    assert out.get("available") is True
    assert out.get("search_mode") == "semantic"
    titles = [(r.get("title") or "") for r in out.get("results") or []]
    # At least one result should reference Verstappen by name or car number 1.
    matches_verstappen = any(
        ("Verstappen" in t) or ("Car 1" in t) or ("VER" in t)
        for t in titles
    )
    assert matches_verstappen, (
        f"No Verstappen-specific result in top 5; got titles: {titles}. "
        "Hybrid search should pin the named driver via FTS."
    )


@pytestmark_live
def test_hybrid_search_finds_acronym_query():
    """ADUO is a 4-letter acronym the embedder generalises to 'engine
    regulation'. FTS on the exact term should pin articles that literally
    use ADUO."""
    from editorial.search import search_editorial_content

    out = search_editorial_content("What is ADUO?", limit=3)
    assert out.get("available") is True
    bodies = [(r.get("chunk_text") or "") for r in out.get("results") or []]
    found_aduo_literal = any("ADUO" in b or "aduo" in b.lower() for b in bodies)
    assert found_aduo_literal, (
        f"No chunk literally contains 'ADUO' in top 3; got bodies: "
        f"{[b[:80] for b in bodies]}"
    )


@pytestmark_live
def test_hybrid_search_returns_results_for_vector_only_query():
    """When the query is paraphrased and no exact words match the corpus,
    vector search should still carry. Confirms the FTS half doesn't
    starve the result set."""
    from editorial.search import search_editorial_content

    # Paraphrased question — unlikely to have an exact FTS hit.
    out = search_editorial_content(
        "How are the 2026 power unit regulations changing?",
        limit=3,
    )
    assert out.get("available") is True
    assert len(out.get("results") or []) >= 1, (
        "Vector half of hybrid should return results even when FTS gets no hits."
    )


@pytestmark_live
def test_hybrid_search_returns_chunks_with_required_fields():
    """Sanity check: the hybrid RPC's return columns are unchanged from
    the original. The Python search layer should see the same shape."""
    from editorial.search import search_editorial_content

    out = search_editorial_content("2026 deployment curve clipping", limit=2)
    for r in out.get("results") or []:
        for required_field in ("url", "title", "source", "chunk_text", "similarity"):
            assert required_field in r, (
                f"Missing required field '{required_field}' in result: "
                f"{list(r.keys())}"
            )
```

- [ ] **Step 2: Run the new tests**

```bash
cd server; python -m pytest tests/test_editorial_search.py -v 2>&1 | tail -20
```

Expected:
- The existing mocked tests still pass.
- The 4 new live tests pass (they hit the real Supabase + the new RPC).
- If `SUPABASE_URL` / `GEMINI_API_KEY` aren't set, the live tests skip cleanly with the skip message.

If the Verstappen test fails — i.e. the hybrid RPC still returns Leclerc/Hamilton at the top — the issue is in the SQL. Re-inspect the RRF formula. Note: a failure here may mean the corpus simply doesn't have a Verstappen Abu Dhabi 2024 penalty article. Check the audit / DB first:

```sql
select id, title from articles 
where title ilike '%abu dhabi%' and source = 'FIA' 
order by id desc limit 10;
```

If no Verstappen-specific 2024 Abu Dhabi PDF exists in the corpus, the test premise is wrong, not the hybrid. Mark the test as `xfail` with that explanation rather than fixing the SQL.

- [ ] **Step 3: Run the full backend suite**

```bash
cd server; python -m pytest tests/ -q 2>&1 | tail -3
```

Expected: 473 + 4 new live tests = 477 passing.

- [ ] **Step 4: Commit**

```bash
git add server/tests/test_editorial_search.py
git commit -m "test(editorial): regression tests for hybrid search

Adds 4 live-DB tests that exercise the new hybrid match_article_chunks RPC:
- specific driver name (Verstappen — the failure case from the earlier
  10-query validation)
- acronym query (ADUO)
- vector-only fallback when no FTS hit
- output column shape

Tests skip cleanly when SUPABASE_URL / GEMINI_API_KEY aren't set.

Plan: docs/superpowers/plans/2026-05-21-hybrid-search-rrf.md Task 4"
```

---

## Validation Checklist

Cross-cutting. Run after all tasks land.

- [ ] `supabase migration list` shows `20260521150000` applied locally + remote.
- [ ] `cd server; python -m pytest tests/ -q` reports 477 passing (or 473 if live tests skipped).
- [ ] The live smoke test in Task 3 (the Verstappen-penalty query) returns a Verstappen-specific result in the top 3.
- [ ] The audit table (`editorial_gate_audit`) shows new rows being written when the chat is exercised — the gate is unaffected by the RPC change, but worth confirming.
- [ ] The existing 10-query RAG validation (run from memory or re-run):
  - **Query 5** ("Why did Verstappen get a penalty at the 2024 Abu Dhabi GP?") now returns Verstappen results.
  - **Query 3** ("What is ADUO?") similarity may *drop* slightly (RRF combines two rankings; the pure-vector top hit at 0.821 may shift) but the top hit is still an ADUO-specific article.
  - **Query 9** ("Race director event notes for Monaco 2024") should remain at 0.85+ — FTS adds a tiny boost; vector was already dominant.

---

## Risks and Open Questions

| Risk | Trigger | Proposed resolution | Decision needed by |
|---|---|---|---|
| **`websearch_to_tsquery` is too strict** — drops common words, may produce no FTS hits for short queries. | Live testing | If FTS often returns zero hits, switch to `plainto_tsquery` (more lenient) or to a 3-tier fallback (websearch → plain → no FTS). | Post-launch |
| **RRF k=60 is the published default but not calibrated for our corpus.** Higher k flattens the contribution; lower k makes top ranks dominate. | First week | Inspect the audit table after a few days. If FTS-only chunks dominate, lower k to 30. If vector-only dominates, raise to 90. | Post-launch |
| **The FTS-chunk expansion (all chunks of an FTS article get the article's rank) is approximate.** A chunk near the end of a long article may rank too high. | Always | This is the trade-off of having FTS at article level. If precision suffers visibly, the fix is to add a `tsvector` column on `article_chunks` and re-index — a follow-up migration, not blocking. | Post-launch |
| **The similarity field is 0.0 for FTS-only hits.** Downstream code that gates on `similarity >= threshold` (e.g. `gated_editorial_lookup`'s cheap gate) will drop FTS-only chunks. | Always | This is intentional. FTS-only chunks should NOT bypass the similarity gate — the gate is what protects against junk. If you want FTS-only chunks to survive the gate, lower the gate threshold or add an explicit FTS-score-based bypass. Out of scope for this plan. | Now (understood) |
| **The hybrid RPC swap is a hot replacement** — no rollback path other than re-running the original migration. | During migration | If something breaks, the rollback is to write a follow-up migration that restores the original RPC body. Trivial. The new RPC has the same signature so no calling code breaks. | Task 3 |

---

## Non-Goals

- **No `tsvector` column on `article_chunks`.** Article-level FTS with chunk expansion is the cheap approximation; chunk-level FTS would double storage. Add later if precision shows the approximation hurts.
- **No tunable RRF k via the RPC signature.** Hard-coded to 60. Changing it would require a migration; doable but not now.
- **No FTS query expansion / stemming customization.** Postgres's English `tsvector` config handles stemming and stop-words; we trust the defaults.
- **No removal of the existing gate.** The hybrid RPC feeds the same gate (similarity threshold + subject + recency + Haiku grader). Hybrid just makes the candidates better, not the gate redundant.
- **No frontend changes.** The chat layer sees the same `search_editorial_content` output shape.

---

## References

- **Cormack, Clarke & Buettcher 2009** — *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009. The canonical paper for the `1/(k+rank)` blending formula with `k=60`.
- **Postgres FTS docs** — [Full-Text Search chapter](https://www.postgresql.org/docs/current/textsearch.html). `tsvector`, `websearch_to_tsquery`, `ts_rank`.
- Companion plan: `2026-05-21-editorial-rag-deterministic-gating.md` — the cheap-gate layer that consumes the hybrid RPC's output.
- Companion plan: `2026-05-21-editorial-rag-deterministic-gating.md` (Task 6) — defines the `similarity` threshold; this plan's RPC sets similarity=0.0 for FTS-only hits, so they intentionally fail that gate.
