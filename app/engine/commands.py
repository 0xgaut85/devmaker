"""Command types sent between backend and Chrome extension over WebSocket."""

from enum import Enum


class CommandType(str, Enum):
    # Navigation
    NAVIGATE = "navigate"
    SCROLL = "scroll"

    # Scraping
    SCRAPE_TIMELINE = "scrape_timeline"
    SCRAPE_PROFILE = "scrape_profile"
    SCRAPE_REPLIES = "scrape_replies"
    SCRAPE_RETWEETS = "scrape_retweets"
    SCRAPE_WHO_TO_FOLLOW = "scrape_who_to_follow"
    SCRAPE_PERFORMANCE = "scrape_performance"

    # Actions
    POST_TWEET = "post_tweet"
    POST_COMMENT = "post_comment"
    POST_THREAD = "post_thread"
    QUOTE_TWEET = "quote_tweet"
    LIKE_POST = "like_post"
    BOOKMARK_POST = "bookmark_post"
    FOLLOW_USER = "follow_user"
    RETWEET = "retweet"

    # Session
    SESSION_WARMUP = "session_warmup"
    LURK_SCROLL = "lurk_scroll"
    CHECK_NOTIFICATIONS = "check_notifications"

    # System
    PING = "ping"
    STATUS = "status"


def make_command(cmd: str, **params) -> dict:
    """Build a command dict to send to the extension."""
    return {"cmd": cmd, "params": params}


def make_response(cmd: str, status: str = "ok", data=None, error: str = "") -> dict:
    """Build a response dict from the extension."""
    resp = {"cmd": cmd, "status": status}
    if data is not None:
        resp["data"] = data
    if error:
        resp["error"] = error
    return resp
