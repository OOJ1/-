"""收起后的悬浮球：果冻质感 + 弹性动画。

设计要点：
- 质感（果冻的「透光厚感」）由 theme.paint_jelly 画的深色玻璃正圆负责，
  球心那只是 theme.paint_pixel_chick 画的像素小鸡；
- 弹性（挤压/回弹/呼吸）由 QPropertyAnimation 驱动本控件的几个浮点属性，
  在 paintEvent 里换算成 painter 的非等比缩放，二者解耦。

四条动画互不抢占同一属性：
    jellyScale  — 悬停放大 / 右键弹起 / 收起入场
    jellyGlow   — 悬停发光强度
    jellySquash — 悬停「挤压弹起」、左键按住压扁、右键抖动
    jellyPulse  — 静息时的轻微呼吸

交互约定：
    左键单击 → 展开     左键按住拖 → 移动位置
    悬停     → 挤压后弹起（一次完整的 q 弹）
    右键单击 → 抖一下
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    Property,
    QPropertyAnimation,
    Qt,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget

from app.ui import theme

PADDING = 8.0        # 球体外留给光晕与放大的余量
IDLE_SCALE = 1.0
HOVER_SCALE = 1.12
PULSE_AMPLITUDE = 1.018
# 横向鼓出不能太大：挤压峰值时 draw 出来的宽度是
# (HOVER_SCALE * (1 + SQUASH_X * 1.15) + 呼吸) * 球半径，
# 超过 widget 半宽就会被裁成平边，果冻立刻变成方块。
SQUASH_X = 0.08
SQUASH_Y = 0.18      # 压下时纵向压扁

# 悬停「挤压弹起」：先压扁 → 弹起时纵向过冲拉长（负值）→ 落回正圆。
# 单纯放大看不出果冻感，中间那下过冲才是。
# 时间点刻意往后放（0.16 才压到底、0.52 才过冲）：动作太快的话鼠标一扫
# 过去根本看不见，实测 300ms 内跑完就是这么废掉的。
HOVER_POP_KEYS = ((0.00, 0.00), (0.16, 1.15), (0.52, -0.38), (1.00, 0.00))
HOVER_POP_MS = 780
# 右键「抖一下」：振幅逐次衰减的振荡，抖几下才停 —— 衰减太快会像抖了一下就卡住
WOBBLE_KEYS = ((0.00, 0.00), (0.09, 1.15), (0.28, -0.55), (0.47, 0.32),
               (0.64, -0.18), (0.81, 0.09), (1.00, 0.00))
WOBBLE_MS = 1250


def _elastic(amplitude: float = 1.0, period: float = 0.34) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.OutElastic)
    curve.setAmplitude(amplitude)
    curve.setPeriod(period)
    return curve


class JellyBubble(QWidget):
    """果冻悬浮球。只管外观与动效，不负责拖拽。

    拖拽由 float_window 里的组合类拼进来（那边有现成的 DragHandle），
    这样本模块不依赖任何项目内其它模块，也不用把 DragHandle 挪位置。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scale = IDLE_SCALE
        self._glow = 0.0
        self._squash = 0.0
        self._pulse = 1.0
        self._hovered = False

        self._scale_anim = QPropertyAnimation(self, b"jellyScale", self)
        self._glow_anim = QPropertyAnimation(self, b"jellyGlow", self)
        self._squash_anim = QPropertyAnimation(self, b"jellySquash", self)
        self._pulse_anim = QPropertyAnimation(self, b"jellyPulse", self)
        self._pulse_anim.setStartValue(1.0)
        self._pulse_anim.setKeyValueAt(0.5, PULSE_AMPLITUDE)
        self._pulse_anim.setEndValue(1.0)
        self._pulse_anim.setDuration(1900)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)
        self._pulse_anim.setLoopCount(-1)

    # ------------------------------------------------------------ 动画属性

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, value: float) -> None:
        self._scale = float(value)
        self.update()

    jellyScale = Property(float, _get_scale, _set_scale)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = float(value)
        self.update()

    jellyGlow = Property(float, _get_glow, _set_glow)

    def _get_squash(self) -> float:
        return self._squash

    def _set_squash(self, value: float) -> None:
        self._squash = float(value)
        self.update()

    jellySquash = Property(float, _get_squash, _set_squash)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = float(value)
        self.update()

    jellyPulse = Property(float, _get_pulse, _set_pulse)

    # ------------------------------------------------------------ 动画编排

    @staticmethod
    def _retarget(anim: QPropertyAnimation, current: float, end: float,
                  duration: int, curve: QEasingCurve) -> None:
        """重设动画的关键帧。

        必须用 setKeyValues 整体替换，而不是只改 start/end：play_pop 留下的
        中间关键帧若不清掉，后续 hover 动画会莫名其妙再弹一下。
        """
        anim.stop()
        anim.setEasingCurve(curve)
        anim.setDuration(duration)
        anim.setKeyValues([(0.0, current), (1.0, end)])
        anim.start()

    @staticmethod
    def _set_keys(anim: QPropertyAnimation, keys, duration: int, curve: QEasingCurve,
                  head: float | None = None) -> None:
        """按一串 (归一化时间, 值) 关键帧重设动画。

        head 不为 None 时替换第一个关键帧的值，让动作从「此刻的实际值」接上，
        不然中途被打断的动画会突然跳回起点。
        """
        pairs = [(float(t), float(v)) for t, v in keys]
        if head is not None:
            pairs[0] = (pairs[0][0], float(head))
        anim.stop()
        anim.setEasingCurve(curve)
        anim.setDuration(duration)
        anim.setKeyValues(pairs)
        anim.start()

    def play_pop(self) -> None:
        """收起瞬间的入场弹性：从偏小弹到略过冲再落回。"""
        self._scale_anim.stop()
        self._scale_anim.setEasingCurve(QEasingCurve.OutQuad)
        self._scale_anim.setDuration(640)
        self._scale_anim.setKeyValues([
            (0.0, 0.68),
            (0.45, 1.055),
            (1.0, HOVER_SCALE if self._hovered else IDLE_SCALE),
        ])
        self._scale_anim.start()

    def stop_animations(self) -> None:
        for anim in (self._scale_anim, self._glow_anim, self._squash_anim, self._pulse_anim):
            anim.stop()

    # ------------------------------------------------------------ 交互

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        # 悬停 = 挤压后弹起（不是单纯放大）：一次动作就能看出它是软的
        self._set_keys(self._squash_anim, HOVER_POP_KEYS, HOVER_POP_MS,
                       QEasingCurve.OutQuad, head=self._squash)
        self._retarget(self._scale_anim, self._scale, HOVER_SCALE, 460, QEasingCurve.OutBack)
        self._retarget(self._glow_anim, self._glow, 1.0, 300, QEasingCurve.OutCubic)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        # 移开就直接收，不再弹一次：否则鼠标来回蹭两下会一直抖，很吵
        self._retarget(self._squash_anim, self._squash, 0.0, 240, QEasingCurve.OutCubic)
        self._retarget(self._scale_anim, self._scale, IDLE_SCALE, 320, QEasingCurve.OutBack)
        self._retarget(self._glow_anim, self._glow, 0.0, 420, QEasingCurve.OutCubic)
        super().leaveEvent(event)

    def play_wobble(self) -> None:
        """右键：抖一下。衰减振荡 + 弹起后落回，抖完自己停。"""
        self._set_keys(self._squash_anim, WOBBLE_KEYS, WOBBLE_MS,
                       QEasingCurve.OutQuad, head=self._squash)
        rest = HOVER_SCALE if self._hovered else IDLE_SCALE
        self._set_keys(self._scale_anim,
                       ((0.0, self._scale), (0.14, HOVER_SCALE), (1.0, rest)),
                       WOBBLE_MS, QEasingCurve.OutCubic)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.play_wobble()
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._retarget(self._squash_anim, self._squash, 1.0, 110, QEasingCurve.OutQuad)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        # 一旦判定成拖动，就把球捏扁一点：手感上像被抓住了，
        # 也顺带告诉用户「现在是在拖，松手不会展开」。
        if getattr(self, "_moved", False) and self._squash < 0.3:
            self._retarget(self._squash_anim, self._squash, 0.35, 150, QEasingCurve.OutQuad)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._retarget(self._squash_anim, self._squash, 0.0, 820, _elastic())
        super().mouseReleaseEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._pulse_anim.state() != QAbstractAnimation.Running:
            self._pulse_anim.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.stop_animations()
        super().hideEvent(event)

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        half = min(self.width(), self.height()) / 2.0
        r = half - PADDING
        if r <= 1.0:
            return
        sx = self._scale * self._pulse * (1.0 + SQUASH_X * self._squash)
        sy = self._scale * self._pulse * (1.0 - SQUASH_Y * self._squash)
        p = QPainter(self)
        try:
            # 外发光只轻微跟随、并硬性限制在窗口内：让它跟着球一起放大就会顶到
            # 边界被裁成直边，看着像「球旁边还有一块方的东西也在放大」。
            theme.paint_jelly_halo(
                p, half, half, r,
                glow=self._glow,
                scale=1.0 + 0.45 * (max(sx, sy) - 1.0),
                limit=half - 0.5,
            )
            # 只有球体做非等比形变（挤压 / 拉伸）
            p.save()
            p.translate(half, half)
            p.scale(sx, sy)
            theme.paint_jelly_body(p, 0.0, 0.0, r)
            p.restore()
        finally:
            p.end()
