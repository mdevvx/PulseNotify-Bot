# PulseNotify

A multi-tenant Discord bot that watches social/streaming accounts (YouTube, Twitch, Kick, X/Twitter, Instagram, Facebook, TikTok) and posts alerts to Discord when they post or go live. Every server's configuration — accounts, channels, alert settings, enabled/disabled state — is fully isolated by `guild_id`.

This is being built in phases. **Phases 1–4 are complete.** YouTube is the first working platform end-to-end: `/pulsenotify account-add` registers a channel, the monitoring framework polls it, and real Discord notifications go out for new videos/Shorts and live start/end.

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Project structure, config, logging, Discord client, `/pulsenotify status`, `/pulsenotify toggle`, `pn!sync`, Supabase connection | ✅ Done |
| 2 | Full database schema (accounts, channels, alert config, events, live state, platform health) | ✅ Done |
| 3 | Monitoring framework (scheduler, workers, rate limiting, retries, dedup, API usage manager) | ✅ Done — framework only, zero adapters registered |
| 4 | YouTube adapter, `/pulsenotify account-add\|account-remove\|account-list`, notification embeds + sender | ✅ Done |
| 5 | Twitch adapter | Not started |
| 6 | Kick adapter | Not started |
| 7 | X/Twitter, Instagram, Facebook, TikTok adapters | Not started |
| 8 | Templates, role mentions, `/pulsenotify alerts` (per-event-type toggles), analytics, admin tooling | Not started |

### Platform API policy (applies to every platform integration)

Before any platform integration is built: verify that platform's *current* official API pricing, quotas, rate limits, auth/approval requirements, and available endpoints — never assume an API is free, and never build against undocumented/scraped endpoints to route around a restriction. Live monitoring should prefer official webhooks/events (e.g. Twitch EventSub) over polling wherever a platform actually offers them — the monitoring framework built in Phase 3 is polling-shaped (`PlatformScheduler` on an interval), so a webhook-based platform will need its own inbound-delivery path (see Monitoring framework below) rather than being forced through `fetch_updates()`. **YouTube's live-stream detection was a deliberate exception, made with the user's explicit sign-off**: there's no cheap official alternative to the 100-quota-unit `search.list` call without a public HTTPS webhook endpoint this project doesn't have yet — see the YouTube adapter section below for the exact tradeoff and how it's budgeted.

## Requirements

- Python 3.11+
- A Discord application/bot ([discord.com/developers/applications](https://discord.com/developers/applications)) with the **Message Content Intent** enabled
- A [Supabase](https://supabase.com) project (Postgres)

## Setup

1. **Install dependencies**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements-dev.txt
   ```

2. **Configure environment**

   Copy `.env.example` to `.env` and fill in:
   - `DISCORD_TOKEN` — from the Discord Developer Portal
   - `SUPABASE_URL` / `SUPABASE_KEY` — use the **secret** key (`sb_secret_...`, Dashboard → Settings → API Keys; the older `service_role` key still works but is being phased out by end of 2026). Server-side only, bypasses RLS.
   - `DEV_GUILD_ID` — optional, a guild ID for instant slash-command sync while developing
   - `DISCORD_OWNER_IDS` — optional, extra Discord user IDs allowed to run owner-only commands. The bot's own application owner/team is resolved automatically and doesn't need to be listed here.

   `YOUTUBE_API_KEY` — a plain API key (not OAuth) from the [Google Cloud Console](https://console.cloud.google.com/apis/credentials) with the YouTube Data API v3 enabled on the project. Without it, YouTube monitoring is simply disabled at startup (logged, not fatal) — every other platform key is optional the same way until its adapter is built. `MONITORING_*`/`YOUTUBE_*` tuning variables (polling intervals, retry/backoff, rate limits, health thresholds, quota budgets) are all optional too — sensible defaults are baked in; see `.env.example` for the full list.

3. **Run the database migrations**

   In the Supabase SQL editor, run, in order:
   - [database/migrations/0001_create_guilds.sql](database/migrations/0001_create_guilds.sql)
   - [database/migrations/0002_core_schema.sql](database/migrations/0002_core_schema.sql)
   - [database/migrations/0003_add_content_cursor.sql](database/migrations/0003_add_content_cursor.sql)

   More migrations are added as later phases need them.

4. **Invite the bot**

   Generate an invite URL in the Developer Portal with the `bot` and `applications.commands` scopes, and at least `Send Messages`, `Embed Links`, `Use Slash Commands`.

5. **Run it**

   ```bash
   python main.py
   ```

6. **Sync slash commands**

   Slash commands aren't visible in Discord until synced. In any server the bot is in (as the bot owner), run:

   - `pn!sync` — syncs to that server only, visible immediately (use while developing)
   - `pn!sync global` — syncs everywhere, can take up to an hour to propagate (use for production releases)

   (`pn!` is the default prefix, set by `DISCORD_COMMAND_PREFIX` in `.env`.)

## Commands

Every slash command lives under one top-level `/pulsenotify` group (`commands/pulsenotify_group.py`) — there is no bare `/status` or `/toggle`. Account management (`account-add`/`account-remove`/`account-list`) is flattened into direct subcommands of the same group rather than nested under its own `account` subgroup: Discord doesn't allow mixing plain subcommands and subcommand groups as siblings under one parent, and `/pulsenotify toggle` (a plain subcommand) was the pattern to match.

| Command | Description | Permission |
|---|---|---|
| `/pulsenotify status` | Bot health: uptime, latency, server count, database connection, this server's enabled state, per-platform monitoring health/request counts | Anyone |
| `/pulsenotify help` | Lists every command and what it does — built by introspecting the command group itself, so it can't drift out of sync with what's actually registered | Anyone |
| `/pulsenotify toggle state:<on\|off>` | Enable/disable PulseNotify for this server. Everything else is blocked while disabled — `toggle` itself always still works. | Manage Server |
| `/pulsenotify account-add platform identifier channel` | Start monitoring a platform account; posts alerts to the given channel | Manage Server |
| `/pulsenotify account-remove account` | Stop monitoring an account (autocompletes from this server's configured accounts) | Manage Server |
| `/pulsenotify account-list` | List accounts monitored in this server, with status | Anyone |
| `/pulsenotify account-set-message account message [event_type]` | Set a custom notification message template for an account (or `clear` to remove it); see below | Manage Server |
| `pn!sync [global]` | Sync slash commands to this server, or globally. A text command, not a slash command — if the command tree is out of sync, `/pulsenotify` itself might not be registered yet, so syncing can't depend on it. | Bot owner only |

Per-account alert preferences (which event types notify, mentions, embed on/off) are seeded with sensible defaults when an account is added — new posts/videos/Shorts/live-start on, stream-ended off, matching the spec's own example. There's no `/pulsenotify alerts` command to change the on/off toggles yet (Phase 8); until then, adjusting them means editing the `pulsenotify_alert_configurations` row directly in Supabase. Custom messages *are* settable now, via `account-set-message`.

### Custom notification messages

`/pulsenotify account-set-message` lets an admin replace the default embed/text with their own template, e.g.:

```
Hey @everyone, {creator} just posted a new post! Go check it out!
{url}
```

Placeholders (`notifications/templates.py`): `{creator}` `{title}` `{description}` `{url}` `{platform}` `{category}` `{viewers}` `{mention}` (the account's configured mention role, if any — empty string otherwise). An unrecognized `{placeholder}` is left as literal text rather than erroring, and the rendered result is truncated to Discord's 2000-character message limit if substitution pushes it over — a malformed template can never crash delivery.

Two different trust levels are handled on purpose: the **template** is admin-authored (the command requires Manage Server) and may contain literal `@everyone`, `@here`, or role mentions — that's explicit configuration, matching the example above. The **values substituted into it** (video title, post description, ...) come from external platform content and are always mention-escaped first (`discord.utils.escape_mentions`), so a stream title containing the literal text "@everyone" can never inject a mention the admin didn't type themselves. `AllowedMentions.everyone` is only set `True` when the *rendered* content actually contains a literal `@everyone`/`@here` — which, given the escaping above, can only happen if the admin put it in the template.

By default a custom message replaces the standard text/embed-description content entirely; the account's `embed_enabled` setting still independently controls whether the structured embed is attached alongside it.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Tests use an in-memory fake for the Supabase query builder ([tests/unit/fakes.py](tests/unit/fakes.py)) — no live Supabase project or Discord connection is needed to run them. `tests/integration/` runs the same way (still no live services) but exercises multiple real components together with real (short) timers, e.g. a fake adapter registered with the real `MonitoringManager`, polled by a real background scheduler loop, delivered through the real dedup path.

## Architecture

```
main.py              entry point: load config, set up logging, run the bot
bot/
  client.py           PulseNotifyBot (discord.ext.commands.Bot subclass), command tree gating, owns MonitoringManager
  events.py            Discord event listeners + centralized error handling
  lifecycle.py          process run/shutdown loop (signal handling, graceful close)
commands/
  pulsenotify_group.py   the single shared `/pulsenotify` app_commands.Group every subcommand below attaches to
  admin/                status.py, toggle.py, help.py — decorate against the shared group; sync.py — a real Cog (text command, not a slash command)
  accounts/              account_commands.py — account-add/account-remove/account-list/account-set-message, flattened into the shared group; see its docstring for why
platforms/
  base.py              PlatformAdapter interface every platform implements; event_types_for_capabilities() helper
  youtube/               the first concrete adapter — client.py (HTTP), parser.py (pure JSON->shapes), adapter.py (ties them together + quota budgeting)
monitoring/
  manager.py            single start()/stop() entry point; owns one PlatformScheduler per registered adapter
  scheduler.py           polls one platform's enabled accounts on an interval, shared rate limiter
  worker.py               polls one account: fetch/normalize, live-transition detection, error isolation
  rate_limiter.py         sliding-window async limiter, shared per-platform, cost-weighted (see YouTube section)
  retry.py                 exponential backoff; skips retrying permanent/rate-limit errors
  health.py                per-platform health/usage tracker (batches request counts, gates on rate limits)
events/
  models.py             NormalizedEvent, EventType — the common event shape every adapter produces
  processor.py            queue + consumer: dedup against `pulsenotify_events`, then hands new events to a sink
notifications/
  embeds.py              NormalizedEvent -> discord.Embed (and a plain-text fallback for embed-disabled accounts)
  templates.py             safe {placeholder} substitution for admin-authored custom messages, with mention-escaping on substituted values
  sender.py                the real EventProcessor sink: alert-config gating, mention scoping, marks a channel invalid instead of retrying forever
database/
  client.py            owns the Supabase AsyncClient connection lifecycle
  models.py             TypedDict row shapes, one per table — no behavior
  repositories/         guild-scoped data access, one file per table
  migrations/           raw SQL, run manually in Supabase for now
config/
  settings.py           pydantic-settings — env vars in, validated Settings out
  constants.py           small app-wide constants (bot name, embed colors)
utils/
  logger.py             logging setup
  errors.py              PulseNotify's exception hierarchy (PlatformError, RateLimitedError, ...)
tests/
  unit/                  fast tests, no live external services
  integration/            multiple real components wired together, still no live external services
```

## Database schema

Three migrations exist so far:

- **`0001_create_guilds.sql`** — `pulsenotify_guilds`: one row per server, tracking only its enabled/disabled state (Phase 1).
- **`0002_core_schema.sql`** — everything needed to configure and run monitoring:
  - `pulsenotify_bot_settings` — guild-wide preferences (1:1 with `pulsenotify_guilds`); not used by any command yet
  - `pulsenotify_platform_accounts` — one row per monitored account per guild; duplicate (guild, platform, account) prevented by a unique constraint; created by `/pulsenotify account-add`
  - `pulsenotify_notification_channels` — Discord channels registered to receive alerts; marked `is_valid = false` rather than deleted if the bot loses access
  - `pulsenotify_account_channels` — routes one account's alerts to one channel (many-to-many)
  - `pulsenotify_alert_configurations` — per-account, per-event-type toggles (new post, live started, mentions, embeds, ...); seeded with defaults by `/pulsenotify account-add`
  - `pulsenotify_events` — the deduplication ledger: `(account_id, event_type, platform_event_id)` is unique, checked before ever sending a notification
  - `pulsenotify_live_states` — current live/offline status per account, so a bot restart mid-stream doesn't re-announce it
  - `pulsenotify_audit_logs` — append-only record of administrative actions; not written by anything yet
  - `pulsenotify_platform_health` — **not** guild-scoped; one row per platform (YouTube, Twitch, ...) tracking the bot's own API usage/quota/rate-limit state against that provider — created on first use
- **`0003_add_content_cursor.sql`** — adds `pulsenotify_platform_accounts.content_cursor`, the persisted "newest content seen" pointer. Found and fixed during Phase 4: without persisting it, a bot restart reset an account's cursor to NULL, which would either re-flood the channel's entire back-catalog or silently skip whatever was published during the downtime, depending on how that case was handled. See `monitoring/worker.py`'s docstring.

`platform`, `event_type`, and `account_status` are Postgres domains (not raw `text`), so the valid-value list for each lives in exactly one `ALTER DOMAIN`-able place instead of being repeated across every column that uses it.

## Monitoring framework

The pipeline (section 9 of the original spec):

```
MonitoringManager
   └── one PlatformScheduler per registered adapter
          └── one AccountWorker per enabled account of that platform
                 poll: fetch_updates() / get_live_status() → normalize → submit
                            ↓
                     EventProcessor (single shared queue + consumer)
                            ↓
                  dedup against `pulsenotify_events` (unique on account+type+platform_event_id)
                            ↓
                   new? → notification sink (NotificationSender, see below)
```

What's real and tested:

- **`PlatformAdapter`** ([platforms/base.py](platforms/base.py)) — the interface a concrete adapter implements: `validate_account`, `fetch_updates`, `get_live_status`, `normalize_event`, plus a `capabilities` set (`POSTS`, `VIDEOS`, `SHORTS`, `STREAMS`, `LIVE_STATUS`, `CHANNEL_UPDATES`) so the worker only calls what a platform actually supports.
- **Rate limiting** — one `RateLimiter` (sliding window) per platform, shared by every account worker for that platform, since the limit is against the platform's API as a whole. It's cost-weighted (`acquire(cost=N)`/`try_acquire(cost=N)`), not just a request count — added specifically because YouTube's API charges wildly different costs per endpoint (see below).
- **Retries** — exponential backoff with jitter; a `PermanentPlatformError` (account gone) or `RateLimitedError` (429/quota) is never retried within a call — see below.
- **The 429 / quota-exhaustion path** — an adapter raises `RateLimitedError(message, retry_after=...)`; the worker routes that to `PlatformHealthTracker.record_rate_limited()` instead of counting it against the account, and `PlatformScheduler` checks `is_rate_limited()` before every poll cycle and skips that platform entirely until the window passes. One platform hitting its quota never touches any other platform's scheduler.
- **API usage tracking** — `PlatformHealthTracker` batches request counts in memory and flushes to the (not guild-scoped) `pulsenotify_platform_health` table once per scheduler tick; surfaced in `/pulsenotify status`.
- **Live-transition detection** — the worker, not the adapter, compares a `LiveStatus` snapshot against the persisted `pulsenotify_live_states` row to decide whether to fire `STREAM_STARTED`/`STREAM_ENDED` — this is what makes "don't re-announce a stream that was already live before a restart" (section 8) work for every platform for free, rather than every adapter reimplementing it.
- **Deduplication** — `EventProcessor` is the one place that checks `pulsenotify_events` and decides "new" vs "already seen," so that guarantee holds regardless of which worker or platform produced the event.
- **Notification delivery** — `EventProcessor`'s sink is `NotificationSender.handle` ([notifications/sender.py](notifications/sender.py)): checks the account's alert config for that event type, builds an embed (or plain text if embeds are disabled for that account), scopes mentions to just the configured role (`AllowedMentions`, never `@everyone`/arbitrary users — section 36), and sends to every channel linked to that account. A channel Discord says is gone (`Forbidden`/`NotFound`) gets marked `is_valid=false` instead of retried forever (section 23); other Discord errors are logged and skipped, not treated as fatal.

**Known architectural gap:** this framework is polling-shaped — `PlatformScheduler` calls `fetch_updates()`/`get_live_status()` on an interval. The platform-API policy above prefers webhooks (Twitch EventSub, YouTube WebSub) where a platform offers them and the cost of polling is too high; a webhook-based platform will need its own inbound HTTP receiver feeding events into the same `EventProcessor.submit()`, bypassing the polling scheduler rather than being forced through it. Not designed yet.

## YouTube adapter (platforms/youtube/)

The first concrete `PlatformAdapter`. API availability was verified against Google's current documentation before writing any code (see `platforms/youtube/adapter.py`'s module docstring for the full table) — summary:

| Feature | Method | Cost | Notes |
|---|---|---|---|
| New videos | `playlistItems.list` on the uploads playlist | 1 unit | Reliable, cheap |
| Shorts | `contentDetails.duration <= 60s` heuristic | (included above) | **No official "is Short" field exists.** False positives possible for short regular videos — `NormalizedEvent.metadata["is_short_heuristic"]` marks it as a guess, not fact |
| Community posts | — | — | **Not implemented — no public API endpoint exists for this at all** |
| Live start/end | `search.list(eventType=live)` + `videos.list` | 100 + 1 | The *only* documented way to find a live broadcast on a channel this bot doesn't own |
| Upcoming/scheduled streams | — | — | Not implemented this phase |

Credentials: a plain API key, no OAuth (everything above is public data).

**The quota tradeoff, and why it needed your sign-off:** the free tier is 10,000 units/day, shared by every YouTube account this bot monitors — one budget per API key, not per account or guild. `search.list` alone can burn the entire daily budget checking live status for a single channel every ~15 minutes. Given the choice between (a) shipping video detection only and deferring live detection, (b) accepting the quota cost, or (c) building a WebSub push receiver now, **you chose (b)** — live detection ships, budgeted explicitly rather than left to accidentally exhaust the quota:

- `YOUTUBE_DAILY_QUOTA_UNITS` (default 10,000) and `YOUTUBE_LIVE_SEARCH_DAILY_BUDGET_UNITS` (default 8,000) split the daily budget between the two call types.
- The adapter owns two internal `RateLimiter`s sized from those settings — one for the cheap 1-unit calls, one for the 100-unit live search.
- The live-search limiter uses `try_acquire()` (non-blocking): once the day's live-search budget is spent, `get_live_status()` just returns `None` (skip this cycle, not an error) instead of blocking a worker for hours waiting for the window to free up.
- A real 429 or `quotaExceeded` response additionally pauses that entire platform via the framework's rate-limit path described above.

If you later get a Google quota extension, raise `YOUTUBE_DAILY_QUOTA_UNITS` accordingly — you cannot pay to increase it directly.

## Guild isolation

Every table that stores server-specific data is keyed by `guild_id`, and every query in `database/repositories/` filters by it — there's no code path that loads all guilds' data and filters in Python. `GuildRepository`'s in-memory cache is likewise keyed per guild, so toggling one server can't affect another's cached state. This pattern is the one to follow for every repository added in later phases.

Where one row links two guild-scoped parents — `pulsenotify_account_channels` linking a `pulsenotify_platform_accounts` row to a `pulsenotify_notification_channels` row — the foreign keys are composite (`guild_id`, `id`) rather than plain `id`. That makes it a database-level constraint violation, not just an application bug, to ever wire one guild's account to another guild's channel; `pulsenotify_platform_health` is the one exception, since it isn't guild data at all (see the schema section above).

## Security notes

- The Discord token, Supabase key, and all platform credentials are read from environment variables only — never hardcoded, never logged.
- `SUPABASE_KEY` must be the `secret` (or legacy `service_role`) key and must never be shipped to a client or exposed publicly.
- Owner-only commands (`sync`) use `commands.is_owner()`, backed by the bot application's real owner/team (fetched from Discord at startup) plus any IDs in `DISCORD_OWNER_IDS` — not a hardcoded user ID check.
