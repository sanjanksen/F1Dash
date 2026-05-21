-- Widen the articles.doc_type CHECK constraint to allow granular FIA doc types.
-- Also backfill source names for hostnames that newly map to curated display names.

alter table articles drop constraint if exists articles_doc_type_check;
alter table articles add constraint articles_doc_type_check check (
    doc_type in (
        'news',
        'fia_scrutineering',
        'fia_pirelli_preview',
        'fia_stewards',
        'fia_pu_info',
        'fia_post_race_check',
        'fia_competition_visa',
        'press_conference',
        'technical_analysis',
        'other'
    )
);

-- One-off backfill: rows already ingested before SOURCE_FROM_HOST gained these
-- entries carry the raw hostname in `source`. Rewrite to curated display names.
update articles set source = 'Crash.net'         where source in ('crash.net', 'www.crash.net');
update articles set source = 'Total Motorsport'  where source in ('total-motorsport.com', 'www.total-motorsport.com');
update articles set source = 'F1Technical'       where source in ('f1technical.net', 'www.f1technical.net');
