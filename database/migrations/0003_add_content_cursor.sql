-- PulseNotify: 0003_add_content_cursor
--
-- AccountWorker's content-polling cursor (an opaque, adapter-defined token
-- — for YouTube, the most recently seen video ID) was only ever held in
-- memory. That means a bot restart reset it to NULL, which either
-- re-floods notifications for a channel's entire back-catalog (if treated
-- as "brand new account") or silently skips whatever was published during
-- the restart gap (if not). Persisting it fixes both: an existing
-- account's cursor survives a restart, and only a genuinely new account
-- (content_cursor still NULL) gets the "establish a baseline, don't
-- notify the back-catalog" treatment.

alter table pulsenotify_platform_accounts add column if not exists content_cursor text;
