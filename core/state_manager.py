"""Sequence state persistence and rotation logic — profile-aware."""

import json
import os
import random
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from content.rules import FORMAT_ORDER, DEGEN_FORMAT_ORDER, COMMENT_ROTATIONS, TONE_LIST, THREAD_FORMAT_ORDER


@dataclass
class SequenceState:
    # Dev Farming state
    sequence_number: int = 0
    last_format: str = ""
    last_topic_tweet: str = ""
    last_topic_qrt: str = ""
    last_topic_rt: str = ""
    last_qrt_author: str = ""
    last_comment_topics: list = field(default_factory=list)
    last_comment_rotation: list = field(default_factory=list)
    last_follows: list = field(default_factory=list)
    history: list = field(default_factory=list)

    # Project Farming state
    project_sequence_number: int = 0
    project_comments_sent: int = 0
    project_accounts_visited: list = field(default_factory=list)

    # Degen Farming state
    degen_sequence_number: int = 0
    degen_last_format: str = ""
    degen_last_topic: str = ""
    degen_last_comment_rotation: list = field(default_factory=list)
    degen_history: list = field(default_factory=list)

    # RT Farm state
    rt_farm_completed_urls: list = field(default_factory=list)
    rt_farm_total_retweeted: int = 0

    # Content dedup history (shared across modes)
    recent_posted_texts: list = field(default_factory=list)
    recent_source_urls: list = field(default_factory=list)

    # Sniper mode state
    sniper_replied_urls: list = field(default_factory=list)
    sniper_total_replies: int = 0

    # Thread state
    thread_last_format: str = ""

    # Performance tracking
    performance_history: list = field(default_factory=list)

    # Position memory
    position_history: list = field(default_factory=list)

    # Daily action tracking
    daily_actions: dict = field(default_factory=dict)

    @staticmethod
    def state_path_for(profile_dir: str) -> str:
        return os.path.join(profile_dir, "state.json")

    def save_to(self, profile_dir: str):
        os.makedirs(profile_dir, exist_ok=True)
        with open(self.state_path_for(profile_dir), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load_for(cls, profile_dir: str) -> "SequenceState":
        path = cls.state_path_for(profile_dir)
        if not os.path.exists(path):
            state = cls()
            state.save_to(profile_dir)
            return state
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = cls()
        for k, v in data.items():
            if hasattr(state, k):
                setattr(state, k, v)
        return state

    # ------------------------------------------------------------------ #
    #  Dev rotation helpers                                                #
    # ------------------------------------------------------------------ #

    def next_format(self) -> str:
        idx = 0
        if self.last_format in FORMAT_ORDER:
            idx = (FORMAT_ORDER.index(self.last_format) + 1) % len(FORMAT_ORDER)
        return FORMAT_ORDER[idx]

    def next_topic(self, enabled_topics: list[str], exclude: list[str] | None = None) -> str:
        exclude = exclude or []
        recent = {self.last_topic_tweet, self.last_topic_qrt, self.last_topic_rt}
        recent.update(exclude)
        available = [t for t in enabled_topics if t not in recent]
        if not available:
            available = [t for t in enabled_topics if t not in exclude]
        if not available:
            available = enabled_topics
        return random.choice(available)

    def next_comment_rotation(self) -> list[str]:
        if self.last_comment_rotation in COMMENT_ROTATIONS:
            idx = (COMMENT_ROTATIONS.index(self.last_comment_rotation) + 1) % len(COMMENT_ROTATIONS)
        else:
            idx = 0
        return COMMENT_ROTATIONS[idx]

    def next_tone(self, index: int) -> str:
        return TONE_LIST[index % len(TONE_LIST)]

    # ------------------------------------------------------------------ #
    #  Degen rotation helpers                                              #
    # ------------------------------------------------------------------ #

    def next_degen_format(self) -> str:
        idx = 0
        if self.degen_last_format in DEGEN_FORMAT_ORDER:
            idx = (DEGEN_FORMAT_ORDER.index(self.degen_last_format) + 1) % len(DEGEN_FORMAT_ORDER)
        return DEGEN_FORMAT_ORDER[idx]

    def next_degen_comment_rotation(self) -> list[str]:
        if self.degen_last_comment_rotation in COMMENT_ROTATIONS:
            idx = (COMMENT_ROTATIONS.index(self.degen_last_comment_rotation) + 1) % len(COMMENT_ROTATIONS)
        else:
            idx = 0
        return COMMENT_ROTATIONS[idx]

    # ------------------------------------------------------------------ #
    #  Record helpers                                                      #
    # ------------------------------------------------------------------ #

    def record_sequence(
        self,
        profile_dir: str,
        format_key: str,
        topic_tweet: str,
        topic_qrt: str,
        topic_rt: str,
        qrt_author: str,
        comment_topics: list[str],
        comment_rotation: list[str],
        follows: list[str],
    ):
        self.history.append(
            {
                "seq": self.sequence_number,
                "format": self.last_format,
                "tweet_topic": self.last_topic_tweet,
                "qrt_topic": self.last_topic_qrt,
            }
        )
        self.history = self.history[-10:]
        self.sequence_number += 1
        self.last_format = format_key
        self.last_topic_tweet = topic_tweet
        self.last_topic_qrt = topic_qrt
        self.last_topic_rt = topic_rt
        self.last_qrt_author = qrt_author
        self.last_comment_topics = comment_topics
        self.last_comment_rotation = comment_rotation
        self.last_follows = follows
        self.save_to(profile_dir)

    def record_project_sequence(self, profile_dir: str, accounts_visited: list[str], comments_sent: int):
        self.project_sequence_number += 1
        self.project_accounts_visited = accounts_visited
        self.project_comments_sent += comments_sent
        self.save_to(profile_dir)

    def record_degen_sequence(
        self,
        profile_dir: str,
        format_key: str,
        topic: str,
        comment_rotation: list[str],
    ):
        self.degen_history.append(
            {
                "seq": self.degen_sequence_number,
                "format": self.degen_last_format,
                "topic": self.degen_last_topic,
            }
        )
        self.degen_history = self.degen_history[-10:]
        self.degen_sequence_number += 1
        self.degen_last_format = format_key
        self.degen_last_topic = topic
        self.degen_last_comment_rotation = comment_rotation
        self.save_to(profile_dir)

    def record_rt_farm_progress(self, profile_dir: str, url: str):
        if url not in self.rt_farm_completed_urls:
            self.rt_farm_completed_urls.append(url)
            self.rt_farm_total_retweeted += 1
        self.save_to(profile_dir)

    def record_posted_text(self, text: str):
        """Track posted text for dedup (in-memory until next save_to)."""
        self.recent_posted_texts.append(text)
        self.recent_posted_texts = self.recent_posted_texts[-30:]

    def record_source_url(self, url: str):
        """Track source post URL to avoid re-using the same inspiration."""
        if url not in self.recent_source_urls:
            self.recent_source_urls.append(url)
        self.recent_source_urls = self.recent_source_urls[-50:]

    def next_thread_format(self) -> str:
        idx = 0
        if self.thread_last_format in THREAD_FORMAT_ORDER:
            idx = (THREAD_FORMAT_ORDER.index(self.thread_last_format) + 1) % len(THREAD_FORMAT_ORDER)
        return THREAD_FORMAT_ORDER[idx]

    def should_post_thread(self, every_n: int = 4) -> bool:
        """Return True if this sequence should include a thread."""
        return self.sequence_number > 0 and self.sequence_number % every_n == 0

    def record_sniper_reply(self, profile_dir: str, url: str):
        if url not in self.sniper_replied_urls:
            self.sniper_replied_urls.append(url)
            self.sniper_total_replies += 1
        self.sniper_replied_urls = self.sniper_replied_urls[-200:]
        self.save_to(profile_dir)

    def record_performance(self, profile_dir: str, entries: list[dict]):
        """Store performance check results, keeping last 50."""
        self.performance_history.extend(entries)
        self.performance_history = self.performance_history[-50:]
        self.save_to(profile_dir)

    # ------------------------------------------------------------------ #
    #  Daily cap helpers                                                   #
    # ------------------------------------------------------------------ #

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _today_counts(self) -> dict:
        key = self._today_key()
        if key not in self.daily_actions:
            self.daily_actions = {key: {}}
        return self.daily_actions[key]

    def can_perform_action(self, action_type: str, daily_caps: dict) -> bool:
        """Check if the daily cap allows this action.
        daily_caps maps action_type -> max count (e.g. {"tweets": 8, "comments": 25})."""
        cap = daily_caps.get(action_type)
        if cap is None:
            return True
        counts = self._today_counts()
        return counts.get(action_type, 0) < cap

    def record_daily_action(self, action_type: str):
        """Increment the daily counter for an action type."""
        counts = self._today_counts()
        counts[action_type] = counts.get(action_type, 0) + 1

    def all_caps_reached(self, daily_caps: dict) -> bool:
        """Return True if every capped action type has hit its limit."""
        for action_type, cap in daily_caps.items():
            counts = self._today_counts()
            if counts.get(action_type, 0) < cap:
                return False
        return True
