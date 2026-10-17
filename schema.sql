-- ===========================================================================
-- Rishi-OS -- Supabase / PostgreSQL schema
--
-- The single datahouse. Seven tables, no local state.
-- Run this in the Supabase SQL editor, or via `psql`.
--
-- Column names here must match `core/db.py` exactly. If you rename a column
-- in one place, rename it in the other.
--
-- SECURITY NOTE
--   Row Level Security is intentionally NOT enabled below, because Rishi-OS
--   is a single-operator system and the Control Room uses the anon/service key
--   directly. If you ever expose this project publicly, enable RLS and add
--   policies BEFORE doing so -- see the commented block at the end.
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- 1. agents -- the roster registry (drives core/caps.py)
-- ---------------------------------------------------------------------------
create table if not exists agents (
    name        text primary key,
    purpose     text,
    enabled     boolean     not null default false,
    daily_cap   integer     not null default 1,
    runs_today  integer     not null default 0,
    schedule    text,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 2. tasks -- queued units of work (written by dashboard or poller)
-- ---------------------------------------------------------------------------
create table if not exists tasks (
    id          uuid primary key default gen_random_uuid(),
    agent       text        not null,
    payload     jsonb       not null default '{}'::jsonb,
    status      text        not null default 'queued',
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 3. outputs -- generated content. raw AND clean, always.
-- ---------------------------------------------------------------------------
create table if not exists outputs (
    id          uuid primary key default gen_random_uuid(),
    agent       text        not null,
    brand       text,
    raw         text,
    clean       text,
    hash        text,
    source_url  text,
    model       text,
    provider    text,
    status      text        not null default 'draft',
    meta        jsonb       not null default '{}'::jsonb,
    created_at  timestamptz not null default now(),
    constraint outputs_status_check check (
        status in ('draft','needs_review','approved','rejected','failed','skipped')
    )
);

-- ---------------------------------------------------------------------------
-- 4. logs -- append-only run telemetry
-- ---------------------------------------------------------------------------
create table if not exists logs (
    id          uuid primary key default gen_random_uuid(),
    agent       text        not null,
    time        timestamptz not null default now(),
    status      text,
    model       text,
    provider    text,
    calls       integer     not null default 0,
    notes       text,
    duration_ms integer
);

-- ---------------------------------------------------------------------------
-- 5. brands -- voice and audience profiles
-- ---------------------------------------------------------------------------
create table if not exists brands (
    key         text primary key,
    name        text,
    voice       text,
    audience    text,
    platforms   text,
    always      text,
    never       text,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 6. usage -- the zero-budget ledger
-- ---------------------------------------------------------------------------
create table if not exists usage (
    id          uuid primary key default gen_random_uuid(),
    agent       text        not null,
    provider    text,
    model       text,
    calls       integer     not null default 0,
    chars_in    integer     not null default 0,
    chars_out   integer     not null default 0,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- 7. notes -- journal, ideas, decisions
-- ---------------------------------------------------------------------------
create table if not exists notes (
    id          uuid primary key default gen_random_uuid(),
    brand       text,
    kind        text        not null default 'note',
    body        text        not null,
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Indexes for the lookups the code actually performs
-- ---------------------------------------------------------------------------
create index if not exists outputs_hash_idx       on outputs (hash);
create index if not exists outputs_url_idx        on outputs (source_url);
create index if not exists outputs_agent_idx      on outputs (agent, created_at desc);
create index if not exists outputs_status_idx     on outputs (status);
create index if not exists logs_time_idx          on logs (time desc);
create index if not exists logs_agent_idx         on logs (agent);
create index if not exists usage_created_idx      on usage (created_at desc);
create index if not exists tasks_agent_status_idx on tasks (agent, status);

-- ---------------------------------------------------------------------------
-- Daily counter reset, called by .github/workflows/daily.yml
-- ---------------------------------------------------------------------------
create or replace function reset_daily_counters()
returns void
language sql
as $$
    update agents set runs_today = 0;
$$;

-- ---------------------------------------------------------------------------
-- Seed: the 7-agent roster. Disabled by default -- turn on from the dashboard.
-- ---------------------------------------------------------------------------
insert into agents (name, purpose, enabled, daily_cap, schedule) values
    ('research_agent',     'Find fresh, deduped signal on a topic',        false, 1, 'daily'),
    ('growth_coach_agent', 'Personal progress and habit coaching',         false, 1, 'daily'),
    ('summarize_librarian','Compress long-form input into a library entry',false, 6, 'every-20-min'),
    ('idea_strategist',    'Turn signal into ranked content angles',       false, 1, 'daily'),
    ('packaging_studio',   'Draft platform-ready posts from one angle',    false, 1, 'daily'),
    ('analytics_auditor',  'Read metrics, report what worked',             false, 1, 'daily'),
    ('ceo_supervisor',     'Weekly cross-agent review and prioritisation', false, 1, 'weekly')
on conflict (name) do nothing;

-- ---------------------------------------------------------------------------
-- Seed: brand profiles
-- ---------------------------------------------------------------------------
insert into brands (key, name, voice, audience, platforms, always, never) values
    ('edivic',   'EDIVIC',
     'direct and technical; explains the mechanism, not the hype',
     'technical founders and operators evaluating AI tooling',
     'linkedin, x, newsletter',
     'concrete numbers, working examples, plain language',
     'buzzwords, unsupported claims, engagement bait'),
    ('nowrides', 'NowRides',
     'warm and practical; speaks to operators, not investors',
     'mobility operators and small fleet owners',
     'linkedin, x, newsletter',
     'real operational detail, cost per unit, plain language',
     'hype, vanity metrics, jargon'),
    ('personal', 'Rishi (personal)',
     'first-person, honest, builds in public, admits what broke',
     'founders and builders following the journey',
     'x, linkedin, newsletter',
     'specific lessons, real numbers, one clear takeaway',
     'guru tone, fake certainty, emoji walls')
on conflict (key) do nothing;

-- ---------------------------------------------------------------------------
-- OPTIONAL HARDENING -- enable only after adding policies
-- ---------------------------------------------------------------------------
-- alter table agents  enable row level security;
-- alter table tasks   enable row level security;
-- alter table outputs enable row level security;
-- alter table logs    enable row level security;
-- alter table brands  enable row level security;
-- alter table usage   enable row level security;
-- alter table notes   enable row level security;
