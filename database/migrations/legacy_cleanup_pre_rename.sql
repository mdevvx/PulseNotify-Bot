-- One-time cleanup for databases set up BEFORE the pulsenotify_ table
-- prefix was added. Not part of the numbered migration sequence — a
-- fresh Supabase project never needs this, since 0001-0003 already create
-- correctly-named tables from scratch. Run this once, then run (or
-- re-run) 0001_create_guilds.sql, 0002_core_schema.sql, and
-- 0003_add_content_cursor.sql in order.
--
-- Safe even if you only ever ran some of the old migrations — IF EXISTS
-- + CASCADE means a table/function that was never created is just
-- silently skipped, and CASCADE drops any dependent triggers/constraints
-- automatically regardless of drop order.

drop table if exists account_channels cascade;
drop table if exists alert_configurations cascade;
drop table if exists audit_logs cascade;
drop table if exists bot_settings cascade;
drop table if exists events cascade;
drop table if exists live_states cascade;
drop table if exists notification_channels cascade;
drop table if exists platform_accounts cascade;
drop table if exists platform_health cascade;
drop table if exists guilds cascade;

-- The old shared trigger function these used; 0001/0002 now create
-- pulsenotify_set_updated_at() instead.
drop function if exists set_updated_at() cascade;
