"""Main window: multi-account tab interface."""

from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QStatusBar,
    QMessageBox,
    QInputDialog,
    QTabBar,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.config import Config
from gui.account_tab import AccountTab
from gui.theme import (
    add_account_button_style,
    MODE_LABELS,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        Config.ensure_default_profile()

        self.setWindowTitle("DevMaker")
        self.setMinimumSize(860, 640)

        self._tabs: dict[str, AccountTab] = {}
        self._build_ui()
        self._load_profiles()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 6)
        root.setSpacing(8)

        # --- Header: title + add account ---
        header = QHBoxLayout()
        title = QLabel("DevMaker")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setStyleSheet("background: transparent;")
        header.addWidget(title)
        header.addStretch()

        add_btn = QPushButton("+ Add Account")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(add_account_button_style())
        add_btn.clicked.connect(self._add_account)
        header.addWidget(add_btn)

        root.addLayout(header)

        # --- Account tabs ---
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self._close_tab)
        self.tab_widget.setMovable(True)

        root.addWidget(self.tab_widget, 1)

        # --- Status bar ---
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status()

    # ------------------------------------------------------------------ #
    #  Profile management                                                  #
    # ------------------------------------------------------------------ #

    def _load_profiles(self):
        """Load all existing profiles as tabs."""
        profiles = Config.list_profiles()
        for name in profiles:
            self._create_tab(name)

        if self.tab_widget.count() == 0:
            self._create_tab("default")

    def _create_tab(self, profile_name: str):
        """Create and add an AccountTab for a profile."""
        tab = AccountTab(profile_name)
        tab.status_changed.connect(self._on_account_status_changed)
        self._tabs[profile_name] = tab

        display_name = profile_name
        cfg = Config.load(profile_name)
        if cfg.x_username:
            display_name = f"@{cfg.x_username.lstrip('@')}"

        self.tab_widget.addTab(tab, display_name)

    def _add_account(self):
        name, ok = QInputDialog.getText(
            self,
            "Add Account",
            "Profile name (e.g. account2, degen-alt, etc.):",
        )
        if not ok or not name.strip():
            return
        name = name.strip().lower().replace(" ", "-")

        if name in self._tabs:
            QMessageBox.warning(self, "DevMaker", f"Profile '{name}' already exists.")
            return

        Config.create_profile(name)
        self._create_tab(name)
        self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)
        self._update_status()

    def _close_tab(self, index: int):
        tab: AccountTab = self.tab_widget.widget(index)
        if tab.is_running:
            QMessageBox.warning(
                self, "DevMaker",
                f"Cannot remove '{tab.profile_name}' while it's running. Stop it first."
            )
            return

        if self.tab_widget.count() <= 1:
            QMessageBox.warning(self, "DevMaker", "You need at least one account.")
            return

        reply = QMessageBox.question(
            self,
            "Remove Account",
            f"Remove profile '{tab.profile_name}' and delete its data?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        profile_name = tab.profile_name
        self.tab_widget.removeTab(index)
        del self._tabs[profile_name]
        Config.delete_profile(profile_name)
        self._update_status()

    # ------------------------------------------------------------------ #
    #  Status                                                              #
    # ------------------------------------------------------------------ #

    def _on_account_status_changed(self, profile_name: str, running: bool):
        self._update_status()
        # Update the tab icon/text to indicate running state
        for i in range(self.tab_widget.count()):
            tab: AccountTab = self.tab_widget.widget(i)
            if tab.profile_name == profile_name:
                cfg = Config.load(profile_name)
                base = f"@{cfg.x_username.lstrip('@')}" if cfg.x_username else profile_name
                label = f"▶ {base}" if running else base
                self.tab_widget.setTabText(i, label)
                break

    def _update_status(self):
        total = len(self._tabs)
        running = sum(1 for t in self._tabs.values() if t.is_running)
        if running > 0:
            self.status_bar.showMessage(f"{running} of {total} accounts running")
        else:
            self.status_bar.showMessage(f"{total} account(s)  |  Ready")

    # ------------------------------------------------------------------ #
    #  Close                                                               #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        running_tabs = [t for t in self._tabs.values() if t.is_running]
        if running_tabs:
            reply = QMessageBox.question(
                self,
                "DevMaker",
                f"{len(running_tabs)} account(s) still running. Stop all and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return
            for tab in running_tabs:
                tab.request_stop()
        event.accept()
