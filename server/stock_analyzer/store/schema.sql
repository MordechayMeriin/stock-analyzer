-- State store schema for the Postgres backend (state-store spec, design D3/D4).
-- Idempotent: safe to run again on a database that already has it; existing rows are kept.
-- Apply with:  stock-analyzer db init   (reads DATABASE_URL)

create schema if not exists stock_analyzer;

-- Provider ("fr") and LLM ("llm") response caches. Permanent; refresh overwrites.
create table if not exists stock_analyzer.kv_cache (
    namespace  text        not null check (namespace in ('fr', 'llm')),
    key        text        not null,
    value      jsonb       not null,
    updated_at timestamptz not null default now(),
    primary key (namespace, key)
);

-- Fetched report Markdown (exact text) and its metadata, one row per ticker and fiscal year.
create table if not exists stock_analyzer.reports (
    ticker      text        not null,
    fiscal_year integer     not null,
    filing_id   bigint      not null,
    meta        jsonb       not null,
    text        text        not null,
    fetched_at  timestamptz not null,
    primary key (ticker, fiscal_year)
);

-- Financials as fetched (with and without revisions), kept as a snapshot per ticker.
create table if not exists stock_analyzer.financials_snapshots (
    ticker     text        not null,
    revisions  boolean     not null,
    data       jsonb       not null,
    fetched_at timestamptz not null default now(),
    primary key (ticker, revisions)
);

-- Append-only usage log: one record per provider or LLM call (cache hits included).
create table if not exists stock_analyzer.usage_log (
    id     bigint generated always as identity primary key,
    ts     timestamptz not null default now(),
    source text        not null check (source in ('fr', 'llm')),
    record jsonb       not null
);
create index if not exists usage_log_source_idx on stock_analyzer.usage_log (source);

-- Keep the state private (design D4). The server connects as the owner role, which bypasses
-- RLS; with RLS on and no policies, any other role sees nothing even if granted access.
alter table stock_analyzer.kv_cache             enable row level security;
alter table stock_analyzer.reports              enable row level security;
alter table stock_analyzer.financials_snapshots enable row level security;
alter table stock_analyzer.usage_log            enable row level security;

-- Supabase's API roles get no access to this schema. (Skipped where the roles do not exist,
-- e.g. a plain local Postgres.)
do $$
declare
    r text;
begin
    foreach r in array array['anon', 'authenticated'] loop
        if exists (select 1 from pg_roles where rolname = r) then
            execute format('revoke all on schema stock_analyzer from %I', r);
            execute format('revoke all on all tables in schema stock_analyzer from %I', r);
            execute format('alter default privileges in schema stock_analyzer revoke all on tables from %I', r);
        end if;
    end loop;
end
$$;
