-- PulseNotify: 0001_create_guilds
--
-- Foundation table: one row per Discord server the bot is in, tracking
-- only its enabled/disabled state for now. Accounts, notification
-- channels, alert configs, events and live-stream state land in later
-- migrations as those phases are built.
--
-- Run this in the Supabase SQL editor, or via `supabase db push` /
-- `supabase migration up` if you're using the Supabase CLI.
--
-- Every table in this project is prefixed `pulsenotify_` so it's
-- unambiguous at a glance in a shared Supabase project which tables
-- belong to this bot.

create table if not exists pulsenotify_guilds (
    guild_id   bigint primary key,
    enabled    boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_pulsenotify_guilds_enabled on pulsenotify_guilds (enabled);

create or replace function pulsenotify_set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_pulsenotify_guilds_updated_at on pulsenotify_guilds;
create trigger trg_pulsenotify_guilds_updated_at
    before update on pulsenotify_guilds
    for each row
    execute function pulsenotify_set_updated_at();

-- The bot only ever talks to Supabase with the service_role key (server
-- side, never exposed to end users), which bypasses RLS. RLS is still
-- enabled here as defense-in-depth in case a lower-privileged key is ever
-- used against this project.
alter table pulsenotify_guilds enable row level security;
