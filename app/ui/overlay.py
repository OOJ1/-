"""截屏框选遮罩。

一次截图流程：
1. 主控调用 capture.grab_virtual_desktop() 拿到「冻结」的整屏图；
2. 本遮罩铺满整个虚拟桌面显示该图并压暗，用户拖拽框选；
3. 松开鼠标 → 按 scale 换算成物理像素裁剪 → 发出 captured(QImage)；
   Esc → cancelled()；回车/双击 → 直接全屏。

先冻结再框选，是为了让用户框选时画面静止，不会因动画/视频导致截到别的内容。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app import capture as cap
from app.logger import get

log = get("overlay")

DIM_ALPHA = 120
ACCENT = QColor(59, 110, 246)
HINT_BG = QColor(26, 29, 33, 210)
MIN_SIZE = 8  # 逻辑像素，小于此视为误点


class CaptureOverlay(QWidget):
    captured = Signal(QImage)
    cancelled = Signal()

    def __init__(self, image: QImage, scale: float, union: QRect, mode: str = "region") -> None:
        super().__init__(None)
        self._image = image
        self._scale = scale or 1.0
        self._union = QRect(union)
        self._origin = QPoint()
        self._current = QPoint()
        self._dragging = False
        self._done = False
        self._mode = mode

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(self._union)
        self.setWindowTitle("截屏解题")

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        # Windows 下 Tool 窗口未必立刻拿到键盘焦点，显式抓一次更稳
        self.grabKeyboard()
        if self._mode == "fullscreen":
            self._finish_full()

    def _release(self) -> None:
        try:
            self.releaseKeyboard()
        except RuntimeError:
            pass

    def _selection(self) -> QRect:
        return QRect(self._origin, self._current).normalized()

    # ------------------------------------------------------------ 事件

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        self._origin = event.position().toPoint()
        self._current = self._origin
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        rect = self._selection()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            # 视为误点，不结束，让用户重新框选
            self.update()
            return
        self._emit(rect)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._finish_full()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key_Escape:
            self._finish_cancel()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            rect = self._selection()
            if rect.width() >= MIN_SIZE and rect.height() >= MIN_SIZE:
                self._emit(rect)
            else:
                self._finish_full()
        elif key == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self._finish_full()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._release()
        if not self._done:
            self._done = True
            self.cancelled.emit()
        super().closeEvent(event)

    # ------------------------------------------------------------ 完成

    def accept_full(self) -> None:
        """外部再次按热键时切到全屏直出。"""
        self._finish_full()

    def _finish_full(self) -> None:
        self._emit(QRect(0, 0, self.width(), self.height()))

    def _finish_cancel(self) -> None:
        if self._done:
            return
        self._done = True
        self._release()
        self.cancelled.emit()
        self.close()

    def _emit(self, rect: QRect) -> None:
        if self._done:
            return
        self._done = True
        physical = QRect(
            round(rect.x() * self._scale),
            round(rect.y() * self._scale),
            max(1, round(rect.width() * self._scale)),
            max(1, round(rect.height() * self._scale)),
        )
        try:
            cropped = cap.crop_physical(self._image, physical)
        except cap.CaptureError as e:
            log.warning("裁剪失败：%s", e)
            self._finish_cancel()
            return
        self._release()
        self.captured.emit(cropped)
        self.close()

    # ------------------------------------------------------------ 绘制

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            p.drawImage(self.rect(), self._image)

            sel = self._selection()
            has_sel = self._dragging or (sel.width() >= MIN_SIZE and sel.height() >= MIN_SIZE)

            if has_sel:
                # 选中区原亮度，其余压暗
                p.setClipRect(sel)
                p.drawImage(self.rect(), self._image)
                p.setClipping(False)
                # 压暗四块外围
                dim = QColor(0, 0, 0, DIM_ALPHA)
                for r in (
                    QRect(0, 0, self.width(), sel.top()),
                    QRect(0, sel.bottom() + 1, self.width(), self.height() - sel.bottom() - 1),
                    QRect(0, sel.top(), sel.left(), sel.height()),
                    QRect(sel.right() + 1, sel.top(), self.width() - sel.right() - 1, sel.height()),
                ):
                    if r.width() > 0 and r.height() > 0:
                        p.fillRect(r, dim)
                p.setPen(QPen(ACCENT, 2))
                p.drawRect(sel.adjusted(0, 0, -1, -1))
                self._draw_size_badge(p, sel)
            else:
                p.fillRect(self.rect(), QColor(0, 0, 0, DIM_ALPHA))
                self._draw_crosshair(p)

            self._draw_hint(p)
        finally:
            p.end()

    def _draw_crosshair(self, p: QPainter) -> None:
        pos = self._current
        pen = QPen(QColor(255, 255, 255, 90), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(0, pos.y(), self.width(), pos.y())
        p.drawLine(pos.x(), 0, pos.x(), self.height())
        # 坐标提示
        p.setPen(QColor(255, 255, 255, 220))
        p.setFont(QFont(self.font().family(), 9))
        p.drawText(pos + QPoint(12, -10), f"{int(pos.x() * self._scale)}, {int(pos.y() * self._scale)}")

    def _draw_size_badge(self, p: QPainter, sel: QRect) -> None:
        text = f"{int(sel.width() * self._scale)} × {int(sel.height() * self._scale)}"
        p.setFont(QFont(self.font().family(), 9, QFont.Bold))
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 14
        h = metrics.height() + 6
        x = min(max(0, sel.left()), self.width() - w)
        y = sel.top() - h - 6
        if y < 0:
            y = min(sel.bottom() + 6, self.height() - h)
        p.setPen(Qt.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(x, y, w, h, 4, 4)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)

    def _draw_hint(self, p: QPainter) -> None:
        text = "拖拽框选题目区域 · 回车全屏 · Esc 取消"
        p.setFont(QFont(self.font().family(), 10))
        metrics = p.fontMetrics()
        w = metrics.horizontalAdvance(text) + 28
        h = metrics.height() + 14
        # 提示放在鼠标所在屏幕顶部居中，避免在多屏下跑到别的屏幕
        screen = QGuiApplication.screenAt(self._current) or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            cx = geo.center().x() - self._union.left()
        else:
            cx = self.width() // 2
        x = min(max(8, cx - w // 2), max(8, self.width() - w - 8))
        y = 24
        p.setPen(Qt.NoPen)
        p.setBrush(HINT_BG)
        p.drawRoundedRect(x, y, w, h, 8, 8)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)
