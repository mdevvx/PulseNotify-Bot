-- PulseNotify: 0002_core_schema
--
-- Adds the tables needed to configure per-guild monitored accounts,
-- notification routing, alert preferences, event deduplication, and
-- live-stream state, plus one platform-level (not guild-scoped) table for
-- tracking API usage/health per external provider.
--
-- No monitoring logic reads or writes these yet (that's Phase 3+); this
-- migration is schema only. Run after 0001_create_guilds.sql.
--
-- Every table is prefixed `pulsenotify_`, matching 0001.

-- ── Shared value domains ─────────────────────────────────────────────
-- Centralizing these as domains (rather than repeating the same CHECK list
-- on every column) means adding a platform or event type later is one
-- ALTER DOMAIN, not a hunt through every table that mentions it.

do $$
begin
    if not exists (select 1 from pg_type where typname = 'platform_t') then
        create domain platform_t as text
            check (value in ('youtube', 'twitch', 'kick', 'twitter', 'instagram', 'facebook', 'tiktok'));
    end if;
end$$;

do $$
begin
    if not exists (select 1 from pg_type where typname = 'event_type_t') then
        -- post_created / video_published / short_published cover the
        -- "new content" side; stream_started / stream_ended / stream_updated
        -- cover live monitoring; account_updated covers profile/channel-level
        -- changes. Platform-specific variants (stories, community posts,
        -- clips, ...) map onto these with details in events.metadata rather
        -- than each getting its own type, until one demonstrably needs to be
        -- filtered/configured independently.
        create domain event_type_t as text
            check (value in (
                'post_created',
                'video_published',
                'short_published',
                'stream_started',
                'stream_ended',
                'stream_updated',
                'account_updated'
            ));
    end if;
end$$;

do $$
begin
    if not exists (select 1 from pg_type where typname = 'account_status_t') then
        -- Distinct from platform_accounts.enabled: `enabled` is the admin's
        -- choice, `status` is what monitoring has observed. An account can be
        -- enabled=true but status='invalid' (e.g. the channel was deleted) —
        -- monitoring stops polling it without silently flipping the admin's
        -- own setting.
        create domain account_status_t as text
            check (value in ('active', 'invalid', 'error'));
    end if;
end$$;

do $$
begin
    if not exists (select 1 from pg_type where typname = 'platform_health_status_t') then
        create domain platform_health_status_t as text
            check (value in ('healthy', 'degraded', 'error', 'disabled'));
    end if;
end$$;

-- ── pulsenotify_bot_settings ─────────────────────────────────────────
-- Guild-wide preferences that apply across every monitored account, as
-- opposed to pulsenotify_alert_configurations below which is per-account.
-- 1:1 with pulsenotify_guilds.

create table if not exists pulsenotify_bot_settings (
    guild_id                 bigint primary key references pulsenotify_guilds (guild_id) on delete cascade,
    default_mention_role_id  bigint,
    embed_color              integer,
    timezone                 text not null default 'UTC',
    created_at               timestamptz not null default now(),
    updated_at               timestamptz not null default now()
);

drop trigger if exists trg_pulsenotify_bot_settings_updated_at on pulsenotify_bot_settings;
create trigger trg_pulsenotify_bot_settings_updated_at
    before update on pulsenotify_bot_settings
    for each row
    execute function pulsenotify_set_updated_at();

alter table pulsenotify_bot_settings enable row level security;

-- ── pulsenotify_platform_accounts ────────────────────────────────────
-- One row per monitored account per guild. Two different guilds watching
-- the same YouTube channel get two independent rows — configuration is
-- never shared across guilds, only the (future) polling layer coalesces
-- the actual API calls for efficiency.

create table if not exists pulsenotify_platform_accounts (
    id                    uuid primary key default gen_random_uuid(),
    guild_id              bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    platform              platform_t not null,
    platform_account_id   text not null,
    username              text not null,
    display_name          text,
    enabled               boolean not null default true,
    status                account_status_t not null default 'active',
    last_checked_at       timestamptz,
    last_error            text,
    consecutive_failures  integer not null default 0,
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now(),

    constraint chk_pulsenotify_platform_accounts_failures_nonneg check (consecutive_failures >= 0),
    -- Referenced by composite foreign keys from child tables below, so a
    -- child row can never point at a (guild_id, account) pair that spans
    -- two different guilds.
    constraint uq_pulsenotify_platform_accounts_guild_id unique (guild_id, id),
    -- Prevents adding the same platform account to a guild twice.
    constraint uq_pulsenotify_platform_accounts_guild_platform_account unique (guild_id, platform, platform_account_id)
);

create index if not exists idx_pulsenotify_platform_accounts_guild on pulsenotify_platform_accounts (guild_id);
-- Lets the (future) scheduler find every guild watching a given platform
-- account without scanning the whole table.
create index if not exists idx_pulsenotify_platform_accounts_platform_lookup on pulsenotify_platform_accounts (platform, platform_account_id);
-- Partial index: the scheduler's hot-path query is "every enabled account",
-- and disabled accounts shouldn't bloat that index.
create index if not exists idx_pulsenotify_platform_accounts_enabled on pulsenotify_platform_accounts (enabled) where enabled = true;

drop trigger if exists trg_pulsenotify_platform_accounts_updated_at on pulsenotify_platform_accounts;
create trigger trg_pulsenotify_platform_accounts_updated_at
    before update on pulsenotify_platform_accounts
    for each row
    execute function pulsenotify_set_updated_at();

alter table pulsenotify_platform_accounts enable row level security;

-- ── pulsenotify_notification_channels ────────────────────────────────
-- A Discord channel registered to receive alerts. is_valid is set false
-- (not deleted) when the bot loses access to the channel, so the admin's
-- account_channels wiring isn't silently lost and the monitor stops
-- retrying a channel that will never succeed.

create table if not exists pulsenotify_notification_channels (
    id          uuid primary key default gen_random_uuid(),
    guild_id    bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    channel_id  bigint not null,
    name        text,
    is_valid    boolean not null default true,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint uq_pulsenotify_notification_channels_guild_id unique (guild_id, id),
    constraint uq_pulsenotify_notification_channels_guild_channel unique (guild_id, channel_id)
);

create index if not exists idx_pulsenotify_notification_channels_guild on pulsenotify_notification_channels (guild_id);

drop trigger if exists trg_pulsenotify_notification_channels_updated_at on pulsenotify_notification_channels;
create trigger trg_pulsenotify_notification_channels_updated_at
    before update on pulsenotify_notification_channels
    for each row
    execute function pulsenotify_set_updated_at();

alter table pulsenotify_notification_channels enable row level security;

-- ── pulsenotify_account_channels ─────────────────────────────────────
-- Routes one account's alerts to one channel. guild_id is denormalized
-- here specifically so the two foreign keys below can be composite
-- (guild_id, ...) — that makes it structurally impossible to link an
-- account from one guild to a channel from another, not just an
-- application-level convention.

create table if not exists pulsenotify_account_channels (
    guild_id    bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    account_id  uuid not null,
    channel_id  uuid not null,
    created_at  timestamptz not null default now(),

    primary key (account_id, channel_id),
    constraint fk_pulsenotify_account_channels_account
        foreign key (guild_id, account_id) references pulsenotify_platform_accounts (guild_id, id) on delete cascade,
    constraint fk_pulsenotify_account_channels_channel
        foreign key (guild_id, channel_id) references pulsenotify_notification_channels (guild_id, id) on delete cascade
);

create index if not exists idx_pulsenotify_account_channels_channel on pulsenotify_account_channels (channel_id);
create index if not exists idx_pulsenotify_account_channels_guild on pulsenotify_account_channels (guild_id);

alter table pulsenotify_account_channels enable row level security;

-- ── pulsenotify_alert_configurations ─────────────────────────────────
-- Per-account, per-event-type notification preferences (section 7's
-- "New Post: ON / Live Started: ON / Role Mention: ON / ..." maps to one
-- row per event_type here).

create table if not exists pulsenotify_alert_configurations (
    id                uuid primary key default gen_random_uuid(),
    guild_id          bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    account_id        uuid not null,
    event_type        event_type_t not null,
    enabled           boolean not null default true,
    mention_role_id   bigint,
    embed_enabled     boolean not null default true,
    custom_message    text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),

    constraint uq_pulsenotify_alert_configurations_account_event unique (account_id, event_type),
    constraint fk_pulsenotify_alert_configurations_account
        foreign key (guild_id, account_id) references pulsenotify_platform_accounts (guild_id, id) on delete cascade
);

create index if not exists idx_pulsenotify_alert_configurations_account on pulsenotify_alert_configurations (account_id);

drop trigger if exists trg_pulsenotify_alert_configurations_updated_at on pulsenotify_alert_configurations;
create trigger trg_pulsenotify_alert_configurations_updated_at
    before update on pulsenotify_alert_configurations
    for each row
    execute function pulsenotify_set_updated_at();

alter table pulsenotify_alert_configurations enable row level security;

-- ── pulsenotify_events ───────────────────────────────────────────────
-- The deduplication ledger described in section 10: before notifying,
-- check whether (account_id, event_type, platform_event_id) has already
-- been recorded. Scoped per-guild (via account_id) rather than globally,
-- matching every other table here — the tradeoff is that two guilds
-- watching the same channel store the event twice, which is preferable to
-- a shared un-scoped table needing its own isolation story.

create table if not exists pulsenotify_events (
    id                 uuid primary key default gen_random_uuid(),
    guild_id           bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    account_id         uuid not null,
    platform           platform_t not null,
    event_type         event_type_t not null,
    platform_event_id  text not null,
    notified           boolean not null default false,
    detected_at        timestamptz not null default now(),
    notified_at        timestamptz,
    metadata           jsonb not null default '{}'::jsonb,

    -- The actual dedup key.
    constraint uq_pulsenotify_events_account_event_platform_id unique (account_id, event_type, platform_event_id),
    constraint fk_pulsenotify_events_account
        foreign key (guild_id, account_id) references pulsenotify_platform_accounts (guild_id, id) on delete cascade
);

create index if not exists idx_pulsenotify_events_guild_detected on pulsenotify_events (guild_id, detected_at desc);

alter table pulsenotify_events enable row level security;

-- ── pulsenotify_live_states ──────────────────────────────────────────
-- Current live/offline status per account (one row per account). Read
-- before firing a STREAM_STARTED event so a bot restart while a streamer
-- is already live doesn't re-announce it (section 8).

create table if not exists pulsenotify_live_states (
    account_id        uuid primary key,
    guild_id          bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    is_live           boolean not null default false,
    current_stream_id text,
    started_at        timestamptz,
    ended_at          timestamptz,
    last_checked_at   timestamptz,
    updated_at        timestamptz not null default now(),

    constraint fk_pulsenotify_live_states_account
        foreign key (guild_id, account_id) references pulsenotify_platform_accounts (guild_id, id) on delete cascade
);

create index if not exists idx_pulsenotify_live_states_guild on pulsenotify_live_states (guild_id);

drop trigger if exists trg_pulsenotify_live_states_updated_at on pulsenotify_live_states;
create trigger trg_pulsenotify_live_states_updated_at
    before update on pulsenotify_live_states
    for each row
    execute function pulsenotify_set_updated_at();

alter table pulsenotify_live_states enable row level security;

-- ── pulsenotify_audit_logs ───────────────────────────────────────────
-- Append-only record of administrative actions (who changed what, when).
-- `action` is intentionally free text rather than a constrained domain —
-- new admin actions get added as commands are built, and that shouldn't
-- require a migration each time.

create table if not exists pulsenotify_audit_logs (
    id          uuid primary key default gen_random_uuid(),
    guild_id    bigint not null references pulsenotify_guilds (guild_id) on delete cascade,
    actor_id    bigint not null,
    action      text not null,
    target      text,
    metadata    jsonb not null default '{}'::jsonb,
    created_at  timestamptz not null default now()
);

create index if not exists idx_pulsenotify_audit_logs_guild_created on pulsenotify_audit_logs (guild_id, created_at desc);

alter table pulsenotify_audit_logs enable row level security;

-- ── pulsenotify_platform_health ──────────────────────────────────────
-- NOT guild-scoped — this is the bot's own credential/quota usage against
-- each external provider, one row per platform regardless of how many
-- guilds or accounts are configured. Backs the API usage manager (request
-- counts, rate-limit/backoff state, quota where the provider exposes it)
-- and the platform-health section of /status.

create table if not exists pulsenotify_platform_health (
    platform                 platform_t primary key,
    status                   platform_health_status_t not null default 'disabled',
    last_success_at          timestamptz,
    last_error_at            timestamptz,
    last_error               text,
    consecutive_failures     integer not null default 0,
    requests_today           integer not null default 0,
    requests_today_reset_at  date not null default current_date,
    rate_limited_until       timestamptz,
    quota_limit              integer,
    quota_remaining          integer,
    updated_at               timestamptz not null default now(),

    constraint chk_pulsenotify_platform_health_failures_nonneg check (consecutive_failures >= 0),
    constraint chk_pulsenotify_platform_health_requests_nonneg check (requests_today >= 0)
);

drop trigger if exists trg_pulsenotify_platform_health_updated_at on pulsenotify_platform_health;
create trigger trg_pulsenotify_platform_health_updated_at
    before update on pulsenotify_platform_health
    for each row
    execute function pulsenotify_set_updated_at();

-- Not guild data, so there's no per-guild access pattern to isolate —
-- still enabled for consistency and because only the service_role key
-- should ever touch this table.
alter table pulsenotify_platform_health enable row level security;
