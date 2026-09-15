-- PulseNotify: 0004_add_webhook_url
--
-- Notifications now send through a per-channel Discord webhook instead of
-- the bot's own user, so each alert can show up under the posting
-- account's name (see notifications/sender.py) rather than always
-- appearing as "PulseNotify". The webhook is created once per channel
-- (lazily, on first notification) and reused after that — persisting its
-- URL here is what makes that reuse survive a bot restart, the same
-- reasoning as 0003's content_cursor.

alter table pulsenotify_notification_channels add column if not exists webhook_url text;
