import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


DEFAULT_TOPICS = [
    "Database / backend",
    "Frontend / UI / UX",
    "DevOps / infra",
    "AI / ML tools",
    "Open source",
    "Startup / founder life",
    "Career / growth",
    "Developer tools / productivity",
    "Product thinking",
    "Hardware / gadgets",
    "Remote work / async",
    "Side projects",
    "Security / privacy",
    "Technical debt / refactoring",
    "Pricing / monetization",
    "API design",
    "Mobile / cross-platform",
    "Data / analytics",
    "Community / content creation",
    "Entrepreneurship",
    "Economics",
    "AI / future of AI",
    "Philosophy of tech",
    "AI agents",
    "Robotics / physical tech",
    "Current events / news",
    "Culture / memes / takes",
]

DEFAULT_DEGEN_TOPICS = [
    "BTC / Bitcoin",
    "ETH / Ethereum",
    "Solana / SOL",
    "Meme coins",
    "DeFi",
    "NFTs",
    "Market analysis",
    "Airdrops / Farming",
    "Layer 2s",
    "Crypto news",
    "Trading / Charts",
    "Regulation / Policy",
]

PROJECT_CATEGORIES = {
    "L1s & L2s": [
        "@solana", "@base", "@arbitrum", "@Optimism", "@zksync", "@Starknet",
        "@Aptos", "@SuiNetwork", "@0xPolygon", "@avaboratory", "@SeiNetwork",
        "@LineaBuild", "@Scroll_ZKP", "@abstractchain", "@monad_xyz",
        "@megaeth_labs", "@movementlabsxyz", "@beaboratory", "@CelestiaOrg",
        "@eigenlayer",
    ],
    "AI": [
        "@OpenAI", "@AnthropicAI", "@GoogleDeepMind",
        "@MistralAI", "@MetaAI", "@CohereAI",
        "@karpathy", "@ylecun", "@sama",
        "@AravSrinivas", "@ClaudeAI",
    ],
    "DeFi": [
        "@Uniswap", "@AaveAave", "@CurveFinance",
        "@LidoFinance", "@PendleFinance", "@1inch", "@GMX_IO",
        "@JupiterExchange",
        "@DefiIgnas", "@Route2FI", "@TheDeFiEdge",
    ],
    "Gaming & NFTs": [
        "@AxieInfinity", "@Immutable", "@RoninChain", "@BeamFdn",
        "@pudgypenguins", "@BoredApeYC", "@MagicEden", "@blur_io",
        "@AzukiOfficial",
    ],
    "Meme coins": [
        "@dogecoin", "@Shibtoken", "@bonk_inu",
        "@pumpdotfun",
    ],
    "CT KOLs": [
        "@blknoiz06", "@alxcooks", "@inversebrah", "@ericcryptoman",
        "@0xMert_", "@jessepollak", "@rajgokal",
        "@MustStopMurad", "@CryptoKaleo",
        "@Pentoshi", "@lookonchain", "@CryptoGodJohn", "@milesdeutscher",
        "@ZachXBT", "@cobie", "@AltcoinGordon", "@CryptoCred",
        "@GCRClassic", "@WClementeIII", "@cburniske",
    ],
    "Infra & Dev Tools": [
        "@QuickNode", "@TrueNetwork_io",
    ],
}


@dataclass
class Config:
    # Profile identity
    profile_name: str = "default"

    # Mode: "dev", "project", "degen"
    farming_mode: str = "dev"

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Browser
    chrome_profile_path: str = ""
    chrome_profile_directory: str = ""
    headless: bool = False

    # X Login
    x_username: str = ""
    x_password: str = ""
    x_totp_secret: str = ""

    # Voice (Dev Farming)
    voice_description: str = ""
    bad_examples: str = ""
    good_examples: str = ""
    dev_do: str = ""
    dev_dont: str = ""

    # Dev Topics
    topics: dict = field(default_factory=lambda: {t: True for t in DEFAULT_TOPICS})

    # Project Farming
    project_name: str = ""
    project_about: str = ""
    project_do: str = ""
    project_dont: str = ""
    project_categories: dict = field(default_factory=lambda: {cat: True for cat in PROJECT_CATEGORIES})
    project_timeline_comments: int = 5
    project_timeline_min_likes: int = 100

    # Degen Farming
    degen_topics: dict = field(default_factory=lambda: {t: True for t in DEFAULT_DEGEN_TOPICS})
    degen_voice_description: str = ""
    degen_do: str = ""
    degen_dont: str = ""

    # RT Farm
    rt_farm_target_handle: str = ""
    rt_farm_delay_seconds: int = 5
    rt_farm_max_scrolls: int = 50

    # Sniper mode
    sniper_enabled: bool = False
    sniper_scan_interval_minutes: int = 8
    sniper_min_velocity: int = 100
    sniper_max_replies: int = 80
    sniper_replies_per_scan: int = 2

    # Thread settings
    thread_every_n_sequences: int = 4

    # Intelligence toggles
    use_llm_classification: bool = True
    use_vision_image_check: bool = False
    position_memory_enabled: bool = True

    # Sequence composition (per-sequence, exact counts)
    seq_text_tweets: int = 1
    seq_rephrase_tweets: int = 1
    seq_comments: int = 4
    seq_qrts: int = 1
    seq_rts: int = 1
    seq_follows: int = 2
    seq_threads: int = 0

    # Daily caps (derived from seq_* * sequences/day)
    daily_max_tweets: int = 8
    daily_max_comments: int = 25
    daily_max_likes: int = 50
    daily_max_follows: int = 10
    daily_max_qrts: int = 5
    daily_max_rts: int = 10

    # Active hours
    active_hours_enabled: bool = False
    active_hours_start: int = 8
    active_hours_end: int = 23
    active_hours_timezone: str = "UTC"

    # Timing
    action_delay_seconds: int = 3
    sequence_delay_minutes: int = 45
    min_engagement_likes: int = 100

    # ------------------------------------------------------------------ #
    #  Path helpers                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def root_dir() -> str:
        return os.path.join(os.path.expanduser("~"), ".devmaker")

    @staticmethod
    def profiles_dir() -> str:
        return os.path.join(Config.root_dir(), "profiles")

    # Keep data_dir() for backward compat — points to profile-specific dir
    def data_dir(self) -> str:
        return os.path.join(Config.profiles_dir(), self.profile_name)

    def config_path(self) -> str:
        return os.path.join(self.data_dir(), "config.json")

    # ------------------------------------------------------------------ #
    #  Topic helpers                                                       #
    # ------------------------------------------------------------------ #

    def enabled_topics(self) -> list[str]:
        return [t for t, enabled in self.topics.items() if enabled]

    def enabled_degen_topics(self) -> list[str]:
        return [t for t, enabled in self.degen_topics.items() if enabled]

    def enabled_project_handles(self) -> set[str]:
        """Return lowercase handle set from all enabled categories."""
        handles: set[str] = set()
        for cat, enabled in self.project_categories.items():
            if enabled and cat in PROJECT_CATEGORIES:
                for h in PROJECT_CATEGORIES[cat]:
                    handles.add(h.strip().lstrip("@").lower())
        handles.discard("")
        return handles

    def active_api_key(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return self.openai_api_key

    def active_model(self) -> str:
        if self.llm_provider == "anthropic":
            return self.anthropic_model
        return self.openai_model

    # ------------------------------------------------------------------ #
    #  Persistence                                                         #
    # ------------------------------------------------------------------ #

    def save(self):
        os.makedirs(self.data_dir(), exist_ok=True)
        with open(self.config_path(), "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, profile_name: str = "default") -> "Config":
        cfg = cls(profile_name=profile_name)
        path = cfg.config_path()
        if not os.path.exists(path):
            cfg.save()
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        cfg.profile_name = profile_name
        for t in DEFAULT_TOPICS:
            if t not in cfg.topics:
                cfg.topics[t] = True
        for t in DEFAULT_DEGEN_TOPICS:
            if t not in cfg.degen_topics:
                cfg.degen_topics[t] = True
        for cat in PROJECT_CATEGORIES:
            if cat not in cfg.project_categories:
                cfg.project_categories[cat] = True
        return cfg

    # ------------------------------------------------------------------ #
    #  Profile management                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_profiles() -> list[str]:
        """Return sorted list of all profile names."""
        pdir = Config.profiles_dir()
        if not os.path.isdir(pdir):
            return []
        names = []
        for entry in os.listdir(pdir):
            full = os.path.join(pdir, entry)
            if os.path.isdir(full) and os.path.exists(os.path.join(full, "config.json")):
                names.append(entry)
        return sorted(names)

    @staticmethod
    def create_profile(name: str) -> "Config":
        """Create a new profile with default config and return it."""
        cfg = Config(profile_name=name)
        cfg.save()
        return cfg

    @staticmethod
    def delete_profile(name: str):
        """Delete a profile directory."""
        import shutil
        pdir = os.path.join(Config.profiles_dir(), name)
        if os.path.isdir(pdir):
            shutil.rmtree(pdir)

    @staticmethod
    def rename_profile(old_name: str, new_name: str):
        pdir = Config.profiles_dir()
        old_path = os.path.join(pdir, old_name)
        new_path = os.path.join(pdir, new_name)
        if os.path.isdir(old_path) and not os.path.exists(new_path):
            os.rename(old_path, new_path)
            cfg = Config.load(new_name)
            cfg.profile_name = new_name
            cfg.save()

    @staticmethod
    def ensure_default_profile():
        """Make sure at least one profile exists. Migrates legacy config if found."""
        import shutil

        root = Config.root_dir()
        old_config = os.path.join(root, "config.json")
        old_state = os.path.join(root, "state.json")
        default_dir = os.path.join(Config.profiles_dir(), "default")

        # Migrate legacy single-account config into profiles/default/
        if os.path.exists(old_config) and not os.path.isdir(default_dir):
            os.makedirs(default_dir, exist_ok=True)
            shutil.copy2(old_config, os.path.join(default_dir, "config.json"))
            if os.path.exists(old_state):
                shutil.copy2(old_state, os.path.join(default_dir, "state.json"))
            # Remove old files after migration
            os.remove(old_config)
            if os.path.exists(old_state):
                os.remove(old_state)

        profiles = Config.list_profiles()
        if not profiles:
            Config.create_profile("default")
