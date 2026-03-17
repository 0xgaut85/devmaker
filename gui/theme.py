"""iOS Liquid Glass dark theme — monochrome black & white aesthetic."""

# ── Core palette ──────────────────────────────────────────────────────
BLACK = "#000000"
NEAR_BLACK = "#0a0a0a"
DARK = "#111111"
SURFACE = "#1a1a1a"
SURFACE_LIGHT = "#222222"
BORDER = "#2a2a2a"
BORDER_LIGHT = "#333333"
DIM = "#555555"
MUTED = "#888888"
SUBTEXT = "#999999"
TEXT = "#e5e5e5"
WHITE = "#ffffff"

# Glass-panel helpers (Qt stylesheet supports rgba)
GLASS_BG = "rgba(255, 255, 255, 6)"       # ~2 % white
GLASS_BG_HOVER = "rgba(255, 255, 255, 15)" # ~6 % white
GLASS_BORDER = "rgba(255, 255, 255, 20)"   # ~8 % white

MODE_LABELS = {
    "dev": "Dev Farming",
    "project": "Project Farming",
    "degen": "Degen Farming",
    "rt_farm": "RT Farm",
    "sniper": "Sniper",
}


def global_stylesheet() -> str:
    return f"""
    QMainWindow, QDialog {{
        background-color: {BLACK};
        color: {TEXT};
    }}
    QWidget {{
        background-color: {BLACK};
        color: {TEXT};
        font-family: "SF Pro Display", "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
        font-size: 13px;
    }}
    QLabel {{
        color: {TEXT};
        background: transparent;
    }}
    QGroupBox {{
        border: 1px solid {BORDER};
        border-radius: 12px;
        margin-top: 14px;
        padding: 18px 14px 14px 14px;
        font-weight: 600;
        color: {SUBTEXT};
        background-color: {NEAR_BLACK};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 8px;
        color: {SUBTEXT};
    }}
    QLineEdit, QTextEdit, QSpinBox, QComboBox {{
        background-color: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 12px;
        selection-background-color: {WHITE};
        selection-color: {BLACK};
    }}
    QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
        border-color: {DIM};
    }}
    QComboBox::drop-down {{
        border: none;
        padding-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {SURFACE_LIGHT};
    }}
    QPushButton {{
        background-color: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 20px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {SURFACE_LIGHT};
        border-color: {BORDER_LIGHT};
    }}
    QPushButton:pressed {{
        background-color: {BORDER};
    }}
    QPushButton:disabled {{
        background-color: {NEAR_BLACK};
        color: {DIM};
        border-color: {SURFACE};
    }}
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 5px;
        border: 1px solid {BORDER_LIGHT};
        background-color: {SURFACE};
    }}
    QCheckBox::indicator:checked {{
        background-color: {WHITE};
        border-color: {WHITE};
    }}
    QRadioButton {{
        color: {TEXT};
        spacing: 8px;
        background: transparent;
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 8px;
        border: 1px solid {BORDER_LIGHT};
        background-color: {SURFACE};
    }}
    QRadioButton::indicator:checked {{
        background-color: {WHITE};
        border-color: {WHITE};
    }}
    QTabWidget::pane {{
        border: 1px solid {BORDER};
        border-radius: 10px;
        background-color: {BLACK};
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: transparent;
        color: {MUTED};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 10px 18px;
        margin-right: 2px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{
        color: {WHITE};
        border-bottom: 2px solid {WHITE};
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT};
    }}
    QScrollArea {{
        border: none;
        background-color: {BLACK};
    }}
    QScrollBar:vertical {{
        background-color: transparent;
        width: 6px;
        border-radius: 3px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BORDER_LIGHT};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {DIM};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QStatusBar {{
        background-color: {NEAR_BLACK};
        color: {MUTED};
        border-top: 1px solid {BORDER};
        padding: 4px 14px;
        font-size: 12px;
    }}
    QFormLayout {{
        background: transparent;
    }}
    """


def mode_button_style(mode: str, active: bool) -> str:
    if active:
        return (
            f"QPushButton {{ background-color: {WHITE}; color: {BLACK}; "
            f"font-weight: bold; padding: 8px 20px; border-radius: 10px; "
            f"border: none; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {TEXT}; }}"
        )
    return (
        f"QPushButton {{ background-color: {SURFACE}; color: {MUTED}; "
        f"font-weight: 600; padding: 8px 20px; border-radius: 10px; "
        f"border: 1px solid {BORDER}; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {SURFACE_LIGHT}; color: {TEXT}; }}"
    )


def start_button_style(mode: str = "") -> str:
    return (
        f"QPushButton {{ background-color: {WHITE}; color: {BLACK}; font-weight: bold; "
        f"padding: 8px 24px; border-radius: 10px; border: none; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {TEXT}; }}"
    )


def stop_button_style() -> str:
    return (
        f"QPushButton {{ background-color: {SURFACE}; color: #ff4444; font-weight: bold; "
        f"padding: 8px 24px; border-radius: 10px; border: 1px solid #ff4444; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: #1a0000; border-color: #ff6666; color: #ff6666; }}"
        f"QPushButton:disabled {{ background-color: {NEAR_BLACK}; color: {DIM}; border-color: {SURFACE}; }}"
    )


def log_area_style() -> str:
    return (
        f"QTextEdit {{ background-color: {NEAR_BLACK}; color: {TEXT}; "
        f"border: 1px solid {BORDER}; border-radius: 10px; padding: 12px; "
        f"font-family: 'SF Mono', 'Cascadia Code', 'Consolas', 'Fira Code', monospace; "
        f"font-size: 12px; }}"
    )


def settings_button_style() -> str:
    return (
        f"QPushButton {{ background-color: transparent; color: {MUTED}; "
        f"padding: 6px 16px; border-radius: 10px; border: 1px solid {BORDER}; }}"
        f"QPushButton:hover {{ background-color: {SURFACE}; color: {TEXT}; "
        f"border-color: {BORDER_LIGHT}; }}"
    )


def add_account_button_style() -> str:
    return (
        f"QPushButton {{ background-color: {WHITE}; color: {BLACK}; font-weight: bold; "
        f"padding: 7px 18px; border-radius: 10px; border: none; font-size: 13px; }}"
        f"QPushButton:hover {{ background-color: {TEXT}; }}"
    )


def mode_frame_style() -> str:
    return (
        f"QFrame {{ background-color: {NEAR_BLACK}; border: 1px solid {BORDER}; "
        f"border-radius: 12px; padding: 4px; }}"
    )
