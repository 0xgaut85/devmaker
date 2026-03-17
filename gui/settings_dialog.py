"""Settings dialog with tabs: Account, Voice, Topics, LLM, Timing, Project Farming, Degen Farming."""

from PyQt6.QtWidgets import (
    QDialog,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QWidget,
    QLabel,
    QLineEdit,
    QTextEdit,
    QCheckBox,
    QRadioButton,
    QButtonGroup,
    QComboBox,
    QSpinBox,
    QPushButton,
    QFileDialog,
    QScrollArea,
    QGroupBox,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from core.config import Config, DEFAULT_TOPICS, DEFAULT_DEGEN_TOPICS, PROJECT_CATEGORIES


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(f"Settings — {config.profile_name}")
        self.setMinimumSize(640, 540)
        self._build_ui()
        self._load_values()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        tabs.addTab(self._build_account_tab(), "Account")
        tabs.addTab(self._build_voice_tab(), "Voice")
        tabs.addTab(self._build_topics_tab(), "Topics")
        tabs.addTab(self._build_llm_tab(), "LLM")
        tabs.addTab(self._build_timing_tab(), "Timing")
        tabs.addTab(self._build_project_tab(), "Project Farming")
        tabs.addTab(self._build_degen_tab(), "Degen Farming")
        tabs.addTab(self._build_rt_farm_tab(), "RT Farm")
        tabs.addTab(self._build_sniper_tab(), "Sniper")
        tabs.addTab(self._build_intelligence_tab(), "Intelligence")

        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------ #
    #  Account                                                             #
    # ------------------------------------------------------------------ #

    def _build_account_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.chrome_path_edit = QLineEdit()
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_chrome_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.chrome_path_edit, 1)
        path_row.addWidget(browse_btn)
        form.addRow("Chrome Profile Path:", path_row)

        self.profile_dir_edit = QLineEdit()
        self.profile_dir_edit.setPlaceholderText("e.g. Profile 4 (leave empty for Default)")
        form.addRow("Profile Directory:", self.profile_dir_edit)

        self.headless_check = QCheckBox("Run browser in headless mode (invisible)")
        form.addRow("", self.headless_check)

        info = QLabel(
            "Chrome User Data path: C:\\Users\\<you>\\AppData\\Local\\Google\\Chrome\\User Data\n"
            "Profile Directory: the subfolder name (e.g. 'Profile 4'). Leave empty for Default.\n"
            "Chrome will be closed automatically when DevMaker starts."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", info)

        sep = QLabel("── X Login (auto-login if session expired) ──")
        sep.setStyleSheet("color: gray; font-weight: bold; margin-top: 10px;")
        form.addRow("", sep)

        self.x_username_edit = QLineEdit()
        self.x_username_edit.setPlaceholderText("@handle or email or phone")
        form.addRow("X Username:", self.x_username_edit)

        self.x_password_edit = QLineEdit()
        self.x_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("X Password:", self.x_password_edit)

        self.x_totp_edit = QLineEdit()
        self.x_totp_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.x_totp_edit.setPlaceholderText("Base32 secret (from authenticator setup)")
        form.addRow("2FA TOTP Secret:", self.x_totp_edit)

        return w

    def _browse_chrome_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Chrome Profile Directory")
        if path:
            self.chrome_path_edit.setText(path)

    # ------------------------------------------------------------------ #
    #  Voice (Dev Farming)                                                 #
    # ------------------------------------------------------------------ #

    def _build_voice_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Voice Description (how the LLM should write for Dev Farming):"))
        self.voice_edit = QTextEdit()
        self.voice_edit.setPlaceholderText(
            "Paste your writing persona here. Example:\n\n"
            "Casual, off-the-cuff. First-person (\"I\", \"we\"). Contractions everywhere.\n"
            "Slightly scrappy, honest about struggles. Not polished or aphoristic.\n"
            "Uses \"honestly\", \"pretty\", \"really\" naturally."
        )
        layout.addWidget(self.voice_edit, 2)

        layout.addWidget(QLabel("Bad Examples (output you do NOT want):"))
        self.bad_examples_edit = QTextEdit()
        self.bad_examples_edit.setPlaceholderText(
            "Optional. Paste examples of bad output here.\n"
            "e.g. \"Ecosystem lock-in beats raw benchmarks every time.\""
        )
        layout.addWidget(self.bad_examples_edit, 1)

        layout.addWidget(QLabel("Good Examples (output you DO want):"))
        self.good_examples_edit = QTextEdit()
        self.good_examples_edit.setPlaceholderText(
            "Optional. Paste examples of good output here.\n"
            "e.g. \"honestly the real moat is integration. benchmarks get headlines, ecosystems win\""
        )
        layout.addWidget(self.good_examples_edit, 1)

        return w

    # ------------------------------------------------------------------ #
    #  Topics (Dev Farming)                                                #
    # ------------------------------------------------------------------ #

    def _build_topics_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Dev Farming topics for rotation:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        self.topic_checks: dict[str, QCheckBox] = {}
        for topic in DEFAULT_TOPICS:
            cb = QCheckBox(topic)
            cb.setChecked(True)
            self.topic_checks[topic] = cb
            scroll_layout.addWidget(cb)

        self._custom_topic_checks: list[QCheckBox] = []

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        self._topic_scroll_layout = scroll_layout
        layout.addWidget(scroll, 1)

        add_row = QHBoxLayout()
        self.custom_topic_input = QLineEdit()
        self.custom_topic_input.setPlaceholderText("Add custom topic...")
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_custom_topic)
        add_row.addWidget(self.custom_topic_input, 1)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        btn_row = QHBoxLayout()
        all_btn = QPushButton("Select All")
        all_btn.clicked.connect(lambda: self._toggle_all_topics(True))
        none_btn = QPushButton("Deselect All")
        none_btn.clicked.connect(lambda: self._toggle_all_topics(False))
        btn_row.addWidget(all_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return w

    def _add_custom_topic(self):
        topic = self.custom_topic_input.text().strip()
        if not topic or topic in self.topic_checks:
            return
        cb = QCheckBox(topic)
        cb.setChecked(True)
        self.topic_checks[topic] = cb
        self._custom_topic_checks.append(cb)
        self._topic_scroll_layout.insertWidget(
            self._topic_scroll_layout.count() - 1, cb
        )
        self.custom_topic_input.clear()

    def _toggle_all_topics(self, checked: bool):
        for cb in self.topic_checks.values():
            cb.setChecked(checked)

    # ------------------------------------------------------------------ #
    #  LLM                                                                 #
    # ------------------------------------------------------------------ #

    def _build_llm_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.provider_group = QButtonGroup(self)
        self.openai_radio = QRadioButton("OpenAI")
        self.anthropic_radio = QRadioButton("Anthropic")
        self.provider_group.addButton(self.openai_radio)
        self.provider_group.addButton(self.anthropic_radio)

        provider_row = QHBoxLayout()
        provider_row.addWidget(self.openai_radio)
        provider_row.addWidget(self.anthropic_radio)
        provider_row.addStretch()
        form.addRow("Provider:", provider_row)

        self.openai_key_edit = QLineEdit()
        self.openai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.openai_key_edit.setPlaceholderText("sk-...")
        form.addRow("OpenAI API Key:", self.openai_key_edit)

        self.openai_model_combo = QComboBox()
        self.openai_model_combo.addItems(["gpt-4o", "gpt-4o-mini", "gpt-4.1"])
        form.addRow("OpenAI Model:", self.openai_model_combo)

        self.anthropic_key_edit = QLineEdit()
        self.anthropic_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.anthropic_key_edit.setPlaceholderText("sk-ant-...")
        form.addRow("Anthropic API Key:", self.anthropic_key_edit)

        self.anthropic_model_combo = QComboBox()
        self.anthropic_model_combo.addItems(["claude-sonnet-4-20250514", "claude-haiku-4-20250414"])
        form.addRow("Anthropic Model:", self.anthropic_model_combo)

        return w

    # ------------------------------------------------------------------ #
    #  Timing                                                              #
    # ------------------------------------------------------------------ #

    def _build_timing_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.action_delay_spin = QSpinBox()
        self.action_delay_spin.setRange(1, 30)
        self.action_delay_spin.setSuffix(" seconds")
        form.addRow("Delay between actions:", self.action_delay_spin)

        self.sequence_delay_spin = QSpinBox()
        self.sequence_delay_spin.setRange(0, 180)
        self.sequence_delay_spin.setSuffix(" minutes")
        form.addRow("Delay between sequences:", self.sequence_delay_spin)

        self.engagement_spin = QSpinBox()
        self.engagement_spin.setRange(0, 10000)
        self.engagement_spin.setSuffix(" likes")
        form.addRow("Min engagement threshold:", self.engagement_spin)

        return w

    # ------------------------------------------------------------------ #
    #  Project Farming                                                     #
    # ------------------------------------------------------------------ #

    def _build_project_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)

        # --- Project identity ---
        id_group = QGroupBox("Your Project")
        id_layout = QVBoxLayout(id_group)

        name_row = QFormLayout()
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("e.g. Monad, Abstract, MyProtocol")
        name_row.addRow("Project name:", self.project_name_edit)
        id_layout.addLayout(name_row)

        id_layout.addWidget(QLabel("About your project:"))
        self.project_about_edit = QTextEdit()
        self.project_about_edit.setPlaceholderText(
            "What does your project do? What problem does it solve?\n"
            "e.g. \"We're building a parallelized EVM L1 with 10k TPS. "
            "Focused on DeFi and gaming. Community-first approach.\""
        )
        self.project_about_edit.setMaximumHeight(90)
        id_layout.addWidget(self.project_about_edit)

        id_info = QLabel(
            "The project name is used in greetings (gm, g{name}) and the about "
            "text gives the LLM context so replies feel authentic to your project's voice."
        )
        id_info.setWordWrap(True)
        id_info.setStyleSheet("color: gray; font-size: 11px;")
        id_layout.addWidget(id_info)
        layout.addWidget(id_group)

        # --- Do / Don't ---
        rules_group = QGroupBox("Custom Instructions")
        rules_layout = QVBoxLayout(rules_group)

        rules_layout.addWidget(QLabel("DO — things the bot should do:"))
        self.project_do_edit = QTextEdit()
        self.project_do_edit.setPlaceholderText(
            "e.g. mention we have a hackathon coming up, hype the community,\n"
            "use emoji occasionally, reference our testnet launch"
        )
        self.project_do_edit.setMaximumHeight(75)
        rules_layout.addWidget(self.project_do_edit)

        rules_layout.addWidget(QLabel("DON'T — things the bot must avoid:"))
        self.project_dont_edit = QTextEdit()
        self.project_dont_edit.setPlaceholderText(
            "e.g. don't mention token price, don't compare to competitors,\n"
            "don't promise dates, don't use the word 'revolutionary'"
        )
        self.project_dont_edit.setMaximumHeight(75)
        rules_layout.addWidget(self.project_dont_edit)
        layout.addWidget(rules_group)

        # --- Category checkboxes ---
        cat_group = QGroupBox("Categories")
        cat_layout = QVBoxLayout(cat_group)
        cat_layout.addWidget(QLabel(
            "Choose which categories to interact with. "
            "Each category includes relevant project accounts, KOLs, and devs."
        ))

        self.category_checks: dict[str, QCheckBox] = {}
        for cat_name, handles in PROJECT_CATEGORIES.items():
            preview = ", ".join(h.lstrip("@") for h in handles[:4])
            cb = QCheckBox(f"{cat_name}  ({preview}, ...)")
            cb.setChecked(True)
            self.category_checks[cat_name] = cb
            cat_layout.addWidget(cb)

        cat_btn_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_categories(True))
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self._set_all_categories(False))
        cat_btn_row.addWidget(select_all_btn)
        cat_btn_row.addWidget(deselect_all_btn)
        cat_btn_row.addStretch()
        cat_layout.addLayout(cat_btn_row)
        layout.addWidget(cat_group)

        # --- Timeline settings ---
        tl_group = QGroupBox("Timeline Settings")
        tl_layout = QVBoxLayout(tl_group)

        tl_form = QFormLayout()
        self.timeline_comments_spin = QSpinBox()
        self.timeline_comments_spin.setRange(1, 20)
        self.timeline_comments_spin.setSuffix(" comments")
        tl_form.addRow("Comments per sequence:", self.timeline_comments_spin)

        self.timeline_min_likes_spin = QSpinBox()
        self.timeline_min_likes_spin.setRange(10, 10000)
        self.timeline_min_likes_spin.setSuffix(" likes")
        tl_form.addRow("Min likes threshold:", self.timeline_min_likes_spin)
        tl_layout.addLayout(tl_form)
        layout.addWidget(tl_group)

        # --- Info ---
        info = QLabel(
            "Reply-guy mode: scrolls your timeline and replies to ANY post above "
            "the like threshold — hackathons, grants, updates, announcements, memes, "
            "anything. Categories help the LLM understand your ecosystem. "
            "Reads existing replies to match the vibe (sarcasm, memes, hype). "
            "With an LLM key, comments are context-aware. Without one, "
            "falls back to safe templates. Never controversial or offensive."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px; margin-top: 8px;")
        layout.addWidget(info)
        layout.addStretch()

        scroll.setWidget(scroll_widget)
        outer.addWidget(scroll)
        return w

    def _set_all_categories(self, checked: bool):
        for cb in self.category_checks.values():
            cb.setChecked(checked)

    # ------------------------------------------------------------------ #
    #  Degen Farming                                                       #
    # ------------------------------------------------------------------ #

    def _build_degen_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("Degen Farming topics for rotation:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        self.degen_topic_checks: dict[str, QCheckBox] = {}
        for topic in DEFAULT_DEGEN_TOPICS:
            cb = QCheckBox(topic)
            cb.setChecked(True)
            self.degen_topic_checks[topic] = cb
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll, 1)

        degen_btn_row = QHBoxLayout()
        degen_all = QPushButton("Select All")
        degen_all.clicked.connect(lambda: self._toggle_degen_topics(True))
        degen_none = QPushButton("Deselect All")
        degen_none.clicked.connect(lambda: self._toggle_degen_topics(False))
        degen_btn_row.addWidget(degen_all)
        degen_btn_row.addWidget(degen_none)
        degen_btn_row.addStretch()
        layout.addLayout(degen_btn_row)

        layout.addWidget(QLabel("Degen voice override (optional — leave empty for default CT degen style):"))
        self.degen_voice_edit = QTextEdit()
        self.degen_voice_edit.setPlaceholderText(
            "Optional. Override the default crypto degen voice.\n"
            "Default: Crypto native, casual, uses slang (ngmi, wagmi, lfg, ser, anon)."
        )
        self.degen_voice_edit.setMaximumHeight(100)
        layout.addWidget(self.degen_voice_edit)

        # --- Do / Don't ---
        degen_rules_group = QGroupBox("Custom Instructions")
        degen_rules_layout = QVBoxLayout(degen_rules_group)

        degen_rules_layout.addWidget(QLabel("DO — things the bot should do:"))
        self.degen_do_edit = QTextEdit()
        self.degen_do_edit.setPlaceholderText(
            "e.g. focus on SOL ecosystem, shill $MON, be extra bullish on L2s"
        )
        self.degen_do_edit.setMaximumHeight(75)
        degen_rules_layout.addWidget(self.degen_do_edit)

        degen_rules_layout.addWidget(QLabel("DON'T — things the bot must avoid:"))
        self.degen_dont_edit = QTextEdit()
        self.degen_dont_edit.setPlaceholderText(
            "e.g. don't talk about regulation, don't trash other chains,\n"
            "don't give financial advice"
        )
        self.degen_dont_edit.setMaximumHeight(75)
        degen_rules_layout.addWidget(self.degen_dont_edit)
        layout.addWidget(degen_rules_group)

        return w

    def _toggle_degen_topics(self, checked: bool):
        for cb in self.degen_topic_checks.values():
            cb.setChecked(checked)

    # ------------------------------------------------------------------ #
    #  RT Farm                                                             #
    # ------------------------------------------------------------------ #

    def _build_rt_farm_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Clone another profile's retweet history onto your account.\n"
            "Retweets are applied from oldest to newest so the timeline looks organic."
        ))

        form = QFormLayout()

        self.rt_target_edit = QLineEdit()
        self.rt_target_edit.setPlaceholderText("e.g. elonmusk (without @)")
        form.addRow("Target handle:", self.rt_target_edit)

        self.rt_delay_spin = QSpinBox()
        self.rt_delay_spin.setRange(1, 30)
        self.rt_delay_spin.setSuffix(" seconds")
        form.addRow("Delay between RTs:", self.rt_delay_spin)

        self.rt_max_scrolls_spin = QSpinBox()
        self.rt_max_scrolls_spin.setRange(10, 200)
        self.rt_max_scrolls_spin.setSuffix(" scrolls")
        form.addRow("Max scroll depth:", self.rt_max_scrolls_spin)

        layout.addLayout(form)

        info = QLabel(
            "How it works:\n"
            "1. Visits the target profile and scrolls to collect their retweets\n"
            "2. Sorts them oldest-first\n"
            "3. Retweets each one on your account with a delay\n"
            "4. Progress is saved — you can stop and resume anytime\n\n"
            "Higher scroll depth = more retweets collected (but takes longer to scrape)."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px; margin-top: 12px;")
        layout.addWidget(info)
        layout.addStretch()

        return w

    # ------------------------------------------------------------------ #
    #  Sniper                                                              #
    # ------------------------------------------------------------------ #

    def _build_sniper_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel(
            "Viral Sniper mode continuously scans your timeline for rising posts\n"
            "and replies early before they get saturated with comments.\n"
            "Speed is everything — early replies on viral posts get massive exposure."
        ))

        form = QFormLayout()

        self.sniper_interval_spin = QSpinBox()
        self.sniper_interval_spin.setRange(3, 60)
        self.sniper_interval_spin.setSuffix(" minutes")
        form.addRow("Scan interval:", self.sniper_interval_spin)

        self.sniper_velocity_spin = QSpinBox()
        self.sniper_velocity_spin.setRange(10, 5000)
        self.sniper_velocity_spin.setSuffix(" likes/hour")
        form.addRow("Min velocity:", self.sniper_velocity_spin)

        self.sniper_max_replies_spin = QSpinBox()
        self.sniper_max_replies_spin.setRange(5, 500)
        self.sniper_max_replies_spin.setSuffix(" replies")
        form.addRow("Max replies (skip if above):", self.sniper_max_replies_spin)

        self.sniper_per_scan_spin = QSpinBox()
        self.sniper_per_scan_spin.setRange(1, 10)
        self.sniper_per_scan_spin.setSuffix(" replies")
        form.addRow("Replies per scan:", self.sniper_per_scan_spin)

        self.thread_every_n_spin = QSpinBox()
        self.thread_every_n_spin.setRange(2, 20)
        self.thread_every_n_spin.setSuffix(" sequences")
        form.addRow("Post thread every:", self.thread_every_n_spin)

        layout.addLayout(form)

        info = QLabel(
            "Velocity = likes per hour since posted. Higher velocity means the post is trending.\n"
            "Max replies threshold skips already-saturated posts where your reply won't be seen.\n"
            "Thread frequency controls how often dev/degen sequences include a thread post."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px; margin-top: 12px;")
        layout.addWidget(info)
        layout.addStretch()

        return w

    # ------------------------------------------------------------------ #
    #  Intelligence & Behavior                                             #
    # ------------------------------------------------------------------ #

    def _build_intelligence_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Intelligence toggles
        intel_group = QGroupBox("Intelligence")
        intel_layout = QVBoxLayout(intel_group)

        self.llm_classification_check = QCheckBox("Use LLM for post classification (detects sarcasm/irony)")
        intel_layout.addWidget(self.llm_classification_check)

        self.vision_image_check = QCheckBox("Use vision model to verify image relevance (extra API cost)")
        intel_layout.addWidget(self.vision_image_check)

        self.position_memory_check = QCheckBox("Position memory (maintain opinion consistency)")
        intel_layout.addWidget(self.position_memory_check)

        layout.addWidget(intel_group)

        # Daily caps
        caps_group = QGroupBox("Daily Caps (prevent over-posting)")
        caps_form = QFormLayout(caps_group)

        self.daily_max_tweets_spin = QSpinBox()
        self.daily_max_tweets_spin.setRange(1, 50)
        caps_form.addRow("Max tweets/day:", self.daily_max_tweets_spin)

        self.daily_max_comments_spin = QSpinBox()
        self.daily_max_comments_spin.setRange(1, 100)
        caps_form.addRow("Max comments/day:", self.daily_max_comments_spin)

        self.daily_max_likes_spin = QSpinBox()
        self.daily_max_likes_spin.setRange(1, 200)
        caps_form.addRow("Max likes/day:", self.daily_max_likes_spin)

        self.daily_max_follows_spin = QSpinBox()
        self.daily_max_follows_spin.setRange(1, 50)
        caps_form.addRow("Max follows/day:", self.daily_max_follows_spin)

        self.daily_max_qrts_spin = QSpinBox()
        self.daily_max_qrts_spin.setRange(1, 30)
        caps_form.addRow("Max quote RTs/day:", self.daily_max_qrts_spin)

        layout.addWidget(caps_group)

        # Active hours
        hours_group = QGroupBox("Active Hours")
        hours_layout = QVBoxLayout(hours_group)

        self.active_hours_check = QCheckBox("Enable active hours (only post during set window)")
        hours_layout.addWidget(self.active_hours_check)

        hours_form = QFormLayout()

        self.active_hours_start_spin = QSpinBox()
        self.active_hours_start_spin.setRange(0, 23)
        self.active_hours_start_spin.setSuffix(":00")
        hours_form.addRow("Start hour:", self.active_hours_start_spin)

        self.active_hours_end_spin = QSpinBox()
        self.active_hours_end_spin.setRange(0, 23)
        self.active_hours_end_spin.setSuffix(":00")
        hours_form.addRow("End hour:", self.active_hours_end_spin)

        self.active_hours_tz_edit = QLineEdit()
        self.active_hours_tz_edit.setPlaceholderText("e.g. America/New_York, Europe/London, UTC")
        hours_form.addRow("Timezone:", self.active_hours_tz_edit)

        hours_layout.addLayout(hours_form)
        layout.addWidget(hours_group)

        info = QLabel(
            "LLM classification uses an extra API call per comment to detect tone/sarcasm.\n"
            "Vision image check uses an API call per image to verify relevance.\n"
            "Daily caps reset at midnight UTC. Active hours pause sequences outside the window."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-size: 11px; margin-top: 12px;")
        layout.addWidget(info)
        layout.addStretch()

        return w

    # ------------------------------------------------------------------ #
    #  Load / Save                                                         #
    # ------------------------------------------------------------------ #

    def _load_values(self):
        c = self.config

        # Account
        self.chrome_path_edit.setText(c.chrome_profile_path)
        self.profile_dir_edit.setText(c.chrome_profile_directory)
        self.headless_check.setChecked(c.headless)
        self.x_username_edit.setText(c.x_username)
        self.x_password_edit.setText(c.x_password)
        self.x_totp_edit.setText(c.x_totp_secret)

        # Voice
        self.voice_edit.setPlainText(c.voice_description)
        self.bad_examples_edit.setPlainText(c.bad_examples)
        self.good_examples_edit.setPlainText(c.good_examples)

        # Dev Topics
        for topic, cb in self.topic_checks.items():
            cb.setChecked(c.topics.get(topic, True))

        for topic, enabled in c.topics.items():
            if topic not in DEFAULT_TOPICS and topic not in self.topic_checks:
                cb = QCheckBox(topic)
                cb.setChecked(enabled)
                self.topic_checks[topic] = cb
                self._topic_scroll_layout.insertWidget(
                    self._topic_scroll_layout.count() - 1, cb
                )

        # LLM
        if c.llm_provider == "anthropic":
            self.anthropic_radio.setChecked(True)
        else:
            self.openai_radio.setChecked(True)

        self.openai_key_edit.setText(c.openai_api_key)
        self.anthropic_key_edit.setText(c.anthropic_api_key)

        idx = self.openai_model_combo.findText(c.openai_model)
        if idx >= 0:
            self.openai_model_combo.setCurrentIndex(idx)
        idx = self.anthropic_model_combo.findText(c.anthropic_model)
        if idx >= 0:
            self.anthropic_model_combo.setCurrentIndex(idx)

        # Timing
        self.action_delay_spin.setValue(c.action_delay_seconds)
        self.sequence_delay_spin.setValue(c.sequence_delay_minutes)
        self.engagement_spin.setValue(c.min_engagement_likes)

        # Project Farming
        self.project_name_edit.setText(c.project_name)
        self.project_about_edit.setPlainText(c.project_about)
        self.project_do_edit.setPlainText(c.project_do)
        self.project_dont_edit.setPlainText(c.project_dont)

        for cat_name, cb in self.category_checks.items():
            cb.setChecked(c.project_categories.get(cat_name, True))

        self.timeline_comments_spin.setValue(c.project_timeline_comments)
        self.timeline_min_likes_spin.setValue(c.project_timeline_min_likes)

        # Degen Farming
        for topic, cb in self.degen_topic_checks.items():
            cb.setChecked(c.degen_topics.get(topic, True))
        self.degen_voice_edit.setPlainText(c.degen_voice_description)
        self.degen_do_edit.setPlainText(c.degen_do)
        self.degen_dont_edit.setPlainText(c.degen_dont)

        # RT Farm
        self.rt_target_edit.setText(c.rt_farm_target_handle)
        self.rt_delay_spin.setValue(c.rt_farm_delay_seconds)
        self.rt_max_scrolls_spin.setValue(c.rt_farm_max_scrolls)

        # Sniper & Thread
        self.sniper_interval_spin.setValue(c.sniper_scan_interval_minutes)
        self.sniper_velocity_spin.setValue(c.sniper_min_velocity)
        self.sniper_max_replies_spin.setValue(c.sniper_max_replies)
        self.sniper_per_scan_spin.setValue(c.sniper_replies_per_scan)
        self.thread_every_n_spin.setValue(c.thread_every_n_sequences)

        # Intelligence & Behavior
        self.llm_classification_check.setChecked(c.use_llm_classification)
        self.vision_image_check.setChecked(c.use_vision_image_check)
        self.position_memory_check.setChecked(c.position_memory_enabled)
        self.daily_max_tweets_spin.setValue(c.daily_max_tweets)
        self.daily_max_comments_spin.setValue(c.daily_max_comments)
        self.daily_max_likes_spin.setValue(c.daily_max_likes)
        self.daily_max_follows_spin.setValue(c.daily_max_follows)
        self.daily_max_qrts_spin.setValue(c.daily_max_qrts)
        self.active_hours_check.setChecked(c.active_hours_enabled)
        self.active_hours_start_spin.setValue(c.active_hours_start)
        self.active_hours_end_spin.setValue(c.active_hours_end)
        self.active_hours_tz_edit.setText(c.active_hours_timezone)

    def _save(self):
        c = self.config

        # Account
        c.chrome_profile_path = self.chrome_path_edit.text().strip()
        c.chrome_profile_directory = self.profile_dir_edit.text().strip()
        c.headless = self.headless_check.isChecked()
        c.x_username = self.x_username_edit.text().strip()
        c.x_password = self.x_password_edit.text().strip()
        c.x_totp_secret = self.x_totp_edit.text().strip()

        # Voice
        c.voice_description = self.voice_edit.toPlainText()
        c.bad_examples = self.bad_examples_edit.toPlainText()
        c.good_examples = self.good_examples_edit.toPlainText()

        # Dev Topics
        c.topics = {}
        for topic, cb in self.topic_checks.items():
            c.topics[topic] = cb.isChecked()

        enabled_count = sum(1 for v in c.topics.values() if v)
        if enabled_count < 3:
            QMessageBox.warning(self, "Warning", "You need at least 3 dev topics enabled.")
            return

        # LLM
        c.llm_provider = "anthropic" if self.anthropic_radio.isChecked() else "openai"
        c.openai_api_key = self.openai_key_edit.text().strip()
        c.anthropic_api_key = self.anthropic_key_edit.text().strip()
        c.openai_model = self.openai_model_combo.currentText()
        c.anthropic_model = self.anthropic_model_combo.currentText()

        # Timing
        c.action_delay_seconds = self.action_delay_spin.value()
        c.sequence_delay_minutes = self.sequence_delay_spin.value()
        c.min_engagement_likes = self.engagement_spin.value()

        # Project Farming
        c.project_name = self.project_name_edit.text().strip()
        c.project_about = self.project_about_edit.toPlainText().strip()
        c.project_do = self.project_do_edit.toPlainText().strip()
        c.project_dont = self.project_dont_edit.toPlainText().strip()

        c.project_categories = {}
        for cat_name, cb in self.category_checks.items():
            c.project_categories[cat_name] = cb.isChecked()

        c.project_timeline_comments = self.timeline_comments_spin.value()
        c.project_timeline_min_likes = self.timeline_min_likes_spin.value()

        # Degen Farming
        c.degen_topics = {}
        for topic, cb in self.degen_topic_checks.items():
            c.degen_topics[topic] = cb.isChecked()
        c.degen_voice_description = self.degen_voice_edit.toPlainText()
        c.degen_do = self.degen_do_edit.toPlainText().strip()
        c.degen_dont = self.degen_dont_edit.toPlainText().strip()

        # RT Farm
        c.rt_farm_target_handle = self.rt_target_edit.text().strip().lstrip("@")
        c.rt_farm_delay_seconds = self.rt_delay_spin.value()
        c.rt_farm_max_scrolls = self.rt_max_scrolls_spin.value()

        # Sniper & Thread
        c.sniper_scan_interval_minutes = self.sniper_interval_spin.value()
        c.sniper_min_velocity = self.sniper_velocity_spin.value()
        c.sniper_max_replies = self.sniper_max_replies_spin.value()
        c.sniper_replies_per_scan = self.sniper_per_scan_spin.value()
        c.thread_every_n_sequences = self.thread_every_n_spin.value()

        # Intelligence & Behavior
        c.use_llm_classification = self.llm_classification_check.isChecked()
        c.use_vision_image_check = self.vision_image_check.isChecked()
        c.position_memory_enabled = self.position_memory_check.isChecked()
        c.daily_max_tweets = self.daily_max_tweets_spin.value()
        c.daily_max_comments = self.daily_max_comments_spin.value()
        c.daily_max_likes = self.daily_max_likes_spin.value()
        c.daily_max_follows = self.daily_max_follows_spin.value()
        c.daily_max_qrts = self.daily_max_qrts_spin.value()
        c.active_hours_enabled = self.active_hours_check.isChecked()
        c.active_hours_start = self.active_hours_start_spin.value()
        c.active_hours_end = self.active_hours_end_spin.value()
        c.active_hours_timezone = self.active_hours_tz_edit.text().strip() or "UTC"

        c.save()
        self.accept()
