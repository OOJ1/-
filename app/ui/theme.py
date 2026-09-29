"""界面主题：浅色 + 圆角卡片，QSS 集中管理。

所有颜色/圆角集中在这里，改主题只动这个文件。
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

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


# ---------------------------------------------------------------- 像素小鸡

# 16×16 像素画。字符含义：
#   .  透明        K  描边（深暖褐）   B  主体金黄
#   D  暗部        H  高光奶油         R  嘴 / 脚 / 鸡冠（橙）
#   E  瞳孔        W  眼里的高光点
#
# 每一行都必须是 16 个字符 —— ui_smoke 会断言这一点，写歪了会有人告诉你。
PIXEL_CHICK: tuple[str, ...] = (
    ".......KK.......",
    "......KRRK......",
    ".....KKRRKK.....",
    "....KKBBBBKK....",
    "...KBBBBBBBBK...",
    "..KBHHBBBBBBBK..",
    "..KBHHBBBBBBBK..",
    "..KBBWEBBWEBBK..",
    "..KBBEEBBEEBBK..",
    "..KBBBBBBBBBBK..",
    "..KBBBBRRBBBBK..",
    "..KBBBBRRBBBBK..",
    "...KDBBBBBBDK...",
    "....KDDDDDDK....",
    "....KRK..KRK....",
    "................",
)

# 像素画的描边刻意用「很深的暖褐」而不是纯黑：压在深靛蓝球体上时它会几乎
# 融进背景，于是视觉上只剩一个亮黄的轮廓 —— 比一圈硬黑边通透得多。
_CHICK_COLORS: dict[str, QColor] = {
    "K": QColor(42, 26, 10),
    "B": QColor(255, 206, 74),
    "D": QColor(226, 152, 42),
    "H": QColor(255, 243, 179),
    "R": QColor(255, 138, 61),
    "E": QColor(34, 24, 14),
    "W": QColor(255, 255, 255),
}

_CHICK_IMG: QImage | None = None


def _chick_image() -> QImage:
    """把图案烘焙成 16×16 的位图，一像素一格。

    直接在 paintEvent 里循环 drawRect 有两个毛病：相邻格的浮点边界会互相
    漏出 1px 缝，而且非等比缩放时缝会忽宽忽窄。烘成图再整体放大就干净了。
    """
    global _CHICK_IMG
    if _CHICK_IMG is not None:
        return _CHICK_IMG
    n = len(PIXEL_CHICK)
    img = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    for row, line in enumerate(PIXEL_CHICK):
        for col, ch in enumerate(line):
            color = _CHICK_COLORS.get(ch)
            if color is not None:
                img.setPixelColor(col, row, color)
    _CHICK_IMG = img
    return img


def paint_pixel_chick(p: QPainter, cx: float, cy: float, size: float) -> None:
    """在 (cx, cy) 为中心、边长 size 的方框里画那只像素小鸡。

    size 按图案整体（含四周的透明留白）算，所以调用方给的值可以略大于
    肉眼看到的鸡 —— 图案本身不是满格的。
    """
    img = _chick_image()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setRenderHint(QPainter.SmoothPixmapTransform, False)   # 最近邻：像素才是硬的
    p.setPen(Qt.NoPen)
    p.drawImage(QRectF(cx - size / 2.0, cy - size / 2.0, size, size), img)


def paint_jelly_halo(p: QPainter, cx: float, cy: float, r: float,
                     glow: float = 0.0, scale: float = 1.0,
                     limit: float | None = None) -> None:
    """球体外那圈发光。

    刻意单独拆出来：它**不能**跟着球体一起做非等比形变。跟着放大就会顶到
    窗口边界被裁成直边，看起来像「球旁边还有一块方的东西也在跟着放大」。
    limit 是硬上限（通常取窗口半宽），保证任何缩放下都不溢出。
    """
    halo = r * (1.16 + 0.22 * glow) * scale
    if limit is not None:
        halo = min(halo, limit)
    g = QRadialGradient(QPointF(cx, cy + r * 0.10), halo)
    g.setColorAt(0.00, QColor(59, 110, 246, int(54 + 54 * glow)))
    g.setColorAt(0.55, QColor(70, 122, 250, int(30 + 30 * glow)))
    g.setColorAt(1.00, QColor(90, 140, 255, 0))
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy + r * 0.10), halo, halo)


def paint_jelly_body(p: QPainter, cx: float, cy: float, r: float) -> None:
    """球体本身：渐变 + 折射环 + 高光 + 球内反光 + 像素小鸡。

    调用方负责用 painter 的 transform 做弹性形变，这里只画正圆，
    于是弹性和质感互不干扰。

    底色走「深靛蓝玻璃」：左上受光偏亮、右下沉到近黑，冷青环境反射压在
    右下角。深底 + 亮暖色的像素鸡，对比拉满，比原先的亮蓝球高级得多。
    """
    p.setRenderHint(QPainter.Antialiasing, True)

    # 1) 球体：光源在左上，右下压暗。
    #    边缘刻意留一点半透明——窗口本身是透明背景，这点 alpha 会让球
    #    真的透出底下的桌面，比纯实心圆通透。
    core = QRadialGradient(QPointF(cx - r * 0.34, cy - r * 0.40), r * 1.85)
    core.setColorAt(0.00, QColor(92, 100, 124, 252))
    core.setColorAt(0.22, QColor(66, 73, 95, 250))
    core.setColorAt(0.48, QColor(45, 51, 68, 246))
    core.setColorAt(0.72, QColor(30, 34, 47, 240))
    core.setColorAt(0.90, QColor(19, 22, 31, 232))
    core.setColorAt(1.00, QColor(11, 13, 19, 212))
    p.setPen(Qt.NoPen)
    p.setBrush(core)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # 2) 球内附加层统一裁剪，省掉多次 save/restore
    clip = QPainterPath()
    clip.addEllipse(QPointF(cx, cy), r, r)
    p.save()
    p.setClipPath(clip)

    # 2a) 上半部整体提亮：做出「上亮下暗」的大趋势。只给一个高光斑的话，
    #     球体中间会平掉；有了这个大趋势才有体积。
    #     深底上这层要收着给 —— 70 的白会在球上半部糊出一片灰雾，
    #     球立刻从「深色玻璃」变成「塑料球」。
    top = QLinearGradient(cx, cy - r, cx, cy + r * 0.20)
    top.setColorAt(0.00, QColor(255, 255, 255, 44))
    top.setColorAt(1.00, QColor(255, 255, 255, 0))
    p.setBrush(top)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # 2b) 环境反射：右下角一抹冷青。玻璃球之所以「活」就靠它，
    #     只有一个纯蓝渐变会立刻显得像塑料片。
    #     底色变深之后这里要抬一点亮度，否则那抹青会被吃掉。
    env = QRadialGradient(QPointF(cx + r * 0.50, cy + r * 0.36), r * 0.80)
    env.setColorAt(0.00, QColor(128, 226, 255, 76))
    env.setColorAt(1.00, QColor(128, 226, 255, 0))
    p.setBrush(env)
    p.drawEllipse(QPointF(cx + r * 0.50, cy + r * 0.36), r * 0.74, r * 0.68)

    # 2c) 底部透射反光：刻意用暖金而不是白 —— 球底映出小鸡的金色，冷底 +
    #     一点暖反光才是「贵」的来源（纯白反光只会像球里装了水）。
    #     强度压在 88：再亮一点就会吃掉小鸡的脚（脚本来就是橙的）。
    bt = QRadialGradient(QPointF(cx + r * 0.06, cy + r * 0.66), r * 0.74)
    bt.setColorAt(0.00, QColor(255, 208, 138, 88))
    bt.setColorAt(1.00, QColor(255, 208, 138, 0))
    p.setBrush(bt)
    p.drawEllipse(QPointF(cx + r * 0.06, cy + r * 0.64), r * 0.66, r * 0.38)

    # 2d) 下缘透光弧：光从球体里透出来，是「半透明」的关键。
    #     深底上给到 170 会变成一条灰白色的脏带，压到 118 才像透光。
    rim = QLinearGradient(cx, cy, cx, cy + r)
    rim.setColorAt(0.00, QColor(214, 234, 255, 0))
    rim.setColorAt(1.00, QColor(214, 234, 255, 118))
    p.setPen(QPen(QBrush(rim), r * 0.13))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy + r * 0.05), r * 0.95, r * 0.95)
    p.restore()

    # 3) 边缘折射环：锥形渐变让上、下缘发亮、两侧转暗。
    #    一圈均匀的白边会立刻变成「塑料按钮」，这是果冻和塑料的分界线。
    ring = QConicalGradient(QPointF(cx, cy), 90.0)
    ring.setColorAt(0.00, QColor(255, 255, 255, 216))   # 正上
    ring.setColorAt(0.22, QColor(255, 255, 255, 20))
    ring.setColorAt(0.50, QColor(188, 218, 255, 152))   # 正下：偏冷，呼应环境光
    ring.setColorAt(0.78, QColor(255, 255, 255, 20))
    ring.setColorAt(1.00, QColor(255, 255, 255, 216))
    d = max(1.0, r * 0.05)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QBrush(ring), d))
    p.drawEllipse(QPointF(cx, cy), r - d * 0.9, r - d * 0.9)

    # 4) 左上主高光斑：贴左上边缘走 —— 放在正中间会被像素鸡整个盖住。
    #    深底上的高光要收着给：一整块高 alpha 的白会立刻把球变成塑料球。
    hl = QRadialGradient(QPointF(cx - r * 0.38, cy - r * 0.50), r * 0.58)
    hl.setColorAt(0.00, QColor(255, 255, 255, 148))
    hl.setColorAt(0.42, QColor(255, 255, 255, 54))
    hl.setColorAt(1.00, QColor(255, 255, 255, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(hl)
    p.drawEllipse(QPointF(cx - r * 0.38, cy - r * 0.50), r * 0.50, r * 0.38)

    # 4b) 镜面小高光点：果冻的「湿亮」就靠这一点，不能省
    sp = QRadialGradient(QPointF(cx - r * 0.42, cy - r * 0.54), r * 0.17)
    sp.setColorAt(0.00, QColor(255, 255, 255, 232))
    sp.setColorAt(0.55, QColor(255, 255, 255, 84))
    sp.setColorAt(1.00, QColor(255, 255, 255, 0))
    p.setBrush(sp)
    p.drawEllipse(QPointF(cx - r * 0.42, cy - r * 0.54), r * 0.16, r * 0.12)

    # 5) 球心那只像素小鸡。
    #    size 取 1.62r 是量出来的：图案四周本来就留白（16 格里只用中间
    #    12×15），给到 1.62r 时鸡的轮廓正好卡在球的内接正方形内；再大一点
    #    头顶的呆毛和脚就会顶到圆弧被裁掉。
    #    纵向偏移只给 0.005r：往下挪多了，脚会掉进底部那圈暖金反光里糊掉。
    paint_pixel_chick(p, cx, cy + r * 0.005, r * 1.62)


def paint_jelly(p: QPainter, cx: float, cy: float, r: float,
                glow: float = 0.0) -> None:
    """完整画一遍果冻球（静态位图、文档截图等场合用）。"""
    paint_jelly_halo(p, cx, cy, r, glow)
    paint_jelly_body(p, cx, cy, r)


def bubble_icon(size: int = 56) -> QPixmap:
    """静态果冻球位图（预览、文档截图等场合用；悬浮球本体是自绘控件）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    try:
        r = size / 2.0 - size * 0.09
        paint_jelly(p, size / 2.0, size / 2.0, r, glow=0.0)
    finally:
        p.end()
    return pm
