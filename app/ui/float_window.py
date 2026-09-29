"""悬浮窗主体：置顶小窗 + 可收起气泡，承载文字解题与截图解题两种入口。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeyEvent, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app import config as cfgmod
from app import store as storemod
from app.config import ANSWER_STYLE_LABELS, ANSWER_STYLES, ConfigManager
from app.engine.base import SolveRequest
from app.logger import get
from app.store import Store
from app.ui import formatting, theme
from app.ui.worker import SolveWorker

log = get("float")

COLLAPSED_SIZE = QSize(56, 56)
EXPANDED_SIZE = QSize(400, 540)


class DragHandle(QWidget):
    """可拖拽区域：按住空白处移动窗口；单击（未拖动）时发 clicked。"""

    clicked = Signal()
    moved = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._offset: QPoint | None = None
        self._moved = False
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        window = self.window()
        self._offset = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
        self._moved = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._offset is None or not (event.buttons() & Qt.LeftButton):
            return
        target = event.globalPosition().toPoint() - self._offset
        if (target - self.window().pos()).manhattanLength() > 3:
            self._moved = True
        self.window().move(target)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._offset is None:
            return
        was_moved = self._moved
        self._offset = None
        self._moved = False
        if was_moved:
            self.moved.emit()
        else:
            self.clicked.emit()
        event.accept()


class FloatWindow(QWidget):
    capture_requested = Signal()
    settings_requested = Signal()
    history_requested = Signal()
    quit_requested = Signal()

    def __init__(self, config: ConfigManager, store: Store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self._worker: SolveWorker | None = None
        self._current_rid: int | None = None
        self._last_request: SolveRequest | None = None
        self._accumulated = ""
        self._dirty = False
        self._collapsed = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowMinimizeButtonHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(cfgmod.APP_NAME)

        self._build_ui()
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(60)
        self._flush_timer.timeout.connect(self._flush_answer)
        self._flush_timer.start()

        self.apply_config(restore_position=True)

    # ============================================================ 构建界面

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        outer.addWidget(self.card)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 8, 12, 12)
        card_layout.setSpacing(8)

        card_layout.addWidget(self._build_header())
        card_layout.addWidget(self._build_tabs())
        card_layout.addWidget(self._build_pages())
        card_layout.addWidget(self._build_answer_area(), 1)
        card_layout.addWidget(self._build_footer())

        # 收起后的气泡
        self.bubble = DragHandle(self)
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_label = QLabel(self.bubble)
        bubble_label.setPixmap(theme.bubble_icon(56))
        bubble_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        bubble_layout.addWidget(bubble_label, 0, Qt.AlignCenter)
        self.bubble.clicked.connect(lambda: self.set_collapsed(False))
        self.bubble.moved.connect(self._remember_position)
        self.bubble.setToolTip("点击展开 鸡哥解题")
        self.bubble.setGeometry(0, 0, COLLAPSED_SIZE.width(), COLLAPSED_SIZE.height())
        self.bubble.hide()

    def _build_header(self) -> QWidget:
        self.header = DragHandle(self.card)
        self.header.setFixedHeight(30)
        self.header.moved.connect(self._remember_position)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(4)

        dot = QLabel("●", self.header)
        dot.setStyleSheet(f"color:{theme.SUCCESS}; font-size:11px;")
        dot.setToolTip("运行中")
        row.addWidget(dot)

        title = QLabel(cfgmod.APP_NAME, self.header)
        title.setObjectName("titleLabel")
        row.addWidget(title)
        row.addStretch(1)

        self.pin_btn = self._icon_button("置顶", "窗口保持在其他程序上层", checkable=True)
        self.pin_btn.toggled.connect(self._on_pin_toggled)
        row.addWidget(self.pin_btn)

        history_btn = self._icon_button("历史", "查看历史解题记录")
        history_btn.clicked.connect(self.history_requested.emit)
        row.addWidget(history_btn)

        settings_btn = self._icon_button("设置", "引擎与热键设置")
        settings_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(settings_btn)

        collapse_btn = self._icon_button("—", "收起为悬浮球")
        collapse_btn.clicked.connect(lambda: self.set_collapsed(True))
        row.addWidget(collapse_btn)

        quit_btn = self._icon_button("×", "退出程序")
        quit_btn.clicked.connect(self.quit_requested.emit)
        row.addWidget(quit_btn)
        return self.header

    def _icon_button(self, text: str, tip: str, checkable: bool = False) -> QPushButton:
        btn = QPushButton(text, self.card)
        btn.setObjectName("iconBtn")
        btn.setCheckable(checkable)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(24)
        return btn

    def _build_tabs(self) -> QWidget:
        container = QWidget(self.card)
        outer = QHBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        wrap = QFrame(container)
        wrap.setObjectName("segWrap")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for idx, text in enumerate(("文字解题", "截图解题")):
            btn = QPushButton(text, wrap)
            btn.setObjectName("seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            row.addWidget(btn, 1)
            self.tab_group.addButton(btn, idx)
        outer.addWidget(wrap, 1)

        # 解答风格：放在最显眼的位置，因为它同时决定「答案详细程度」和「出答案的速度」
        self.style_box = QComboBox(container)
        self.style_box.setObjectName("styleBox")
        for key in ANSWER_STYLES:
            self.style_box.addItem(ANSWER_STYLE_LABELS[key], key)
        # 不要写死宽度：字号是可配置的，写死就会在中文字体下把「详细题解」截断
        # （渲染验证时实测过）。让它按内容自适应，再兜一个最小值。
        self.style_box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.style_box.setMinimumWidth(100)
        self.style_box.setToolTip(
            "只看答案：只输出最终结果，几十个字，最快\n"
            "详细题解：给出知识点与完整步骤，输出长所以更慢"
        )
        self.style_box.currentIndexChanged.connect(self._on_style_changed)
        outer.addWidget(self.style_box, 0)
        return container

    def _on_style_changed(self) -> None:
        key = self.style_box.currentData()
        if key not in ANSWER_STYLES:
            return
        engine = self.config.config.engine
        if engine.answer_style == key:
            return
        engine.answer_style = key
        self.config.save()
        label = ANSWER_STYLE_LABELS[key]
        if engine.has_custom_prompt:
            # 自定义提示词的优先级高于风格，这里必须说清楚，否则用户会以为是 bug
            self._set_status(
                f"已选「{label}」，但你在设置里自定义了系统提示词，实际仍按自定义提示词作答。",
                theme.WARNING,
            )
        else:
            self._set_status(f"解答风格已切换为「{label}」。", theme.TEXT_MUTED)

    def _build_pages(self) -> QWidget:
        self.stack = QStackedWidget(self.card)
        self.stack.setFixedHeight(148)
        self.stack.addWidget(self._build_text_page())
        self.stack.addWidget(self._build_shot_page())
        self.tab_group.idClicked.connect(self._on_tab_changed)
        return self.stack

    def _build_text_page(self) -> QWidget:
        page = QWidget(self.card)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.question_edit = QPlainTextEdit(page)
        self.question_edit.setPlaceholderText("把题目粘贴或输入到这里…\nCtrl+Enter 直接发送")
        self.question_edit.installEventFilter(self)
        layout.addWidget(self.question_edit, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.clear_btn = QPushButton("清空", page)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(lambda: self.question_edit.clear())
        row.addWidget(self.clear_btn)

        self.send_btn = QPushButton("解答", page)
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFixedHeight(30)
        self.send_btn.clicked.connect(self.submit_text)
        row.addWidget(self.send_btn, 1)
        layout.addLayout(row)
        return page

    def _build_shot_page(self) -> QWidget:
        page = QWidget(self.card)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.shot_btn = QPushButton("截屏解题", page)
        self.shot_btn.setObjectName("primary")
        self.shot_btn.setCursor(Qt.PointingHandCursor)
        self.shot_btn.setMinimumHeight(72)
        self.shot_btn.clicked.connect(self.capture_requested.emit)
        layout.addWidget(self.shot_btn, 1)

        self.shot_hint = QLabel(page)
        self.shot_hint.setObjectName("hintLabel")
        self.shot_hint.setWordWrap(True)
        self.shot_hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.shot_hint)

        preview_row = QHBoxLayout()
        preview_row.setSpacing(8)
        self.preview_label = QLabel(page)
        self.preview_label.setFixedSize(72, 44)
        self.preview_label.setStyleSheet(
            f"border:1px solid {theme.BORDER}; border-radius:6px; background:{theme.SURFACE};"
        )
        self.preview_label.setAlignment(Qt.AlignCenter)
        preview_row.addWidget(self.preview_label)
        self.preview_text = QLabel("最近一次截取的题目会显示在这里", page)
        self.preview_text.setObjectName("hintLabel")
        self.preview_text.setWordWrap(True)
        preview_row.addWidget(self.preview_text, 1)
        layout.addLayout(preview_row)
        return page

    def _build_answer_area(self) -> QWidget:
        wrap = QWidget(self.card)
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(6)
        label = QLabel("解答", wrap)
        label.setObjectName("titleLabel")
        row.addWidget(label)
        self.answer_meta = QLabel("", wrap)
        self.answer_meta.setObjectName("subLabel")
        row.addWidget(self.answer_meta)
        row.addStretch(1)

        self.copy_btn = QPushButton("复制", wrap)
        self.copy_btn.setObjectName("iconBtn")
        self.copy_btn.setToolTip("复制解答内容")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._copy_answer)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)

        self.regen_btn = QPushButton("重解", wrap)
        self.regen_btn.setObjectName("iconBtn")
        self.regen_btn.setToolTip("用同样的题目重新解答一次")
        self.regen_btn.setCursor(Qt.PointingHandCursor)
        self.regen_btn.clicked.connect(self._regenerate)
        self.regen_btn.setEnabled(False)
        row.addWidget(self.regen_btn)
        layout.addLayout(row)

        self.answer_view = QTextBrowser(wrap)
        self.answer_view.setObjectName("answer")
        self.answer_view.setOpenExternalLinks(True)
        self.answer_view.setPlaceholderText("")
        layout.addWidget(self.answer_view, 1)
        return wrap

    def _build_footer(self) -> QWidget:
        wrap = QWidget(self.card)
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.progress = QProgressBar(wrap)
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)

        self.status = QLabel("", wrap)
        self.status.setObjectName("hintLabel")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        return wrap

    # ============================================================ 配置应用

    def apply_config(self, restore_position: bool = False) -> None:
        ui = self.config.config.ui
        self.setWindowOpacity(max(0.35, min(1.0, float(ui.opacity))))
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(bool(ui.always_on_top))
        self.pin_btn.blockSignals(False)
        self._apply_always_on_top(bool(ui.always_on_top))

        idx = 1 if int(ui.last_tab) == 1 else 0
        button = self.tab_group.button(idx)
        if button is not None:
            button.setChecked(True)
        self.stack.setCurrentIndex(idx)

        self.sync_style_box()

        self.update_hotkey_hint()

        if not self._collapsed:
            self.setFixedSize(EXPANDED_SIZE)
        if restore_position:
            if ui.pos_x < 0 or ui.pos_y < 0:
                self._move_to_default_corner()
            else:
                self._move_clamped(QPoint(int(ui.pos_x), int(ui.pos_y)))
        else:
            self._move_clamped(self.pos())

    def sync_style_box(self) -> None:
        """把配置里的风格同步到下拉框（设置页改过之后要跟上）。"""
        key = self.config.config.engine.style
        idx = self.style_box.findData(key)
        if idx < 0:
            return
        self.style_box.blockSignals(True)
        self.style_box.setCurrentIndex(idx)
        self.style_box.blockSignals(False)

    def update_hotkey_hint(self) -> None:
        from app.hotkey import display_text

        combo = display_text(self.config.config.hotkey.capture)
        mode = "框选区域" if self.config.config.capture.mode == "region" else "整屏直出"
        self.shot_btn.setText(f"截屏解题  {combo}")
        self.shot_hint.setText(f"按下 {combo} 后{mode}，松开鼠标自动解答。\n也可以直接点上面的按钮。")

    def _apply_always_on_top(self, on: bool) -> None:
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        if flags != self.windowFlags():
            visible = self.isVisible()
            self.setWindowFlags(flags)
            if visible:
                self.show()

    # ============================================================ 位置与收起

    def _screen_geometry(self):
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else None

    def _move_to_default_corner(self) -> None:
        geo = QGuiApplication.primaryScreen()
        if geo is None:
            return
        avail = geo.availableGeometry()
        self.move(avail.right() - self.width() - 24, avail.top() + 80)

    def _move_clamped(self, pos: QPoint) -> None:
        self.move(pos)
        geo = self._screen_geometry()
        if geo is None:
            return
        x = min(max(pos.x(), geo.left() - 20), geo.right() - 40)
        y = min(max(pos.y(), geo.top()), geo.bottom() - 40)
        self.move(x, y)

    def set_collapsed(self, flag: bool) -> None:
        self._collapsed = bool(flag)
        self.card.setVisible(not flag)
        self.bubble.setVisible(flag)
        # 收起时以当前窗口中心为锚点，避免气泡跑到屏幕外
        center = self.frameGeometry().center()
        if flag:
            self.setFixedSize(COLLAPSED_SIZE)
        else:
            self.setFixedSize(EXPANDED_SIZE)
        self.move(center - QPoint(self.width() // 2, self.height() // 2))
        self._move_clamped(self.pos())
        ui = self.config.config.ui
        ui.collapsed = flag
        self.config.save()
        self._remember_position()

    def _remember_position(self) -> None:
        ui = self.config.config.ui
        ui.pos_x = int(self.x())
        ui.pos_y = int(self.y())
        ui.collapsed = self._collapsed
        self.config.save()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if hasattr(self, "_pos_save_timer"):
            self._pos_save_timer.start(600)
        else:
            self._pos_save_timer = QTimer(self)
            self._pos_save_timer.setSingleShot(True)
            self._pos_save_timer.timeout.connect(self._remember_position)
            self._pos_save_timer.start(600)

    # ============================================================ 事件

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.question_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                self.submit_text()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and not self._collapsed:
            self.set_collapsed(True)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._remember_position()
        self._stop_worker(wait_ms=2000)
        super().closeEvent(event)

    # ============================================================ 解题流程

    def submit_text(self) -> None:
        text = self.question_edit.toPlainText().strip()
        if not text:
            self._set_status("请先输入题目内容。", theme.WARNING)
            return
        self.submit(SolveRequest(question=text), source=storemod.SOURCE_TEXT, question_text=text)

    def submit_image(self, image: QImage, image_png: bytes, note: str = "") -> None:
        """截图解题入口：原图存盘，压缩图送模型。"""
        from app import capture as cap

        try:
            b64, mime = cap.encode_for_model(
                image,
                max_width=int(self.config.config.capture.shot_max_width),
                quality=int(self.config.config.capture.jpeg_quality),
            )
        except cap.CaptureError as e:
            self._set_status(str(e), theme.DANGER)
            return

        question_text = note or "截图解题"
        image_rel = self.store.save_shot(image_png, "png")
        self._show_preview(image, image_rel)
        self.submit(
            SolveRequest(question=note, image_b64=b64, image_mime=mime),
            source=storemod.SOURCE_IMAGE,
            question_text=question_text,
            image_rel=image_rel,
        )

    def submit(self, req: SolveRequest, *, source: str, question_text: str,
               image_rel: str | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        engine = self.config.config.engine
        self._current_rid = self.store.add_record(
            source=source,
            question=question_text,
            image_path=image_rel,
            provider=engine.provider,
            model=engine.model,
            status="pending",
            style=engine.style,
        )
        self._last_request = req
        self._accumulated = ""
        self._dirty = False

        self.answer_view.setPlainText("")
        self.answer_meta.setText(f"{engine.provider} · {engine.model}{self._style_suffix()}")
        self._set_running(True)
        self._set_status("正在解答，请稍候…", theme.TEXT_MUTED)
        self.regen_btn.setEnabled(False)
        self.copy_btn.setEnabled(False)

        self._worker = SolveWorker(engine, req, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.start()

    def _on_chunk(self, piece: str) -> None:
        self._accumulated += piece
        self._dirty = True

    def _flush_answer(self) -> None:
        """定时刷新，避免每个分片都重排一次文档导致卡顿。"""
        if not self._dirty:
            return
        self._dirty = False
        self.answer_view.setPlainText(formatting.to_plain(self._accumulated))
        bar = self.answer_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_done(self, answer: str, elapsed_ms: int) -> None:
        self._accumulated = answer
        self._dirty = False
        self._set_running(False)
        self.answer_view.document().setMarkdown(formatting.to_markdown(answer))
        bar = self.answer_view.verticalScrollBar()
        bar.setValue(bar.maximum())

        engine = self.config.config.engine
        if self._current_rid:
            self.store.update_record(
                self._current_rid,
                answer=answer,
                status=storemod.STATUS_OK,
                error="",
                elapsed_ms=elapsed_ms,
                model=engine.model,
                provider=engine.provider,
            )
        self.answer_meta.setText(
            f"{engine.provider} · {engine.model}{self._style_suffix()} · {elapsed_ms / 1000:.1f}s"
        )
        self._set_status("解答完成。", theme.SUCCESS)
        self.copy_btn.setEnabled(bool(answer))
        self.regen_btn.setEnabled(True)
        self._auto_trim()

    def _style_suffix(self) -> str:
        """只在「只看答案」时标注，避免详细模式下的文案噪音。"""
        engine = self.config.config.engine
        if engine.style == "brief":
            return " · 只看答案"
        return ""

    def _on_failed(self, message: str) -> None:
        self._set_running(False)
        self._flush_answer()
        if self._accumulated:
            self.answer_view.document().setMarkdown(formatting.to_markdown(self._accumulated))
        self.answer_view.append(f"\n[出错] {message}")
        if self._current_rid:
            self.store.update_record(
                self._current_rid,
                answer=self._accumulated,
                status=storemod.STATUS_ERROR,
                error=message,
            )
        self._set_status(message, theme.DANGER)
        self.regen_btn.setEnabled(True)
        self.copy_btn.setEnabled(bool(self._accumulated))
        self._auto_trim()

    def _on_cancelled(self) -> None:
        self._set_running(False)
        self._flush_answer()
        self._set_status("已取消。", theme.TEXT_MUTED)
        self.regen_btn.setEnabled(True)

    def _regenerate(self) -> None:
        if self._last_request is None:
            return
        req = self._last_request
        source = storemod.SOURCE_IMAGE if req.has_image else storemod.SOURCE_TEXT
        # 复用已有截图文件，不重复落盘
        image_rel = None
        if self._current_rid:
            rec = self.store.get_record(self._current_rid)
            if rec:
                image_rel = rec.get("image_path")
        self.submit(req, source=source, question_text=(req.question or "截图解题"), image_rel=image_rel)

    def _copy_answer(self) -> None:
        from PySide6.QtWidgets import QApplication

        text = self._accumulated or self.answer_view.toPlainText()
        QApplication.clipboard().setText(text)
        self._set_status("已复制到剪贴板。", theme.SUCCESS)

    # ============================================================ 小工具

    def stop_current(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()

    def _stop_worker(self, wait_ms: int = 3000) -> None:
        if self._worker is None:
            return
        if self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(wait_ms)
        self._worker = None

    def _set_running(self, running: bool) -> None:
        self.progress.setVisible(running)
        self.shot_btn.setEnabled(not running)
        self.send_btn.setEnabled(not running)
        if running:
            self.send_btn.setText("解答中…")
        else:
            self.send_btn.setText("解答")

    def _set_status(self, text: str, color: str = theme.TEXT_MUTED) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color:{color}; font-size:11px;")

    def set_status(self, text: str, color: str = theme.TEXT_MUTED) -> None:
        """对外公开的状态提示入口，供主控与托盘调用。"""
        self._set_status(text, color)

    def _show_preview(self, image: QImage, image_rel: str) -> None:
        # QImage.scaled() 返回 QImage，QLabel 需要 QPixmap，显式转换
        pix = QPixmap.fromImage(
            image.scaled(
                self.preview_label.width(), self.preview_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
        )
        self.preview_label.setPixmap(pix)
        stamp = datetime.now().strftime("%H:%M:%S")
        abs_path = self.store.abs_shot_path(image_rel)
        nbytes = abs_path.stat().st_size if abs_path and abs_path.exists() else 0
        size_text = f"{nbytes / 1024:.1f} KB" if nbytes >= 1024 else f"{nbytes} B"
        self.preview_text.setText(
            f"{stamp} 截取 {image.width()}×{image.height()}，{size_text}\n已存入 data/shots/，可在历史里回看"
        )

    def _auto_trim(self) -> None:
        storage = self.config.config.storage
        if not storage.auto_trim:
            return
        limit = int(storage.history_limit)
        if limit > 0 and self.store.count_records() > limit:
            removed = self.store.trim_history(limit)
            if removed:
                log.info("历史超出上限，自动清理 %d 条", removed)

    def _on_pin_toggled(self, checked: bool) -> None:
        self._apply_always_on_top(checked)
        self.config.config.ui.always_on_top = checked
        self.config.save()

    def _on_tab_changed(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.config.config.ui.last_tab = idx
        self.config.save()
