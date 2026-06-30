-- ===========================================================
--  Trading Journal — Datenbank-Struktur (Supabase / Postgres)
--  Einzelnutzer. Zugriff nur server-seitig über den Service-Key.
--  In Supabase: SQL Editor -> New query -> einfügen -> Run.
-- ===========================================================

create table if not exists accounts (
  id         bigint generated always as identity primary key,
  name       text not null,
  currency   text default 'EUR',
  created_at timestamptz default now()
);

create table if not exists trades (
  id             bigint generated always as identity primary key,
  account_id     bigint references accounts(id) on delete cascade,
  created_at     timestamptz default now(),
  closed_at      date,
  symbol         text,
  direction      text,                 -- 'Long' / 'Short'
  entry_price    numeric,
  exit_price     numeric,
  stop_price     numeric,
  quantity       numeric,              -- Lots / Größe
  pnl            numeric,
  pnl_r          numeric,
  pips           numeric,
  setup          text,
  mistakes       jsonb default '[]'::jsonb,
  emotion        text,
  rating         int,
  rules_followed jsonb default '[]'::jsonb,
  reason_entry   text,                 -- Reflexion: warum eingestiegen
  reason_exit    text,                 -- Reflexion: warum/wie geschlossen
  management     text,                 -- Reflexion: wie gemanaged
  notes          text,
  ai_setup       int,
  ai_exec        int,
  ai_psych       int,
  ai_weakness    text,
  ai_tip         text,
  image_path     text
);

create table if not exists app_lists (
  name  text primary key,             -- 'setups' | 'mistakes' | 'rules'
  items jsonb default '[]'::jsonb
);

create table if not exists coach_profile (
  id      int primary key default 1,
  content text default ''
);

-- Sicherheit: RLS an, KEINE öffentlichen Policies.
-- Dadurch kommt nur der server-seitige Service-Key (in den Streamlit-Secrets)
-- an die Daten — der öffentliche anon-Key nicht.
alter table accounts      enable row level security;
alter table trades        enable row level security;
alter table app_lists     enable row level security;
alter table coach_profile enable row level security;
