"""鸡哥解题 —— 应用入口。

职责：单实例保护、装配配置/存储/热键/界面、编排「热键 → 截图 → 自动解答」流程。
直接运行：python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QLockFile, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from app import capture as cap  # noqa: E402
from app import config as cfgmod  # noqa: E402
from app import logger as logmod  # noqa: E402
from app.config import ConfigManager  # noqa: E402
from app.engine.base import SolveRequest  # noqa: E402
from app.engine.service import warm_up_async  # noqa: E402
from app.hotkey import HotkeyManager, display_text  # noqa: E402
from app.store import Store  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.float_window import FloatWindow  # noqa: E402
from app.ui.history_dialog import HistoryDialog  # noqa: E402
from app.ui.overlay import CaptureOverlay  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402

log = logmod.get("main")

CAPTURE_HIDE_DELAY_MS = 160


class AppController:
    """把各模块粘起来，避免界面类之间互相引用。"""

    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.config = ConfigManager()
        self.store = Store(drop_orphan=bool(self.config.config.storage.drop_orphan_shots))
        self.window = FloatWindow(self.config, self.store)
        self.hotkeys = HotkeyManager(self.app)
        self.tray = QSystemTrayIcon(theme.make_app_icon(), self.app)
        self._overlay: CaptureOverlay | None = None
        self._history: HistoryDialog | None = None
        self._window_was_visible = False
        self._icon = theme.make_app_icon()
        self._warmed_model = ""

    # ============================================================ 启动

    def start(self) -> None:
        self._setup_tray()
        self._wire()

        dropped = self.store.reconcile() if self.config.config.storage.drop_orphan_shots else None
        if dropped and (dropped["orphan_deleted"] or dropped["dangling_cleared"]):
            log.info("启动对账：%s", dropped)
        logmod.cleanup_logs(7)

        if self.config.config.ui.collapsed:
            self.window.set_collapsed(True)
        self.window.show()

        self._register_hotkey(first_run=True)
        self._prewarm_model()

    def _prewarm_model(self) -> None:
        """后台把本机模型读进显存。

        冷启动要重新加载权重，实测 9B 模型约 74 秒、热态只要 5-12 秒。
        启动时先"点"一下（不发 prompt、不产生 token），用户配好设置后第一次提问就不用干等。
        失败只记日志 —— 预热纯属优化，绝不能影响启动。
        """
        try:
            warm_up_async(self.config.config.engine)
            self._warmed_model = self.config.config.engine.model or ""
        except Exception:  # noqa: BLE001
            log.exception("模型预热启动失败（忽略）")

    def _setup_tray(self) -> None:
        menu = QMenu()
        actions = [
            ("显示 / 收起悬浮窗", self._toggle_window),
            ("立即截图解题", self.start_capture),
            (None, None),
            ("历史记录", self.open_history),
            ("设置", self.open_settings),
            ("打开数据目录", self._open_data_dir),
            (None, None),
            ("退出", self.quit),
        ]
        for text, handler in actions:
            if text is None:
                menu.addSeparator()
                continue
            act = QAction(text, menu)
            act.triggered.connect(handler)
            menu.addAction(act)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(f"{cfgmod.APP_NAME} —— 双击显示悬浮窗")
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _wire(self) -> None:
        self.window.capture_requested.connect(self.start_capture)
        self.window.settings_requested.connect(self.open_settings)
        self.window.history_requested.connect(self.open_history)
        self.window.quit_requested.connect(self.quit)
        self.hotkeys.triggered.connect(self.start_capture)
        self.hotkeys.failed.connect(self._on_hotkey_failed)
        self.app.aboutToQuit.connect(self._on_about_to_quit)

    def _register_hotkey(self, first_run: bool = False) -> None:
        cfg = self.config.config.hotkey
        if not cfg.enabled:
            self.hotkeys.stop()
            self.window.set_status("全局热键已关闭，可用悬浮窗按钮截图。", theme.WARNING)
            return
        ok = self.hotkeys.start(cfg.capture)
        if ok:
            self.window.set_status(
                f"就绪 · 按 {display_text(cfg.capture)} 即可截图解题", theme.SUCCESS
            )
        else:
            # 具体原因由 failed 信号给出（会覆盖这里的兜底文案）
            self.window.set_status("全局热键未生效，请到「设置」里换一个组合键。", theme.DANGER)

    def _on_hotkey_failed(self, message: str) -> None:
        self.window.set_status(message, theme.DANGER)
        self.tray.showMessage(cfgmod.APP_NAME, message, self._icon, 6000)

    # ============================================================ 截图流程

    def start_capture(self) -> None:
        """热键或按钮触发：先把自身窗口藏起来，避免截到自己。"""
        if self._overlay is not None:
            # 已经在框选状态：再按一次热键 = 整屏直出
            self._overlay.accept_full()
            return
        self._window_was_visible = self.window.isVisible()
        if self._window_was_visible:
            self.window.hide()
        QTimer.singleShot(CAPTURE_HIDE_DELAY_MS, self._do_capture)

    def _do_capture(self) -> None:
        try:
            image, scale, union = cap.grab_virtual_desktop()
        except Exception as e:  # noqa: BLE001
            log.exception("截屏失败")
            self._restore_window()
            self.window.set_status(f"截屏失败：{e}", theme.DANGER)
            self.tray.showMessage(cfgmod.APP_NAME, f"截屏失败：{e}", self._icon, 6000)
            return

        mode = self.config.config.capture.mode
        self._overlay = CaptureOverlay(image, scale, union, mode=mode)
        self._overlay.captured.connect(self._on_captured)
        self._overlay.cancelled.connect(self._on_capture_cancelled)
        self._overlay.start()

    def _on_captured(self, image) -> None:
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()
        self._restore_window()
        try:
            png = cap.to_png_bytes(image)
        except cap.CaptureError as e:
            self.window.set_status(f"截图编码失败：{e}", theme.DANGER)
            return
        self.window.submit_image(image, png)

    def _on_capture_cancelled(self) -> None:
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()
        self._restore_window()
        self.window.set_status("已取消截图。", theme.TEXT_MUTED)

    def _restore_window(self) -> None:
        """截图流程结束后还原悬浮窗，保持用户原来的展开/收起状态。"""
        self.window.set_collapsed(bool(self.config.config.ui.collapsed))
        self.window.show()
        self.window.raise_()

    # ============================================================ 对话框

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self.store, self.window)
        dialog.applied.connect(self._on_settings_applied)
        dialog.exec()
        dialog.deleteLater()

    def _on_settings_applied(self) -> None:
        self.app.setFont(theme.app_font(int(self.config.config.ui.font_size)))
        self.window.apply_config()
        self._register_hotkey()
        self.window.set_status("设置已保存。", theme.SUCCESS)
        # 换了模型/服务商就顺手预热，省掉下一次提问的冷启动等待
        if (self.config.config.engine.model or "") != self._warmed_model:
            self._prewarm_model()

    def open_history(self) -> None:
        if self._history is not None and self._history.isVisible():
            self._history.raise_()
            self._history.activateWindow()
            return
        self._history = HistoryDialog(self.store, self.window)
        self._history.show()
        self._history.raise_()
        self._history.activateWindow()

    def _open_data_dir(self) -> None:
        root = cfgmod.data_dir()
        root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(root)))

    # ============================================================ 托盘 / 退出

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()

    def quit(self) -> None:
        log.info("退出程序")
        self.hotkeys.stop()
        try:
            self.window._stop_worker(wait_ms=1500)
        except Exception:  # noqa: BLE001
            pass
        self.tray.hide()
        self.app.quit()

    def _on_about_to_quit(self) -> None:
        self.store.reconcile(drop_orphans=self.config.config.storage.drop_orphan_shots)
        self.store.close()


def main() -> int:
    cfgmod.ensure_dirs()
    # 首次运行把默认配置落盘，用户可直接打开 data/config.json 查看或手改
    # （load() 本身不写盘，若这里不写，用户会以为“没有配置文件”）
    if not (cfgmod.data_dir() / "config.json").is_file():
        ConfigManager().save()
    logmod.setup()
    logmod.install_excepthook()

    app = QApplication(sys.argv)
    app.setApplicationName(cfgmod.APP_NAME)
    app.setApplicationDisplayName(cfgmod.APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(theme.app_font(12))
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(theme.make_app_icon())

    lock = QLockFile(str(cfgmod.data_dir() / "app.lock"))
    if not lock.tryLock(200):
        QMessageBox.warning(
            None,
            cfgmod.APP_NAME,
            "程序已经在运行了。\n请在右下角系统托盘里找到它（双击托盘图标显示悬浮窗）。",
        )
        return 1

    controller = AppController(app)
    controller.start()
    log.info("启动完成，数据目录：%s", cfgmod.data_dir())
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
