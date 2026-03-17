"""Per-account tab widget: mode selector, controls, state display, log."""

import asyncio
import threading

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QGroupBox,
    QFormLayout,
    QMessageBox,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QTextCursor

from core.config import Config
from core.state_manager import SequenceState
from core.sequence_engine import SequenceEngine
from gui.settings_dialog import SettingsDialog
from gui.theme import (
    mode_button_style,
    start_button_style,
    stop_button_style,
    log_area_style,
    settings_button_style,
    mode_frame_style,
    MODE_LABELS,
    MUTED,
)
from content.rules import FORMAT_CATALOG, DEGEN_FORMAT_CATALOG


class _LogSignal(QObject):
    message = pyqtSignal(str)


class AccountTab(QWidget):
    """Self-contained widget for a single X account / profile."""

    status_changed = pyqtSignal(str, bool)  # (profile_name, running)

    def __init__(self, profile_name: str, parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.config = Config.load(profile_name)
        self.engine: SequenceEngine | None = None
        self._worker_thread: threading.Thread | None = None
        self._running = False

        self._log_signal = _LogSignal()
        self._log_signal.message.connect(self._append_log)

        self._build_ui()
        self._sync_mode_ui()
        self._refresh_state_display()

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------ #
    #  UI                                                                  #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 8)
        root.setSpacing(12)

        # --- Header: account name + settings ---
        header = QHBoxLayout()
        self.account_label = QLabel(self.profile_name)
        self.account_label.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self.account_label.setStyleSheet("background: transparent;")
        header.addWidget(self.account_label)
        header.addStretch()

        settings_btn = QPushButton("Settings")
        settings_btn.setStyleSheet(settings_button_style())
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        root.addLayout(header)

        # --- Mode selector ---
        mode_frame = QFrame()
        mode_frame.setStyleSheet(mode_frame_style())
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setContentsMargins(6, 6, 6, 6)
        mode_layout.setSpacing(6)

        mode_label = QLabel("MODE")
        mode_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        mode_label.setStyleSheet(f"color: {MUTED}; background: transparent; padding-right: 4px;")
        mode_layout.addWidget(mode_label)

        self.mode_buttons: dict[str, QPushButton] = {}
        for mode_key, label in MODE_LABELS.items():
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, m=mode_key: self._select_mode(m))
            self.mode_buttons[mode_key] = btn
            mode_layout.addWidget(btn)

        mode_layout.addStretch()
        root.addWidget(mode_frame)

        # --- Controls row ---
        controls = QHBoxLayout()
        controls.setSpacing(10)

        seq_lbl = QLabel("Sequences:")
        seq_lbl.setStyleSheet("background: transparent;")
        controls.addWidget(seq_lbl)

        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100)
        self.count_spin.setValue(1)
        self.count_spin.setFixedWidth(70)
        controls.addWidget(self.count_spin)

        self.start_btn = QPushButton("Start")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._start)
        controls.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(stop_button_style())
        self.stop_btn.clicked.connect(self._stop)
        controls.addWidget(self.stop_btn)

        controls.addStretch()
        root.addLayout(controls)

        # --- State display ---
        state_group = QGroupBox("Current State")
        state_layout = QFormLayout(state_group)
        state_layout.setHorizontalSpacing(16)
        state_layout.setVerticalSpacing(6)

        self.state_labels: dict[str, QLabel] = {}
        for key in ["mode", "sequence", "format", "topic_1", "topic_2", "extra"]:
            lbl = QLabel("-")
            lbl.setStyleSheet("background: transparent;")
            self.state_labels[key] = lbl

        state_layout.addRow("Mode:", self.state_labels["mode"])
        state_layout.addRow("Sequence #:", self.state_labels["sequence"])
        state_layout.addRow("Last Format:", self.state_labels["format"])
        state_layout.addRow("Topic 1:", self.state_labels["topic_1"])
        state_layout.addRow("Topic 2:", self.state_labels["topic_2"])
        state_layout.addRow("Extra:", self.state_labels["extra"])

        root.addWidget(state_group)

        # --- Log area ---
        log_header = QLabel("Activity Log")
        log_header.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        log_header.setStyleSheet("background: transparent;")
        root.addWidget(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Cascadia Code", 10))
        self.log_area.setStyleSheet(log_area_style())
        root.addWidget(self.log_area, 1)

    # ------------------------------------------------------------------ #
    #  Mode selector                                                       #
    # ------------------------------------------------------------------ #

    def _select_mode(self, mode: str):
        if self._running:
            QMessageBox.warning(self, "DevMaker", "Cannot change mode while running.")
            return
        self.config.farming_mode = mode
        self.config.save()
        self._sync_mode_ui()
        self._refresh_state_display()
        self._log(f"Mode switched to {MODE_LABELS[mode]}.")

    def _sync_mode_ui(self):
        current = self.config.farming_mode
        for mode_key, btn in self.mode_buttons.items():
            btn.setStyleSheet(mode_button_style(mode_key, mode_key == current))
        self.start_btn.setStyleSheet(start_button_style(current))

    # ------------------------------------------------------------------ #
    #  State display                                                       #
    # ------------------------------------------------------------------ #

    def _refresh_state_display(self):
        state = SequenceState.load_for(self.config.data_dir())
        mode = self.config.farming_mode

        self.state_labels["mode"].setText(MODE_LABELS.get(mode, mode))

        if mode == "dev":
            self.state_labels["sequence"].setText(str(state.sequence_number))
            if state.last_format and state.last_format in FORMAT_CATALOG:
                fmt = FORMAT_CATALOG[state.last_format]
                self.state_labels["format"].setText(f"{state.last_format} ({fmt['name']})")
            else:
                self.state_labels["format"].setText("-")
            self.state_labels["topic_1"].setText(state.last_topic_tweet or "-")
            self.state_labels["topic_2"].setText(state.last_topic_qrt or "-")
            self.state_labels["extra"].setText(f"Follows: {len(state.last_follows)}")

        elif mode == "project":
            self.state_labels["sequence"].setText(str(state.project_sequence_number))
            self.state_labels["format"].setText("Reply-guy (timeline)")
            self.state_labels["topic_1"].setText(f"Min likes: {self.config.project_timeline_min_likes}")
            self.state_labels["topic_2"].setText(f"Total comments sent: {state.project_comments_sent}")
            self.state_labels["extra"].setText(f"Target: {self.config.project_timeline_comments} per run")

        elif mode == "degen":
            self.state_labels["sequence"].setText(str(state.degen_sequence_number))
            if state.degen_last_format and state.degen_last_format in DEGEN_FORMAT_CATALOG:
                fmt = DEGEN_FORMAT_CATALOG[state.degen_last_format]
                self.state_labels["format"].setText(f"{state.degen_last_format} ({fmt['name']})")
            else:
                self.state_labels["format"].setText("-")
            self.state_labels["topic_1"].setText(state.degen_last_topic or "-")
            self.state_labels["topic_2"].setText("-")
            self.state_labels["extra"].setText("-")

        elif mode == "rt_farm":
            self.state_labels["sequence"].setText("-")
            self.state_labels["format"].setText("Retweet cloning")
            target = self.config.rt_farm_target_handle
            self.state_labels["topic_1"].setText(f"Target: @{target}" if target else "No target set")
            self.state_labels["topic_2"].setText(f"Retweeted: {state.rt_farm_total_retweeted}")
            self.state_labels["extra"].setText(f"Queued: {len(state.rt_farm_completed_urls)} done")

        elif mode == "sniper":
            self.state_labels["sequence"].setText("-")
            self.state_labels["format"].setText("Viral reply sniper")
            self.state_labels["topic_1"].setText(f"Min velocity: {self.config.sniper_min_velocity}/h")
            self.state_labels["topic_2"].setText(f"Total replies: {state.sniper_total_replies}")
            self.state_labels["extra"].setText(f"Scan interval: {self.config.sniper_scan_interval_minutes}min")

    # ------------------------------------------------------------------ #
    #  Settings                                                            #
    # ------------------------------------------------------------------ #

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config = Config.load(self.profile_name)
            self._sync_mode_ui()
            self._refresh_state_display()
            self._log("Settings saved.")

    # ------------------------------------------------------------------ #
    #  Log                                                                 #
    # ------------------------------------------------------------------ #

    def _log(self, msg: str):
        self._log_signal.message.emit(msg)

    def _append_log(self, msg: str):
        if msg == "__DONE__":
            self._on_finished()
            return
        self.log_area.append(msg)
        self.log_area.moveCursor(QTextCursor.MoveOperation.End)

    # ------------------------------------------------------------------ #
    #  Start / Stop                                                        #
    # ------------------------------------------------------------------ #

    def _start(self):
        mode = self.config.farming_mode

        if not self.config.chrome_profile_path:
            QMessageBox.warning(self, "Error", "Set Chrome profile path in Settings first.")
            return

        if mode in ("dev", "degen") and not self.config.active_api_key():
            QMessageBox.warning(
                self, "Error",
                f"No API key set for {self.config.llm_provider}. Configure in Settings > LLM."
            )
            return

        if mode == "dev" and len(self.config.enabled_topics()) < 3:
            QMessageBox.warning(self, "Error", "Enable at least 3 topics in Settings > Topics.")
            return

        if mode == "project" and not self.config.active_api_key():
            QMessageBox.warning(
                self, "Warning",
                "No LLM API key configured. Project Farming will use\n"
                "template replies only. Configure one in Settings > LLM\n"
                "for context-aware comments."
            )

        if mode == "degen" and len(self.config.enabled_degen_topics()) < 2:
            QMessageBox.warning(self, "Error", "Enable at least 2 degen topics in Settings > Degen Farming.")
            return

        if mode == "rt_farm" and not self.config.rt_farm_target_handle:
            QMessageBox.warning(self, "Error", "Set a target handle in Settings > RT Farm first.")
            return

        if mode == "sniper" and not self.config.active_api_key():
            QMessageBox.warning(
                self, "Error",
                f"No API key set for {self.config.llm_provider}. Configure in Settings > LLM."
            )
            return

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.count_spin.setEnabled(False)
        for btn in self.mode_buttons.values():
            btn.setEnabled(False)
        self.status_changed.emit(self.profile_name, True)

        count = self.count_spin.value()
        self.engine = SequenceEngine(self.config, log_fn=self._log)

        self._worker_thread = threading.Thread(
            target=self._run_in_thread, args=(count,), daemon=True
        )
        self._worker_thread.start()

    def _run_in_thread(self, count: int):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.engine.run_batch(count))
        except Exception as e:
            self._log(f"FATAL ERROR: {e}")
        finally:
            loop.close()
            self._log_signal.message.emit("__DONE__")

    def _stop(self):
        if self.engine:
            self.engine.cancel()
        self._log("Stopping after current action...")
        self.stop_btn.setEnabled(False)

    def _on_finished(self):
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.count_spin.setEnabled(True)
        for btn in self.mode_buttons.values():
            btn.setEnabled(True)
        self._sync_mode_ui()
        self._refresh_state_display()
        self.status_changed.emit(self.profile_name, False)

    def request_stop(self):
        """External stop request (e.g. from window close)."""
        if self._running and self.engine:
            self.engine.cancel()
