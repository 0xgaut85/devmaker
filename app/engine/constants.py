"""Engine-wide tunables. Single source of truth for every magic number."""

# Extension command timeouts
DEFAULT_CMD_TIMEOUT = 60.0
SLOW_CMD_TIMEOUT = 180.0
SLOW_COMMANDS = frozenset({
    "post_tweet", "post_comment", "post_thread", "quote_tweet",
    "session_warmup", "scrape_timeline", "scrape_retweets",
})

# Reconnect window when the extension drops mid-sequence (Chrome MV3 SW
# suspension is the common cause).
RECONNECT_WAIT_SECONDS = 30.0

# Generation
MAX_GEN_RETRIES = 3

# Dedup state caps (kept on State.recent_*)
RECENT_POSTED_TEXTS_CAP = 30
RECENT_SOURCE_URLS_CAP = 50
RECENT_FOLLOWS_CAP = 100

# Daily action counter retention (in days). Older buckets are dropped.
DAILY_COUNTER_RETENTION = 14

# Position memory cap.
POSITION_HISTORY_CAP = 30

# Sniper internal caps.
SNIPER_REPLIED_CAP = 200

# Engagement / scrape baseline. The single fallback factor used when the user's
# min_engagement_likes setting yields too few eligible posts. We prefer one
# clean retry over the previous "three escalating fallback scrapes" hack.
TIMELINE_FALLBACK_LIKES_DIVISOR = 5
TIMELINE_MIN_ELIGIBLE = 3

# Pause floor (seconds) applied when cfg.action_delay_seconds is missing/zero.
PAUSE_FLOOR_DEFAULT = 8
