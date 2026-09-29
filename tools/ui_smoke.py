"""界面与端到端冒烟测试（离屏渲染，不需要真实模型）。

做的事：
1. 起一个假的 OpenAI 兼容 SSE 服务，跑通「提交 → 流式分片 → 写库 → 渲染答案」全链路；
2. 覆盖截图解题路径：图片落盘、送模型体里带 image_url、记录关联图片；
3. 把悬浮窗、设置页、历史页、截图遮罩渲染成 PNG，供人工核对；
4. 校验错误路径：连不上的地址要给出中文可读提示。

用法：<项目>/.venv/Scripts/python.exe tools/ui_smoke.py
产物：_verify/*.png（供查看，确认后可删）
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_DATA = Path(tempfile.mkdtemp(prefix="jige-ui-"))
VERIFY = ROOT / "_verify"
VERIFY.mkdir(exist_ok=True)

os.environ["JIGE_DATA_DIR"] = str(TMP_DATA)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if detail and not cond else ""))


class FakeHandler(BaseHTTPRequestHandler):
    received: list[dict] = []
    pieces = ["答案：", "因为 1+1=2", "，所以 x = 42。"]

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {"_raw": raw[:200].decode("utf-8", "replace")}
        FakeHandler.received.append(body)

        if "/fail" in self.path:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"boom"}')
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for piece in FakeHandler.pieces:
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def log_message(self, *args) -> None:  # 静音
        pass


def start_fake_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def pump(app, seconds: float, until=None) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until else True


def main() -> int:
    server, port = start_fake_server()
    base_url = f"http://127.0.0.1:{port}/v1"

    try:
        # ------------------------------------------------------ 导入检查
        print("=== 模块导入 ===")
        import main as entry  # noqa: F401  只验证可导入
        check("main.py 可导入", True)

        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication

        from app import capture as cap
        from app import config as cfgmod
        from app.config import ANSWER_STYLE_MAX_TOKENS, ANSWER_STYLES, ConfigManager
        from app.engine.base import SolveRequest
        from app.engine.service import build_provider
        from app.store import SOURCE_IMAGE, SOURCE_TEXT, Store
        from app.ui import theme
        from app.ui.float_window import FloatWindow
        from app.ui.history_dialog import HistoryDialog
        from app.ui.overlay import CaptureOverlay
        from app.ui.settings_dialog import SettingsDialog

        check("全部 UI 模块可导入", True)

        app = QApplication([])
        app.setStyleSheet(theme.STYLESHEET)
        app.setFont(theme.app_font(12))

        cfgmod.ensure_dirs()
        config = ConfigManager()
        config.config.engine.provider = "custom"
        config.config.engine.base_url = base_url
        config.config.engine.model = "fake-model"
        config.config.engine.api_key = "test-key"
        config.config.engine.wire_api = "openai"
        config.config.engine.timeout = 20
        config.save()
        store = Store()

        # ------------------------------------------------------ 端到端：文字
        print("\n=== 端到端：文字解题 ===")
        window = FloatWindow(config, store)
        window.show()
        app.processEvents()

        state = {"done": False}
        window.question_edit.setPlainText("1+1 等于几？")
        window.submit_text()
        rid = window._current_rid
        check("提交后立即建了记录", bool(rid))

        window_worker = window._worker
        window_worker.done.connect(lambda *_: state.update(done=True))
        window_worker.failed.connect(lambda *_: state.update(done=True))
        finished = pump(app, 15, until=lambda: state["done"])
        check("流式解答在超时前结束", finished)

        expected = "".join(FakeHandler.pieces)
        check("答案完整拼接", window._accumulated == expected, repr(window._accumulated[:60]))
        check("界面已渲染答案", expected[:6] in window.answer_view.toPlainText())

        rec = store.get_record(rid)
        check("答案已写入数据库", bool(rec) and rec["answer"] == expected, str(rec and rec["answer"])[:60])
        check("记录状态为 ok", bool(rec) and rec["status"] == "ok")
        check("记录来源为文字", bool(rec) and rec["source"] == SOURCE_TEXT)
        check("耗时已记录", bool(rec) and rec["elapsed_ms"] >= 0)

        sent = FakeHandler.received[-1]
        check("请求体带 model", sent.get("model") == "fake-model")
        check("请求体 stream=True", sent.get("stream") is True)
        check("请求体带鉴权头之外的结构完整", "messages" in sent and len(sent["messages"]) >= 2)
        check("纯文本内容为字符串", isinstance(sent["messages"][-1]["content"], str),
              str(type(sent["messages"][-1]["content"])))
        check("温度参数下传", sent.get("temperature") is not None)

        window.grab().save(str(VERIFY / "01_float_text.png"))

        # ------------------------------------------------------ 解答风格切换
        print("\n=== 解答风格：只看答案 / 详细题解 ===")
        check("悬浮窗有风格选择框", window.style_box.count() == 2,
              str([window.style_box.itemText(i) for i in range(window.style_box.count())]))
        check("风格选项与配置一致",
              [window.style_box.itemData(i) for i in range(window.style_box.count())] == list(ANSWER_STYLES))
        check("初始跟随配置（详解）", window.style_box.currentData() == "detailed",
              str(window.style_box.currentData()))
        check("详解请求使用详解提示词",
              "解题步骤" in sent["messages"][0]["content"], sent["messages"][0]["content"][:40])

        # 切到「只看答案」：应当落盘、改提示词、并封顶输出长度
        window.style_box.setCurrentIndex(window.style_box.findData("brief"))
        app.processEvents()
        check("切换后配置立即落盘", config.config.engine.answer_style == "brief",
              config.config.engine.answer_style)
        check("切换后有状态提示", "只看答案" in window.status.text(), window.status.text())
        reloaded = ConfigManager()
        check("重开程序仍是只看答案", reloaded.config.engine.answer_style == "brief",
              reloaded.config.engine.answer_style)

        state["done"] = False
        window.question_edit.setPlainText("2+3 等于几？")
        window.submit_text()
        rid_brief = window._current_rid
        worker_b = window._worker
        worker_b.done.connect(lambda *_: state.update(done=True))
        worker_b.failed.connect(lambda *_: state.update(done=True))
        pump(app, 15, until=lambda: state["done"])

        brief_sent = FakeHandler.received[-1]
        check("简答请求改用简答提示词",
              "只给最终结果" in brief_sent["messages"][0]["content"],
              brief_sent["messages"][0]["content"][:40])
        check("简答请求封顶输出长度",
              brief_sent.get("max_tokens") == ANSWER_STYLE_MAX_TOKENS["brief"],
              str(brief_sent.get("max_tokens")))
        check("简答记录落库为 brief",
              (store.get_record(rid_brief) or {}).get("style") == "brief",
              str((store.get_record(rid_brief) or {}).get("style")))
        check("详细记录的风格仍是 detailed",
              (store.get_record(rid) or {}).get("style") == "detailed")

        # 自定义提示词时，风格开关要说清楚「不生效」，不能让人以为是 bug
        config.config.engine.system_prompt = "自定义提示词"
        window.style_box.setCurrentIndex(window.style_box.findData("detailed"))
        app.processEvents()
        check("有自定义提示词时明确提示风格不生效",
              "实际仍按自定义提示词作答" in window.status.text(), window.status.text())
        config.config.engine.system_prompt = ""
        config.config.engine.answer_style = "detailed"
        config.save()

        # 设置页改过风格之后，悬浮窗的下拉要同步过来
        window.style_box.setCurrentIndex(window.style_box.findData("brief"))
        app.processEvents()
        config.config.engine.answer_style = "detailed"
        config.save()
        window.sync_style_box()
        check("设置页改动后悬浮窗同步", window.style_box.currentData() == "detailed",
              str(window.style_box.currentData()))


        # ------------------------------------------------------ 端到端：截图
        print("\n=== 端到端：截图解题 ===")
        shot = QImage(640, 360, QImage.Format_RGB32)
        shot.fill(QColor("#F2F5FA"))
        png = cap.to_png_bytes(shot)
        check("截图可编码为 PNG", len(png) > 100, f"{len(png)} 字节")

        state["done"] = False
        window.submit_image(shot, png, note="第 3 题：求 x")
        rid2 = window._current_rid
        worker2 = window._worker
        worker2.done.connect(lambda *_: state.update(done=True))
        worker2.failed.connect(lambda *_: state.update(done=True))
        pump(app, 15, until=lambda: state["done"])

        rec2 = store.get_record(rid2)
        check("截图记录已落库", bool(rec2))
        check("截图记录来源为 image", bool(rec2) and rec2["source"] == SOURCE_IMAGE)
        check("记录关联到图片文件", bool(rec2) and bool(rec2["image_path"]))
        shot_path = store.abs_shot_path(rec2["image_path"]) if rec2 else None
        check("图片文件真实存在", bool(shot_path) and shot_path.exists(), str(shot_path))

        img_sent = FakeHandler.received[-1]["messages"][-1]["content"]
        check("多模态请求体", isinstance(img_sent, list) and len(img_sent) == 2, str(img_sent)[:80])
        check("图片以 data url 上传",
              isinstance(img_sent, list) and img_sent[1]["image_url"]["url"].startswith(
                  "data:image/jpeg;base64,"))
        check("多模态提问文本带入题干",
              isinstance(img_sent, list) and img_sent[0]["text"] == "第 3 题：求 x",
              str(img_sent[0] if isinstance(img_sent, list) else img_sent))

        window.tab_group.button(1).setChecked(True)
        window._on_tab_changed(1)
        app.processEvents()
        window.grab().save(str(VERIFY / "02_float_shot.png"))

        window.set_collapsed(True)
        app.processEvents()
        window.grab().save(str(VERIFY / "03_float_collapsed.png"))
        check("收起后窗口变小", window.width() == 56 and window.height() == 56,
              f"{window.width()}x{window.height()}")
        window.set_collapsed(False)
        app.processEvents()
        check("展开后恢复尺寸", window.width() == 400 and window.height() == 540,
              f"{window.width()}x{window.height()}")

        # ------------------------------------------------------ 错误路径
        print("\n=== 错误路径 ===")
        bad = cfgmod.AppConfig().engine
        bad.provider = "custom"
        bad.base_url = f"http://127.0.0.1:{port}/fail"
        bad.model = "fake-model"
        bad.api_key = "k"
        bad.timeout = 10
        ok, msg = build_provider(bad).test()
        check("HTTP 500 被转成可读提示", (not ok) and "HTTP 500" in msg, msg[:100])

        dead = cfgmod.AppConfig().engine
        dead.provider = "custom"
        dead.base_url = "http://127.0.0.1:59999/v1"
        dead.model = "m"
        dead.api_key = "k"
        dead.timeout = 5
        ok2, msg2 = build_provider(dead).test()
        check("连接失败提示中文可读", (not ok2) and ("无法连接" in msg2 or "超时" in msg2), msg2[:100])

        # ------------------------------------------------------ 界面渲染
        print("\n=== 界面渲染 ===")
        settings = SettingsDialog(config, store)
        settings.show()
        app.processEvents()
        settings.grab().save(str(VERIFY / "04_settings_engine.png"))
        settings.tabs.setCurrentIndex(1)
        app.processEvents()
        settings.grab().save(str(VERIFY / "05_settings_hotkey.png"))
        settings.tabs.setCurrentIndex(2)
        app.processEvents()
        settings.grab().save(str(VERIFY / "06_settings_data.png"))
        check("设置页三个标签页可渲染", settings.tabs.count() == 3)

        # 风格 / 模型驻留：设置页必须能读写回配置，否则改了等于没改
        check("设置页有解答风格下拉", settings.style_box.count() == len(ANSWER_STYLES),
              str(settings.style_box.count()))
        check("设置页风格随配置载入", settings.style_box.currentData() == "detailed",
              str(settings.style_box.currentData()))
        check("设置页有模型驻留下拉", settings.keep_alive_box.count() >= 4,
              str(settings.keep_alive_box.count()))
        check("驻留默认选中 30 分钟", settings.keep_alive_box.currentData() == "30m",
              str(settings.keep_alive_box.currentData()))
        check("留空提示词时说明「按风格自动」",
              "当前生效" in settings.prompt_note.text(), settings.prompt_note.text())
        settings.style_box.setCurrentIndex(settings.style_box.findData("brief"))
        app.processEvents()
        check("切风格后提示词说明同步更新",
              "只看答案" in settings.prompt_note.text(), settings.prompt_note.text())
        settings.prompt_edit.setPlainText("手写的提示词")
        app.processEvents()
        check("填了自定义提示词后说明转为「不生效」提示",
              "不起作用" in settings.prompt_note.text(), settings.prompt_note.text())
        settings.prompt_edit.setPlainText("")
        settings.style_box.setCurrentIndex(settings.style_box.findData("detailed"))

        settings.keep_alive_box.setCurrentIndex(settings.keep_alive_box.findData("-1"))
        settings._on_save()
        app.processEvents()
        check("保存后风格与驻留写入配置",
              config.config.engine.answer_style == "detailed"
              and config.config.engine.keep_alive == "-1",
              f"{config.config.engine.answer_style} / {config.config.engine.keep_alive}")
        reopened = SettingsDialog(config, store)
        check("重开设置页能读回驻留设置", reopened.keep_alive_box.currentData() == "-1",
              str(reopened.keep_alive_box.currentData()))
        reopened.deleteLater()
        config.config.engine.keep_alive = "30m"
        config.save()

        settings = SettingsDialog(config, store)
        settings.show()
        app.processEvents()
        # 重新截一张引擎页：让「解答风格 / 模型驻留」两个新控件进入观感验收图
        settings.grab().save(str(VERIFY / "04_settings_engine.png"))

        # 「检测本机模型」按钮：全程打桩，不联网
        from app.ui import settings_dialog as sdlg

        check("设置页有「检测本机模型」按钮", settings.detect_btn.text() == "检测本机模型")

        class _DummyInput:
            @staticmethod
            def getItem(*args, **kwargs):
                return ("qwen3.5:9b", True)

        class _DummyMsgBox:
            """同时顶替 QMessageBox 的静态弹窗和「构造函数 + addButton/exec」用法。"""

            Warning = 3
            AcceptRole = 0
            RejectRole = 1
            warned: list = []
            boxes: list = []

            def __init__(self, parent=None):
                self._buttons = []
                self._clicked = None
                self.text = ""
                _DummyMsgBox.boxes.append(self)

            def setIcon(self, *a, **k):
                return None

            def setWindowTitle(self, *a, **k):
                return None

            def setText(self, text):
                self.text = text

            def addButton(self, text, role):
                btn = object()
                self._buttons.append(btn)
                if self._clicked is None:
                    self._clicked = btn  # 模拟用户点了第一个按钮（即「检测本机模型」）
                return btn

            def exec(self):
                return 0

            def clickedButton(self):
                return self._clicked

            @staticmethod
            def warning(parent, title, text, *a, **k):
                _DummyMsgBox.warned.append(text)
                return None

            @staticmethod
            def information(*a, **k):
                return None

        _real = (sdlg.detect_models, sdlg.QInputDialog, sdlg.QMessageBox)
        sdlg.QInputDialog = _DummyInput
        sdlg.QMessageBox = _DummyMsgBox
        try:
            sdlg.detect_models = lambda cfg: ["qwen3.5:9b", "qwen2.5vl:7b"]
            settings.model_edit.setText("qwen2.5vl:7b")
            settings._on_detect_models()
            check("检测后点选可填入模型名", settings.model_edit.text() == "qwen3.5:9b",
                  settings.model_edit.text())
            check("检测后按钮文案与可用性恢复",
                  settings.detect_btn.isEnabled() and settings.detect_btn.text() == "检测本机模型",
                  settings.detect_btn.text())

            sdlg.detect_models = lambda cfg: []
            settings._on_detect_models()
            check("服务端无模型时不崩且按钮恢复", settings.detect_btn.isEnabled())

            def _boom(cfg):
                raise RuntimeError("模拟探测失败")

            sdlg.detect_models = _boom
            settings._on_detect_models()
            check("探测抛异常时按钮仍被恢复（finally 生效）", settings.detect_btn.isEnabled())
            check("探测失败给出中文提示", bool(_DummyMsgBox.warned), str(_DummyMsgBox.warned)[:80])

            # 「模型没装」的失败要直接把修复动作弹出来
            sdlg.detect_models = lambda cfg: ["qwen3.5:9b"]
            settings.model_edit.setText("qwen2.5vl:7b")
            _DummyMsgBox.boxes.clear()
            settings._on_test_done(False, "本机服务上没有找到模型「qwen2.5vl:7b」。")
            check("模型没装时弹出修复对话框", len(_DummyMsgBox.boxes) == 1,
                  f"弹出 {len(_DummyMsgBox.boxes)} 个")
            check("点修复后模型名被换成已装的", settings.model_edit.text() == "qwen3.5:9b",
                  settings.model_edit.text())

            _DummyMsgBox.boxes.clear()
            settings._on_test_done(False, "服务返回 HTTP 401。API Key 无效或未填写。")
            check("普通失败不弹修复对话框", not _DummyMsgBox.boxes)
            check("失败信息仍显示在结果区", "401" in settings.test_result.text(),
                  settings.test_result.text()[:60])
        finally:
            sdlg.detect_models, sdlg.QInputDialog, sdlg.QMessageBox = _real

        settings.close()

        history = HistoryDialog(store)
        history.show()
        app.processEvents()
        history.grab().save(str(VERIFY / "07_history.png"))
        check("历史页载入记录", history.table.rowCount() == store.count_records(),
              f"表 {history.table.rowCount()} vs 库 {store.count_records()}")
        check("历史页有风格列", history.table.columnCount() == 4,
              str([history.table.horizontalHeaderItem(i).text() for i in range(history.table.columnCount())]))
        check("风格列有中文标签",
              all(history.table.item(r, 2) is not None and history.table.item(r, 2).text() in
                  ("只看答案", "详细题解") for r in range(history.table.rowCount())),
              str([history.table.item(r, 2).text() if history.table.item(r, 2) else None
                   for r in range(history.table.rowCount())]))
        check("详情里也显示风格",
              any(k in history.meta_label.text() for k in ("只看答案", "详细题解")),
              history.meta_label.text())
        history.close()

        fake_screen = QImage(1280, 720, QImage.Format_RGB32)
        fake_screen.fill(QColor("#DCE3EE"))
        overlay = CaptureOverlay(fake_screen, 1.0, QRect(0, 0, 1280, 720), mode="region")
        overlay.show()
        overlay._origin = QPoint(160, 120)
        overlay._current = QPoint(760, 420)
        overlay._dragging = True
        overlay.update()
        app.processEvents()
        overlay.grab().save(str(VERIFY / "08_overlay_region.png"))
        check("截图遮罩可渲染", True)

        captured: list = []
        overlay.captured.connect(lambda img: captured.append(img))
        overlay._emit(QRect(100, 50, 400, 300))
        app.processEvents()
        check("遮罩按 1:1 裁出选中区域",
              bool(captured) and captured[0].width() == 400 and captured[0].height() == 300,
              str(captured[0].size()) if captured else "无输出")

        overlay2 = CaptureOverlay(fake_screen, 2.0, QRect(0, 0, 1280, 720), mode="region")
        captured2: list = []
        overlay2.captured.connect(lambda img: captured2.append(img))
        overlay2._emit(QRect(100, 50, 400, 300))
        app.processEvents()
        check("高 DPI 下按 scale 换算物理像素",
              bool(captured2) and captured2[0].width() == 800 and captured2[0].height() == 600,
              str(captured2[0].size()) if captured2 else "无输出")

        # ------------------------------------------------------ 真实抓屏
        print("\n=== 真实抓屏（离屏平台，仅要求不崩） ===")
        try:
            img, scale, union = cap.grab_virtual_desktop()
            check("grab_virtual_desktop 可用", img.width() > 0 and img.height() > 0,
                  f"{img.width()}x{img.height()} scale={scale}")
        except Exception as e:  # noqa: BLE001
            check("grab_virtual_desktop 可用", False, repr(e))

        # ------------------------------------------------------ 清理校验
        print("\n=== 数据清理 ===")
        before = store.stats()
        res = store.reconcile()
        check("对账不误删在册图片", res["orphan_deleted"] == 0, str(res))
        (store.shots / "leftover.png").write_bytes(b"x")
        res2 = store.reconcile()
        check("新增孤儿被清理", res2["orphan_deleted"] == 1, str(res2))
        cleared = store.clear_all()
        check("一键清空生效", cleared["records"] == before["records"], str(cleared))
        check("清空后无残留文件",
              not [p for p in store.shots.glob("*") if p.is_file()],
              str([p.name for p in store.shots.glob("*")]))

        window.close()
        store.close()
        settings.deleteLater()
        history.deleteLater()

        print("\n=== 结果 ===")
        print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
        if FAIL:
            print("失败项：" + ", ".join(FAIL))
        return 1 if FAIL else 0

    finally:
        server.shutdown()
        shutil.rmtree(TMP_DATA, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
