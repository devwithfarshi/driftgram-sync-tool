"""Driftgram: colours and the stylesheet built from them.

Qt's native styling is fine but inconsistent between Windows 11 and the
various Linux desktops, and this app is the same product on both. So the
palette is defined once here and applied as a stylesheet, with a light and a
dark set chosen from the system's own colour-scheme hint - a user who runs
their desktop in dark mode should not be handed a white window at midnight.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    accent_soft: str
    success: str
    warning: str
    danger: str
    is_dark: bool


LIGHT = Palette(
    bg="#FFFFFF",
    surface="#F7F9FB",
    surface_alt="#EEF2F6",
    border="#DFE5EC",
    text="#111C29",
    muted="#5C6B7F",
    accent="#1C82C4",
    accent_text="#FFFFFF",
    accent_soft="#E7F2FA",
    success="#1E8E4E",
    warning="#B4740B",
    danger="#C42B30",
    is_dark=False,
)

DARK = Palette(
    bg="#15181C",
    surface="#1C2026",
    surface_alt="#242A31",
    border="#313943",
    text="#E9EEF4",
    muted="#9AA7B6",
    accent="#38B6F1",
    accent_text="#0A1218",
    accent_soft="#1B2C38",
    success="#4ED084",
    warning="#E3A93B",
    danger="#F0666B",
    is_dark=True,
)


def current_palette() -> Palette:
    """Light or dark, following the desktop's own preference."""
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        return DARK if scheme == Qt.ColorScheme.Dark else LIGHT
    except Exception:
        # Older Qt or an unusual platform plugin: light is the safer guess,
        # because every colour in it is defined against a white background.
        return LIGHT


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{
        color: {p.text};
        font-size: 14px;
    }}
    QMainWindow, QDialog {{ background: {p.bg}; }}

    /* ---- sidebar ---- */
    #Sidebar {{
        background: {p.surface};
        border-right: 1px solid {p.border};
    }}
    #Sidebar QPushButton {{
        text-align: left;
        padding: 10px 14px;
        border: none;
        border-radius: 8px;
        color: {p.muted};
        font-weight: 500;
        background: transparent;
    }}
    #Sidebar QPushButton:hover {{ background: {p.surface_alt}; color: {p.text}; }}
    #Sidebar QPushButton:checked {{
        background: {p.accent_soft};
        color: {p.accent};
        font-weight: 600;
    }}
    #BrandName {{ font-size: 17px; font-weight: 700; color: {p.text}; }}
    #BrandTag  {{ font-size: 11px; color: {p.muted}; }}

    /* ---- cards & typography ---- */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    #CardTight {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 10px;
    }}
    #PageTitle {{ font-size: 22px; font-weight: 700; }}
    #PageHint  {{ color: {p.muted}; }}
    #StatusHeadline {{ font-size: 20px; font-weight: 700; }}
    #StatusDetail   {{ color: {p.muted}; }}
    #StatNumber {{ font-size: 22px; font-weight: 700; }}
    #StatLabel  {{ color: {p.muted}; font-size: 12px; }}
    #Muted {{ color: {p.muted}; }}
    #Danger {{ color: {p.danger}; }}
    #SectionTitle {{ font-weight: 600; font-size: 15px; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px 16px;
        color: {p.text};
    }}
    QPushButton:hover  {{ background: {p.border}; }}
    QPushButton:disabled {{ color: {p.muted}; background: {p.surface}; }}
    QPushButton#Primary {{
        background: {p.accent};
        color: {p.accent_text};
        border: 1px solid {p.accent};
        font-weight: 600;
    }}
    QPushButton#Primary:hover    {{ background: {p.accent}; }}
    QPushButton#Primary:disabled {{ background: {p.surface_alt}; color: {p.muted}; border-color: {p.border}; }}
    QPushButton#Link {{
        background: transparent; border: none; color: {p.accent};
        padding: 2px 4px; text-align: left;
    }}
    QPushButton#Link:hover {{ text-decoration: underline; background: transparent; }}
    QPushButton#DangerButton {{ color: {p.danger}; }}

    /* ---- inputs ---- */
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background: {p.bg};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {p.accent};
        selection-color: {p.accent_text};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {p.accent}; }}
    QLineEdit#CodeEntry {{
        font-size: 24px; letter-spacing: 8px; padding: 12px;
        qproperty-alignment: AlignCenter;
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p.bg}; border: 1px solid {p.border};
        selection-background-color: {p.accent_soft}; selection-color: {p.text};
    }}
    /* Indicators are styled explicitly because the native ones use the
       desktop's accent colour - on Windows that is whatever the user picked,
       which lands a pink tick in the middle of a blue app. */
    QCheckBox, QRadioButton {{ spacing: 9px; padding: 3px 0; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px;
        background: {p.bg};
        border: 2px solid {p.muted};
    }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    /* Exactly half the 16px box: any larger and Qt renders a rounded square
       instead of a circle once the border thickens on :checked. */
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {p.accent}; }}
    QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}
    /* A thick border would give the classic ring-and-dot, but Qt stops
       honouring border-radius once the border gets that heavy and draws a
       rounded square instead. A radial gradient paints the inner dot inside
       a thin, reliably round border. */
    QRadioButton::indicator:checked {{
        border: 2px solid {p.accent};
        border-radius: 8px;
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {p.accent}, stop:0.55 {p.accent}, stop:0.62 {p.bg}, stop:1 {p.bg});
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {p.border}; }}

    /* ---- tables & lists ---- */
    QTableWidget, QTreeWidget, QListWidget {{
        background: {p.bg};
        border: 1px solid {p.border};
        border-radius: 10px;
        gridline-color: {p.border};
    }}
    QTableWidget::item, QListWidget::item {{ padding: 6px 4px; }}
    QTableWidget::item:selected, QListWidget::item:selected {{
        background: {p.accent_soft}; color: {p.text};
    }}
    QHeaderView::section {{
        background: {p.surface};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 8px 6px;
        color: {p.muted};
        font-weight: 600;
    }}
    #ActivityList {{ border: none; background: transparent; }}
    #ActivityList::item {{ border-bottom: 1px solid {p.border}; padding: 8px 2px; }}

    /* ---- misc ---- */
    QProgressBar {{
        background: {p.surface_alt};
        border: none; border-radius: 5px;
        height: 8px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {p.accent}; border-radius: 5px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    #Separator {{ background: {p.border}; max-height: 1px; border: none; }}
    QToolTip {{
        background: {p.surface_alt}; color: {p.text};
        border: 1px solid {p.border}; padding: 6px; border-radius: 6px;
    }}
    """


def apply(app) -> Palette:
    palette = current_palette()
    app.setStyleSheet(stylesheet(palette))
    return palette
