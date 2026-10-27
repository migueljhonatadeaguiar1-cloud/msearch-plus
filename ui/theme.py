"""Temas claro/escuro (QSS)."""
from __future__ import annotations

from string import Template

PALETTES = {
    "light": dict(bg="#ffffff", surface="#f5f6fa", text="#1f2328", muted="#667085", accent="#3b5bdb",
                  accent_hover="#2f49b3", border="#e2e5ee", link="#1a4fd6", ok="#16a34a", bad="#dc2626",
                  warn="#d97706", card="#ffffff", input_bg="#ffffff"),
    "dark": dict(bg="#14161c", surface="#1c1f27", text="#e8eaf0", muted="#9aa3b2", accent="#7c93ff",
                 accent_hover="#9aacff", border="#2c303c", link="#8fa5ff", ok="#4ade80", bad="#f87171",
                 warn="#fbbf24", card="#1a1d25", input_bg="#1c1f27"),
}

_QSS = Template("""
QWidget { background: $bg; color: $text; font-size: 14px; }
QDialog, QMainWindow { background: $bg; }
QLabel { background: transparent; }
QLabel#Muted { color: $muted; }
QLabel#CardDomain { color: $muted; font-size: 12px; }
QLabel#Badge { color: $accent; background: $surface; border: 1px solid $border; border-radius: 8px;
               padding: 1px 8px; font-size: 11px; }
QLabel#Tagline { color: $muted; font-size: 15px; }
QLabel#Notice { color: $warn; }
QLineEdit#SearchInput { background: $input_bg; border: 1px solid $border; border-radius: 22px;
                        padding: 8px 18px; font-size: 16px; selection-background-color: $accent; }
QLineEdit#SearchInput:focus { border: 2px solid $accent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser {
    background: $input_bg; border: 1px solid $border; border-radius: 6px; padding: 4px 6px; }
QPushButton { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { border-color: $accent; }
QPushButton:disabled { color: $muted; }
QPushButton#Primary { background: $accent; color: white; border: none; border-radius: 20px;
                      padding: 9px 22px; font-weight: 600; }
QPushButton#Primary:hover { background: $accent_hover; }
QPushButton#Link { background: transparent; border: none; color: $link; padding: 4px 8px; }
QPushButton#Link:hover { text-decoration: underline; }
QPushButton#Danger { color: $bad; }
QFrame#Card { background: $card; border: 1px solid $border; border-radius: 12px; }
QProgressBar { background: $surface; border: none; border-radius: 3px; }
QProgressBar::chunk { background: $accent; border-radius: 3px; }
QScrollArea { border: none; }
QTabWidget::pane { border: 1px solid $border; border-radius: 8px; }
QTabBar::tab { padding: 8px 16px; background: transparent; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }
QToolButton { background: transparent; border: none; border-radius: 6px; padding: 4px 8px; font-size: 15px; }
QToolButton:hover { background: $surface; }
QToolButton:disabled { color: $muted; }
QToolButton::menu-indicator { image: none; }
QLineEdit#AddressBar { border-radius: 17px; padding: 4px 14px; }
QLineEdit#AddressBar:focus { border: 2px solid $accent; }
QProgressBar#PageProgress { background: transparent; border-radius: 0; }
QProgressBar#PageProgress::chunk { background: $accent; border-radius: 0; }
QLabel#InfoBar { background: $surface; color: $text; border-bottom: 1px solid $border; padding: 6px 12px; }
QTabBar { background: transparent; }
QTabBar::tab { padding: 7px 14px; max-width: 220px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: $surface; }
QTabBar::tab:hover:!selected { background: $surface; }
QMenu { background: $card; border: 1px solid $border; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: $surface; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
""")


def stylesheet(theme: str) -> str:
    return _QSS.substitute(PALETTES.get(theme, PALETTES["light"]))


def palette(theme: str) -> dict:
    return PALETTES.get(theme, PALETTES["light"])
