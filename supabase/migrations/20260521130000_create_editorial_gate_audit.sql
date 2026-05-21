-- Audit log for the editorial RAG relevance gate.
--
-- Every call to gated_editorial_lookup writes one row here, recording what
-- the gate considered and what it chose to keep. Lets us inspect false
-- negatives (relevant chunks dropped) without instrumenting the chat layer.

create table editorial_gate_audit (
    id              bigint generated always as identity primary key,
    created_at      timestamptz not null default now(),
    question        text not null,
    analysis_mode   text not null,
    resolver_subjects jsonb,           -- snapshot of resolver entity set
    candidate_count int not null,      -- how many chunks came back from pgvector
    kept_count      int not null,      -- how many survived the gate
    threshold_used  float8,            -- the similarity threshold applied
    dropped         jsonb,             -- [{chunk_id, reason, similarity, age_days}]
    kept_chunk_ids  jsonb              -- [chunk_id, ...]
);

create index editorial_gate_audit_created_at_idx
    on editorial_gate_audit (created_at desc);
create index editorial_gate_audit_mode_idx
    on editorial_gate_audit (analysis_mode);

comment on table editorial_gate_audit is
    'Records each gate decision so we can audit false negatives — relevant
     chunks dropped by the cheap (threshold + subject + recency) filter.
     Inspect periodically; prune rows older than 90 days.';
