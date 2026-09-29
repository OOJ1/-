"""界面主题：浅色 + 圆角卡片，QSS 集中管理。

所有颜色/圆角集中在这里，改主题只动这个文件。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

# 调色板
BG = "#FFFFFF"
SURFACE = "#F6F7F9"
SURFACE_HOVER = "#EDEFF3"
BORDER = "#E4E7EC"
BORDER_STRONG = "#D3D8E0"
TEXT = "#1A1D21"
TEXT_MUTED = "#6B7280"
PRIMARY = "#3B6EF6"
PRIMARY_HOVER = "#2F5FE0"
PRIMARY_PRESSED = "#2851C4"
SUCCESS = "#12A150"
DANGER = "#E5484D"
DANGER_HOVER = "#D13438"
WARNING = "#C77700"

RADIUS = 12

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "PingFang SC", sans-serif'
MONO_FAMILY = '"Cascadia Mono", "Consolas", "Courier New", monospace'


def app_font(size: int = 12) -> QFont:
    """选一个系统里真实存在的中文字体，避免方块字。"""
    families = set(QFontDatabase.families())
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Segoe UI", "Arial"):
        if name in families:
            f = QFont(name, size)
            f.setHintingPreference(QFont.PreferFullHinting)
            return f
    return QFont("", size)


STYLESHEET = f"""
QWidget {{
    font-family: {FONT_FAMILY};
    color: {TEXT};
}}

#card {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}}

#bubble {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY_PRESSED};
    border-radius: 28px;
}}
#bubble:hover {{ background: {PRIMARY_HOVER}; }}

#titleLabel {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT};
}}

#subLabel, #hintLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: #A9B0BB; background: {SURFACE}; }}

QPushButton#primary {{
    background: {PRIMARY};
    border: 1px solid {PRIMARY};
    color: #FFFFFF;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton#primary:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton#primary:disabled {{ background: #B9C7F2; border-color: #B9C7F2; color: #FFFFFF; }}

QPushButton#danger {{ color: {DANGER}; border-color: #F3C9CB; background: #FFF5F5; }}
QPushButton#danger:hover {{ background: #FFE9EA; border-color: {DANGER}; }}

QPushButton#iconBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 6px;
    color: {TEXT_MUTED};
    font-size: 13px;
}}
QPushButton#iconBtn:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton#iconBtn:checked {{ background: #E8EFFE; color: {PRIMARY}; }}

QPushButton#seg {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    color: {TEXT_MUTED};
}}
QPushButton#seg:hover {{ color: {TEXT}; }}
QPushButton#seg:checked {{
    background: {BG};
    border-color: {BORDER};
    color: {PRIMARY};
    font-weight: 600;
}}

#segWrap {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QPlainTextEdit, QTextBrowser, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 8px;
    selection-background-color: #CBD9FB;
    selection-color: {TEXT};
}}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PRIMARY};
}}
QTextBrowser {{ background: {BG}; border: 1px solid {BORDER}; }}
QTextBrowser#answer {{ background: #FCFCFD; }}

QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {BG};
    border: 1px solid {BORDER};
    selection-background-color: #E8EFFE;
    selection-color: {TEXT};
    outline: none;
}}

QProgressBar {{
    background: {SURFACE};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 3px; }}

QCheckBox {{ spacing: 6px; color: {TEXT}; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER_STRONG};
    border-radius: 4px;
    background: {BG};
}}
QCheckBox::indicator:checked {{
    background: {PRIMARY};
    border-color: {PRIMARY};
    image: none;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {TEXT_MUTED};
}}

QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 10px; background: {BG}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    padding: 7px 14px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{
    background: {BG};
    border-color: {BORDER};
    border-bottom-color: {BG};
    color: {PRIMARY};
    font-weight: 600;
}}

QTableWidget {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {SURFACE};
    selection-background-color: #E8EFFE;
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    color: {TEXT_MUTED};
    font-weight: 600;
}}
QTableWidget::item {{ padding: 4px; }}

QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D6DAE1; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #BEC4CE; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #D6DAE1; border-radius: 4px; min-width: 24px; }}

QToolTip {{
    background: #2B2F36;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 4px 8px;
}}

QSplitter::handle {{ background: {BORDER}; }}
"""


def make_app_icon(size: int = 256) -> QIcon:
    """程序内绘制图标，避免携带二进制资源文件。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(PRIMARY))
        radius = size * 0.22
        p.drawRoundedRect(0, 0, size, size, radius, radius)
        p.setPen(QColor("#FFFFFF"))
        font = app_font(int(size * 0.52))
        font.setBold(True)
        p.setFont(font)
        p.drawText(pm.rect(), Qt.AlignCenter, "鸡")
    finally:
        p.end()
    return QIcon(pm)


def bubble_icon(size: int = 56) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(PRIMARY))
        p.drawEllipse(0, 0, size, size)
        p.setPen(QColor("#FFFFFF"))
        font = app_font(int(size * 0.42))
        font.setBold(True)
        p.setFont(font)
        p.drawText(pm.rect(), Qt.AlignCenter, "鸡")
    finally:
        p.end()
    return pm
